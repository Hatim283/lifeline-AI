import os
import json
import logging
import asyncio
import time
import random
import httpx
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Literal, TypedDict, cast
from abc import ABC, abstractmethod
from pydantic import BaseModel

import google.generativeai as genai
from config import settings

from schema import (
    UserPreferences,
    CalendarBlock,
    DisruptionContext,
    LogisticalAlternative,
    AutomatedCommunication,
    ChatMessage,
    AgentState
)

# ---------------------------------------------------------------------------
# Constants & Caching
# ---------------------------------------------------------------------------
DEFAULT_GEMINI_MODEL = "gemini-1.5-pro"
API_CACHE: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class ToolError(Exception):
    """Base exception for all tool-related errors."""
    pass

class APIConnectionError(ToolError):
    """Raised when an external API connection fails or quota is exceeded."""
    pass

class ValidationError(ToolError):
    """Raised when input or output validation fails."""
    pass

# ---------------------------------------------------------------------------
# TypedDicts for API Responses
# ---------------------------------------------------------------------------
class WeatherCondition(TypedDict):
    main: str
    description: str

class WeatherMain(TypedDict):
    temp: float
    humidity: int

class WeatherData(TypedDict):
    weather: List[WeatherCondition]
    main: WeatherMain

class PlaceResult(TypedDict):
    name: str
    vicinity: str
    rating: float

class EmergencyContact(TypedDict, total=False):
    name: str
    phone: str
    relation: str

# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------
def generate_utc_timestamp() -> datetime:
    return datetime.now(timezone.utc)



def normalize_response(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k.lower(): v for k, v in data.items()}

async def with_retry_httpx(
    coro_func: Callable[..., Any], 
    *args: Any, 
    max_retries: int = 3, 
    base_delay: float = 1.0, 
    **kwargs: Any
) -> Any:
    last_err = None
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (401, 403):
                raise APIConnectionError(f"Auth error {status}: {str(e)}") from e
            if 400 <= status < 500 and status != 429:
                raise APIConnectionError(f"Client error {status}: {str(e)}") from e
            last_err = e
        except httpx.RequestError as e:
            last_err = e
        except APIConnectionError as e:
            if "denied" in str(e).lower() or "unauthorized" in str(e).lower():
                raise e 
            last_err = e
        except Exception as e:
            last_err = e

        if attempt == max_retries - 1:
            logger.error(f"All {max_retries} retries failed for {getattr(coro_func, '__name__', 'func')}")
            raise APIConnectionError(f"Operation failed after retries: {str(last_err)}") from last_err
        
        delay = base_delay * (2 ** attempt) + random.uniform(0.1, 1.0)
        logger.warning(f"Transient error. Attempt {attempt + 1} failed. Retrying in {delay:.2f}s...")
        await asyncio.sleep(delay)



# ---------------------------------------------------------------------------
# Communication Providers
# ---------------------------------------------------------------------------
class BaseCommunicationProvider(ABC):
    @abstractmethod
    async def send_message(self, recipient: str, message: str) -> bool:
        pass

class MockProvider(BaseCommunicationProvider):
    async def send_message(self, recipient: str, message: str) -> bool:
        logger.info(f"[MockProvider] Sending message to {recipient}: {message}")
        await asyncio.sleep(0.5)
        return True

class ConsoleProvider(BaseCommunicationProvider):
    async def send_message(self, recipient: str, message: str) -> bool:
        print(f"\n--- MESSAGE TO: {recipient} ---\n{message}\n-------------------------------\n")
        return True

class EmailProvider(BaseCommunicationProvider):
    async def send_message(self, recipient: str, message: str) -> bool:
        logger.info(f"[EmailProvider] Simulating email to {recipient}")
        await asyncio.sleep(1.0)
        return True

class WhatsAppProvider(BaseCommunicationProvider):
    async def send_message(self, recipient: str, message: str) -> bool:
        logger.info(f"[WhatsAppProvider] Simulating WhatsApp to {recipient}")
        await asyncio.sleep(1.0)
        return True

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class GeminiReasoningTool:
    
    def __init__(self) -> None:
        self.api_key = settings.gemini_api_key
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)

    async def decide_next_step(self, state_dict: Dict[str, Any]) -> str:
        """Determines the next required node in the agentic graph dynamically."""
        start_time = time.time()
        tool_name = "GeminiReasoningTool.decide_next_step"
        
        cache_key = f"decide_step_{hash(json.dumps(state_dict, default=str))}"
        if cache_key in API_CACHE:
            return API_CACHE[cache_key]

        class NodeDecision(BaseModel):
            next_node: Literal["ASSESSMENT", "WEATHER", "MAPS", "CALENDAR", "PLANNER", "COMMUNICATION", "FINISH"]

        prompt = (
            f"You are the routing engine for an autonomous crisis concierge agent.\n"
            f"Review the following agent state:\n{json.dumps(state_dict, indent=2, default=str)}\n\n"
            f"Which node should be executed next? Choose EXACTLY ONE from this list:\n"
            f"- ASSESSMENT (if disruption is not yet classified)\n"
            f"- WEATHER (if weather data is missing and potentially relevant)\n"
            f"- MAPS (if location context/travel time is missing and relevant)\n"
            f"- CALENDAR (if calendar conflicts have not been checked)\n"
            f"- PLANNER (if we have enough context to generate logistical alternatives)\n"
            f"- COMMUNICATION (if alternatives exist and we need to draft a message)\n"
            f"- FINISH (if all necessary steps are completed and we are awaiting user approval or idle)"
        )
        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=NodeDecision
                )
            )
            decision = json.loads(response.text)["next_node"]
            
            elapsed = time.time() - start_time
            logger.info(f"[{elapsed:.2f}s] {tool_name} -> {decision}")
            API_CACHE[cache_key] = decision
            return decision
        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return "FINISH"

    async def summarize_disruption(self, raw_input: str) -> DisruptionContext | Dict[str, str]:
        start_time = time.time()
        tool_name = "GeminiReasoningTool.summarize_disruption"
        
        prompt = (
            f"Analyze the following user input and classify the disruption. "
            f"Input: {raw_input}"
        )
        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=DisruptionContext
                )
            )
            data = json.loads(response.text)
            
            data["local_timestamp"] = data.get("local_timestamp") or generate_utc_timestamp().isoformat()
            data["raw_user_input_string"] = raw_input
            if "incident_type" not in data:
                data["incident_type"] = "Other"
                
            try:
                context = DisruptionContext.model_validate(data)
            except Exception as ve:
                raise ValidationError(f"Schema validation failed for summarize_disruption: {ve}")
                
            elapsed = time.time() - start_time
            logger.info(f"Successfully executed {tool_name} in {elapsed:.2f}s")
            return context
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Failed {tool_name} after {elapsed:.2f}s: {e}")
            return {"status": "error", "reason": str(e)}

    async def generate_alternative_plan(
        self, 
        disruption: DisruptionContext, 
        prefs: UserPreferences
    ) -> List[LogisticalAlternative] | Dict[str, str]:
        start_time = time.time()
        tool_name = "GeminiReasoningTool.generate_alternative_plan"
        
        prompt = (
            f"Generate logistical alternatives for an incident of type {disruption.incident_type}. "
            f"User prefers: {prefs.preferred_transport_modes}. "
        )
        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=list[LogisticalAlternative]
                )
            )
            data = json.loads(response.text)
            
            alternatives: List[LogisticalAlternative] = []
            for item in data:
                item["estimated_eta"] = item.get("estimated_eta") or generate_utc_timestamp().isoformat()
                
                booking_url = item.get("booking_url")
                if booking_url:
                    parsed = urlparse(booking_url)
                    if not parsed.scheme or not parsed.netloc or parsed.scheme not in ("http", "https"):
                        item["booking_url"] = None

                try:
                    alt = LogisticalAlternative.model_validate(item)
                    alternatives.append(alt)
                except Exception as ve:
                    logger.warning(f"Skipping invalid alternative due to schema validation: {ve}")
                    
            if not alternatives:
                raise ValidationError("No valid alternatives could be extracted from the response.")
                
            elapsed = time.time() - start_time
            logger.info(f"Successfully executed {tool_name} in {elapsed:.2f}s")
            return alternatives
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Failed {tool_name} after {elapsed:.2f}s: {e}")
            return {"status": "error", "reason": str(e)}

    async def draft_communication(
        self, 
        disruption: DisruptionContext, 
        contact: EmergencyContact,
        channel: Literal["WhatsApp", "Email"]
    ) -> AutomatedCommunication | Dict[str, str]:
        start_time = time.time()
        tool_name = "GeminiReasoningTool.draft_communication"
        
        recipient_name = contact.get("name", "Stakeholder")
        prompt = (
            f"Draft a brief, professional {channel} message to {recipient_name} "
            f"explaining a delay due to: {disruption.incident_type}."
        )
        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=AutomatedCommunication
                )
            )
            data = json.loads(response.text)
            comm_data = {
                "recipient_name": data.get("recipient_name", recipient_name),
                "communication_channel": channel,
                "generated_message_draft": data.get("generated_message_draft", ""),
                "user_approval_granted": False
            }
            try:
                comm = AutomatedCommunication.model_validate(comm_data)
            except Exception as ve:
                raise ValidationError(f"Draft validation failed: {ve}")
                
            elapsed = time.time() - start_time
            logger.info(f"Successfully executed {tool_name} in {elapsed:.2f}s")
            return comm
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Failed {tool_name} after {elapsed:.2f}s: {e}")
            return {"status": "error", "reason": str(e)}

class WeatherTool:
    
    def __init__(self) -> None:
        self.api_key = settings.openweather_api_key
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"

    async def _fetch_weather(self, lat: float, lon: float) -> WeatherData:
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValidationError(f"Invalid coordinates: lat={lat}, lon={lon}")
            
        params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"}
        async with httpx.AsyncClient() as client:
            response = await client.get(self.base_url, params=params, timeout=10.0)
            
            if response.status_code == 401:
                raise APIConnectionError("Unauthorized OpenWeather API key.")
            elif response.status_code >= 500:
                raise APIConnectionError(f"OpenWeather API outage: HTTP {response.status_code}")
                
            response.raise_for_status()
            data = normalize_response(response.json())
            
            if "main" not in data or "weather" not in data or not data["weather"]:
                raise ValidationError("Missing required weather fields in API response.")
                
            return cast(WeatherData, data)

    async def get_weather(self, latitude: float, longitude: float) -> Any:
        start_time = time.time()
        tool_name = "WeatherTool.get_weather"
        
        if not self.api_key:
            return {"status": "disabled", "reason": "OPENWEATHER_API_KEY not configured"}
            
        cache_key = f"weather_{round(latitude,2)}_{round(longitude,2)}"
        if cache_key in API_CACHE:
            return API_CACHE[cache_key]
            
        try:
            data = await with_retry_httpx(self._fetch_weather, latitude, longitude)
            API_CACHE[cache_key] = data
            return data
        except Exception as e:
            return {"status": "error", "reason": str(e)}

class MapsTool:
    
    def __init__(self) -> None:
        self.api_key = settings.google_maps_api_key
        self.geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
        self.directions_url = "https://maps.googleapis.com/maps/api/directions/json"
        self.places_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

    def _handle_maps_status(self, data: Dict[str, Any]) -> None:
        status = data.get("status", "UNKNOWN")
        if status == "ZERO_RESULTS":
            raise ValidationError("No results found for the given input.")
        elif status == "OVER_QUERY_LIMIT":
            raise APIConnectionError("Google Maps API quota exceeded.")
        elif status == "REQUEST_DENIED":
            raise APIConnectionError("Google Maps API request denied (check API key).")
        elif status != "OK":
            raise ToolError(f"Google Maps API error: {status}")

    async def _geocode(self, address: str) -> Dict[str, Any]:
        params = {"address": address, "key": self.api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(self.geocode_url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            self._handle_maps_status(data)
            return normalize_response(data)

    async def geocode_location(self, address: str) -> Any:
        start_time = time.time()
        tool_name = "MapsTool.geocode_location"
        
        if not self.api_key:
            return {"status": "disabled", "reason": "GOOGLE_MAPS_API_KEY not configured"}

        cache_key = f"geocode_{address}"
        if cache_key in API_CACHE:
            return API_CACHE[cache_key]

        try:
            data = await with_retry_httpx(self._geocode, address)
            results = data.get("results", [])
            if not results:
                raise ValidationError("No geocoding results found.")
                
            geometry = results[0].get("geometry", {})
            location = geometry.get("location", {})
            if "lat" not in location or "lng" not in location:
                raise ValidationError("Missing geometry/location in geocode response.")
                
            lat, lng = float(location["lat"]), float(location["lng"])
            API_CACHE[cache_key] = (lat, lng)
            return lat, lng
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    async def _get_directions(self, origin: str, destination: str) -> Dict[str, Any]:
        params = {"origin": origin, "destination": destination, "key": self.api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(self.directions_url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            self._handle_maps_status(data)
            return normalize_response(data)

    async def estimate_travel_time(self, origin: str, destination: str) -> Any:
        start_time = time.time()
        tool_name = "MapsTool.estimate_travel_time"
        
        if not self.api_key:
            return {"status": "disabled", "reason": "GOOGLE_MAPS_API_KEY not configured"}

        try:
            data = await with_retry_httpx(self._get_directions, origin, destination)
            routes = data.get("routes", [])
            if not routes:
                raise ValidationError("No routes found between origin and destination.")
                
            legs = routes[0].get("legs", [])
            if not legs:
                raise ValidationError("No legs found in the generated route.")
                
            duration_data = legs[0].get("duration")
            if not duration_data or "value" not in duration_data:
                raise ValidationError("Missing duration value in route legs.")
                
            duration_min = int(duration_data["value"] / 60)
            return duration_min
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    async def _search_places(self, lat: float, lon: float, keyword: str) -> Dict[str, Any]:
        params = {
            "location": f"{lat},{lon}",
            "radius": 5000,
            "keyword": keyword,
            "key": self.api_key
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(self.places_url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            self._handle_maps_status(data)
            return normalize_response(data)

    async def search_nearby_services(self, latitude: float, longitude: float, service_type: str) -> Any:
        start_time = time.time()
        tool_name = "MapsTool.search_nearby_services"
        
        if not self.api_key:
            return {"status": "disabled", "reason": "GOOGLE_MAPS_API_KEY not configured"}
        
        valid_services = {"hospitals", "hotels", "taxis", "repair shops", "airports"}
        if service_type.lower() not in valid_services:
            return {"status": "error", "reason": f"Invalid service type: {service_type}"}

        cache_key = f"places_{round(latitude,2)}_{round(longitude,2)}_{service_type}"
        if cache_key in API_CACHE:
            return API_CACHE[cache_key]

        try:
            data = await with_retry_httpx(self._search_places, latitude, longitude, service_type)
            results = data.get("results", [])
            
            normalized_results: List[PlaceResult] = []
            for place in results:
                normalized_results.append({
                    "name": place.get("name", "Unknown"),
                    "vicinity": place.get("vicinity", "Unknown"),
                    "rating": float(place.get("rating", 0.0))
                })
                
            API_CACHE[cache_key] = normalized_results
            return normalized_results
        except Exception as e:
            return {"status": "error", "reason": str(e)}

class CalendarTool:
    
    def __init__(self) -> None:
        self.credentials_configured = settings.google_calendar_credentials is not None

    async def find_conflicts(self, current_schedule: List[CalendarBlock], proposed_event: CalendarBlock) -> Any:
        tool_name = "CalendarTool.find_conflicts"
        
        if not self.credentials_configured:
            return {"status": "disabled", "reason": "GOOGLE_CALENDAR_CREDENTIALS not configured"}
            
        try:
            conflicts = []
            for event in current_schedule:
                if (proposed_event.start_time < event.end_time and 
                    proposed_event.end_time > event.start_time):
                    conflicts.append(event)
            return conflicts
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    async def suggest_reschedule(self, conflicting_event: CalendarBlock, delay_minutes: int) -> Any:
        if not self.credentials_configured:
            return {"status": "disabled", "reason": "GOOGLE_CALENDAR_CREDENTIALS not configured"}
            
        try:
            import datetime as dt
            time_delta = dt.timedelta(minutes=delay_minutes)
            new_event = conflicting_event.model_copy(update={
                "start_time": conflicting_event.start_time + time_delta,
                "end_time": conflicting_event.end_time + time_delta
            })
            return new_event
        except Exception as e:
            return {"status": "error", "reason": str(e)}

class CommunicationTool:
    
    def __init__(self) -> None:
        self.providers: Dict[str, BaseCommunicationProvider] = {
            "Email": EmailProvider(),
            "WhatsApp": WhatsAppProvider(),
            "Console": ConsoleProvider(),
            "Mock": MockProvider()
        }

    async def validate_message(self, communication: AutomatedCommunication) -> bool:
        try:
            if len(communication.generated_message_draft) < 10:
                return False
            return True
        except Exception as e:
            raise ToolError(f"Message validation failed: {str(e)}") from e

    async def execute_message(self, communication: AutomatedCommunication) -> bool:
        provider = self.providers.get(communication.communication_channel, self.providers["Mock"])
        return await provider.send_message(communication.recipient_name, communication.generated_message_draft)

    async def queue_message(self, communication: AutomatedCommunication, state: AgentState) -> AgentState:
        try:
            new_pending = state.pending_communications + [communication]
            new_state = state.model_copy(update={
                "pending_communications": new_pending,
                "last_updated": generate_utc_timestamp()
            })
            return new_state
        except Exception as e:
            raise ToolError(f"Queueing message failed: {str(e)}") from e

class RiskAssessmentTool:

    async def calculate_risk_score(
        self,
        disruption: DisruptionContext,
        has_calendar_conflicts: bool,
        weather_conditions: WeatherData,
        travel_delay_minutes: int
    ) -> Tuple[float, str] | Dict[str, str]:
        """Calculates a risk score from 0.0 to 100.0 and provides an explanation."""
        start_time = time.time()
        tool_name = "RiskAssessmentTool.calculate_risk_score"
        try:
            score = 0.0
            explanation_parts = []

            high_risk_incidents = {"Medical Emergency", "Vehicle Breakdown"}
            if disruption.incident_type in high_risk_incidents:
                score += 40.0
                explanation_parts.append(f"High risk incident type: {disruption.incident_type}.")
            elif disruption.incident_type == "Weather Emergency":
                score += 30.0
                explanation_parts.append("Weather emergency declared.")
            else:
                score += 10.0
                explanation_parts.append(f"Standard incident type: {disruption.incident_type}.")

            if has_calendar_conflicts:
                score += 20.0
                explanation_parts.append("Schedule conflicts detected.")

            if travel_delay_minutes > 120:
                score += 30.0
                explanation_parts.append(f"Severe travel delay of {travel_delay_minutes} mins.")
            elif travel_delay_minutes > 30:
                score += 15.0
                explanation_parts.append(f"Moderate travel delay of {travel_delay_minutes} mins.")

            weather_list = weather_conditions.get("weather", [])
            weather_desc = weather_list[0].get("main", "").lower() if weather_list else ""
            if weather_desc in {"thunderstorm", "snow", "extreme"}:
                score += 10.0
                explanation_parts.append(f"Adverse weather conditions: {weather_desc}.")

            final_score = min(max(score, 0.0), 100.0)
            explanation = " ".join(explanation_parts)

            elapsed = time.time() - start_time
            logger.info(f"Successfully executed {tool_name} in {elapsed:.2f}s")
            return final_score, explanation
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Failed {tool_name} after {elapsed:.2f}s: {e}")
            return {"status": "error", "reason": str(e)}
