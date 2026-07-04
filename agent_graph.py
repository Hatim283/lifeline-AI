import logging
import asyncio
import time
import datetime as dt
from typing import List, Dict, Any, Optional, Literal

from schema import (
    AgentState,
    DisruptionContext,
    LogisticalAlternative,
    AutomatedCommunication,
    CalendarBlock,
    UserPreferences,
    ChatMessage
)

from mcp_tools import (
    GeminiReasoningTool,
    WeatherTool,
    MapsTool,
    CalendarTool,
    CommunicationTool,
    RiskAssessmentTool,
    ToolError,
    APIConnectionError,
    ValidationError,
    generate_utc_timestamp,
    EmergencyContact,
    WeatherData
)

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
# Orchestrator Graph
# ---------------------------------------------------------------------------
class LifelineAgentGraph:
    """Stateful dynamic orchestration workflow for Lifeline Concierge."""

    def __init__(self) -> None:
        """Initializes the required tools for the agent graph."""
        logger.info("Initializing LifelineAgentGraph tools...")
        self.reasoning_tool = GeminiReasoningTool()
        self.weather_tool = WeatherTool()
        self.maps_tool = MapsTool()
        self.calendar_tool = CalendarTool()
        self.communication_tool = CommunicationTool()
        self.risk_tool = RiskAssessmentTool()

    def _append_trace(self, state: AgentState, message: str) -> AgentState:
        logger.info(f"TRACE: {message}")
        new_trace = state.active_graph_node_tracking_steps + [message]
        return state.model_copy(update={"active_graph_node_tracking_steps": new_trace})

    async def _node_assessor(self, state: AgentState, raw_input: str) -> AgentState:
        """Analyzes incoming disruption information and updates state."""
        start_time = time.time()
        logger.info("Starting Assessor Node")
        try:
            disruption = await self.reasoning_tool.summarize_disruption(raw_input)
            
            if isinstance(disruption, dict) and disruption.get("status") in ("disabled", "error"):
                logger.error(f"Assessor Error (Self-Correcting): {disruption.get('reason')}")
                state = self._append_trace(state, f"⚠️ Incident classification failed: {disruption.get('reason')}")
                # We can't really continue without disruption context, but we will not crash.
                state = state.model_copy(update={"workflow_status": "error", "last_updated": generate_utc_timestamp()})
                return state
                
            active_disruptions = state.active_disruptions.copy()
            active_disruptions.append(disruption) # type: ignore
            
            state = self._append_trace(state, f"✓ Incident classified as {disruption.incident_type}")
            state = state.model_copy(update={
                "active_disruptions": active_disruptions,
                "workflow_status": "planning",
                "last_updated": generate_utc_timestamp()
            })
            return state
        except Exception as e:
            logger.error(f"Assessor Node failed: {e}")
            state = self._append_trace(state, "⚠️ Incident classification critical failure.")
            return state.model_copy(update={"workflow_status": "error"})

    async def _node_weather(self, state: AgentState) -> AgentState:
        """Fetches weather data."""
        logger.info("Starting Weather Node")
        if not state.active_disruptions:
            return state
            
        disruption = state.active_disruptions[-1]
        lat, lon = disruption.latitude, disruption.longitude
        flags = state.validation_flags.copy()
        
        if lat is not None and lon is not None:
            try:
                weather_data_res = await self.weather_tool.get_weather(lat, lon)
                if isinstance(weather_data_res, dict) and weather_data_res.get("status") in ("disabled", "error"):
                    logger.warning(f"Weather tool unavailable: {weather_data_res.get('reason')}")
                    flags["weather_data_fetched"] = False
                    flags["weather_service_unavailable"] = True
                    state = self._append_trace(state, "⚠️ Weather retrieval failed (continuing without weather data)")
                else:
                    flags["weather_data_fetched"] = True
                    flags["weather_service_unavailable"] = False
                    
                    weather_list = weather_data_res.get("weather", [])
                    weather_desc = weather_list[0].get("main", "") if weather_list else "Unknown"
                    state = self._append_trace(state, f"✓ Weather retrieved: {weather_desc}")
                    
                    # Store weather data in workflow metadata for the risk engine later
                    meta = state.workflow_metadata.copy()
                    meta["current_weather"] = weather_data_res
                    state = state.model_copy(update={"workflow_metadata": meta})
            except Exception as e:
                logger.warning(f"Failed to fetch weather: {e}")
                flags["weather_data_fetched"] = False
                flags["weather_service_unavailable"] = True
                state = self._append_trace(state, "⚠️ Weather retrieval critical failure")

        return state.model_copy(update={"validation_flags": flags, "last_updated": generate_utc_timestamp()})

    async def _node_maps(self, state: AgentState) -> AgentState:
        """Fetches maps / nearby services data."""
        logger.info("Starting Maps Node")
        if not state.active_disruptions:
            return state
            
        disruption = state.active_disruptions[-1]
        lat, lon = disruption.latitude, disruption.longitude
        flags = state.validation_flags.copy()
        
        if lat is not None and lon is not None:
            try:
                services = await self.maps_tool.search_nearby_services(lat, lon, "hospitals")
                if isinstance(services, dict) and services.get("status") in ("disabled", "error"):
                    logger.warning(f"Maps tool unavailable: {services.get('reason')}")
                    flags["nearby_hospitals_found"] = False
                    flags["maps_service_unavailable"] = True
                    state = self._append_trace(state, "⚠️ Maps service unavailable")
                else:
                    found = len(services) > 0 # type: ignore
                    flags["nearby_hospitals_found"] = found
                    flags["maps_service_unavailable"] = False
                    state = self._append_trace(state, f"✓ Maps analyzed (Hospitals nearby: {found})")
            except Exception as e:
                logger.warning(f"Failed to fetch maps: {e}")
                flags["nearby_hospitals_found"] = False
                flags["maps_service_unavailable"] = True
                state = self._append_trace(state, "⚠️ Maps analysis critical failure")

        return state.model_copy(update={"validation_flags": flags, "last_updated": generate_utc_timestamp()})

    async def _node_calendar(self, state: AgentState) -> AgentState:
        """Fetches calendar conflict data."""
        logger.info("Starting Calendar Node")
        if not state.active_disruptions:
            return state
            
        disruption = state.active_disruptions[-1]
        flags = state.validation_flags.copy()
        
        try:
            proposed_event = CalendarBlock(
                event_name="Disruption Recovery",
                location="Current Location",
                start_time=disruption.local_timestamp,
                end_time=disruption.local_timestamp + dt.timedelta(hours=2),
                is_critical=True
            )
            conflicts = await self.calendar_tool.find_conflicts(state.current_calendar, proposed_event)
            if isinstance(conflicts, dict) and conflicts.get("status") in ("disabled", "error"):
                logger.warning(f"Calendar tool unavailable: {conflicts.get('reason')}")
                flags["calendar_conflicts_detected"] = False
                flags["calendar_service_unavailable"] = True
                state = self._append_trace(state, "⚠️ Calendar check failed (continuing)")
            else:
                has_conflicts = len(conflicts) > 0 # type: ignore
                flags["calendar_conflicts_detected"] = has_conflicts
                flags["calendar_service_unavailable"] = False
                state = self._append_trace(state, f"✓ Calendar checked ({len(conflicts)} conflicts detected)")
        except Exception as e:
            logger.warning(f"Failed to check calendar: {e}")
            flags["calendar_conflicts_detected"] = False
            flags["calendar_service_unavailable"] = True
            state = self._append_trace(state, "⚠️ Calendar check critical failure")

        return state.model_copy(update={"validation_flags": flags, "last_updated": generate_utc_timestamp()})

    async def _node_planner(self, state: AgentState) -> AgentState:
        """Generates and ranks logistical alternatives, and computes risk."""
        logger.info("Starting Planner Node")
        if not state.active_disruptions:
            return state
            
        disruption = state.active_disruptions[-1]
        
        # Calculate Risk Score first
        flags = state.validation_flags.copy()
        has_conflicts = flags.get("calendar_conflicts_detected", False)
        weather_data = state.workflow_metadata.get("current_weather", {})
        
        risk_score_val = 0.0
        risk_explanation_val = "Risk assessment unavailable."
        try:
            score_result = await self.risk_tool.calculate_risk_score(
                disruption=disruption,
                has_calendar_conflicts=has_conflicts,
                weather_conditions=weather_data,
                travel_delay_minutes=60 
            )
            if not (isinstance(score_result, dict) and score_result.get("status") in ("disabled", "error")):
                risk_score_val, risk_explanation_val = score_result # type: ignore
                flags["high_risk"] = risk_score_val >= 50.0
                state = self._append_trace(state, f"✓ Risk calculated (Score: {risk_score_val:.0f})")
            else:
                state = self._append_trace(state, "⚠️ Risk calculation failed")
        except Exception as e:
            logger.warning(f"Failed to calculate risk score: {e}")
        
        # Generate Alternatives
        try:
            alternatives = await self.reasoning_tool.generate_alternative_plan(
                disruption=disruption,
                prefs=state.user_preferences
            )
            
            if isinstance(alternatives, dict) and alternatives.get("status") in ("disabled", "error"):
                logger.warning(f"Failed to generate alternatives: {alternatives.get('reason')}")
                state = self._append_trace(state, "⚠️ Logistics planning failed")
                return state.model_copy(update={"validation_flags": flags, "risk_score": risk_score_val, "risk_explanation": risk_explanation_val})
            
            sorted_alts = sorted(
                alternatives, # type: ignore
                key=lambda x: (-x.confidence_score, x.estimated_eta, x.additional_cost_normalized)
            )
            
            state = self._append_trace(state, f"✓ Alternatives ranked ({len(sorted_alts)} options generated)")
            
            return state.model_copy(update={
                "validation_flags": flags,
                "risk_score": risk_score_val,
                "risk_explanation": risk_explanation_val,
                "logistical_alternatives": sorted_alts,
                "last_updated": generate_utc_timestamp()
            })
        except Exception as e:
            logger.error(f"Planner Node failed: {e}")
            state = self._append_trace(state, "⚠️ Logistics planning critical failure")
            return state.model_copy(update={"validation_flags": flags, "risk_score": risk_score_val, "risk_explanation": risk_explanation_val})

    async def _node_communication(self, state: AgentState) -> AgentState:
        """Drafts stakeholder notifications."""
        logger.info("Starting Communication Node")
        if not state.active_disruptions or not state.user_preferences.default_emergency_contacts:
            state = self._append_trace(state, "⚠️ No emergency contacts available for communication")
            return state
            
        disruption = state.active_disruptions[-1]
        raw_contact = state.user_preferences.default_emergency_contacts[0]
        
        contact: EmergencyContact = {
            "name": raw_contact.get("name", "Stakeholder"),
            "phone": raw_contact.get("phone", ""),
            "relation": raw_contact.get("relation", "")
        }
        
        channel_str = (
            state.user_preferences.notification_channels[0] 
            if state.user_preferences.notification_channels 
            else "Email"
        )
        channel: Literal["WhatsApp", "Email"] = "WhatsApp" if channel_str == "WhatsApp" else "Email"
        
        try:
            comm_draft = await self.reasoning_tool.draft_communication(
                disruption=disruption,
                contact=contact,
                channel=channel
            )
            
            if isinstance(comm_draft, dict) and comm_draft.get("status") in ("disabled", "error"):
                logger.warning(f"Failed to draft communication: {comm_draft.get('reason')}")
                state = self._append_trace(state, "⚠️ Communication drafting failed")
                return state
            
            state = await self.communication_tool.queue_message(comm_draft, state) # type: ignore
            state = self._append_trace(state, "✓ Communication drafted and queued")
            return state
        except Exception as e:
            logger.error(f"Communication Node failed: {e}")
            state = self._append_trace(state, "⚠️ Communication drafting critical failure")
            return state

    async def _node_approval(self, state: AgentState) -> AgentState:
        """Updates workflow status at the end."""
        try:
            if state.workflow_status == "error":
                return state
                
            if state.pending_communications or state.logistical_alternatives:
                status: Literal["idle", "planning", "executing", "awaiting_user", "completed", "error"] = "awaiting_user"
            else:
                status = "completed"
                
            return state.model_copy(update={
                "workflow_status": status,
                "last_updated": generate_utc_timestamp()
            })
        except Exception as e:
            logger.error(f"Approval Node failed: {e}")
            return state

    async def run(self, state: AgentState, raw_input: str) -> AgentState:
        """Executes the orchestration workflow securely and dynamically.
        
        Args:
            state: The initial state configuration.
            raw_input: Raw context string from user.
            
        Returns:
            The final derived AgentState post graph execution.
        """
        logger.info(f"--- Starting Dynamic LifelineAgentGraph Execution for Session: {state.current_session_id} ---")
        overall_start = time.time()

        try:
            # Step 1: Always Assess the user's new input
            state = await self._node_assessor(state, raw_input)
            if state.workflow_status == "error":
                logger.warning("Workflow aborted early due to Assessor Error.")
                return state

            # Step 2: Dynamic Routing Loop
            max_steps = 10
            step_count = 0
            
            while step_count < max_steps:
                step_count += 1
                decision = await self.reasoning_tool.decide_next_step(state.model_dump(mode='json'))
                
                if decision == "WEATHER":
                    state = await self._node_weather(state)
                elif decision == "MAPS":
                    state = await self._node_maps(state)
                elif decision == "CALENDAR":
                    state = await self._node_calendar(state)
                elif decision == "PLANNER":
                    state = await self._node_planner(state)
                elif decision == "COMMUNICATION":
                    state = await self._node_communication(state)
                elif decision == "FINISH":
                    logger.info("Graph Router decided to FINISH workflow.")
                    break
                else:
                    logger.warning(f"Unknown router decision: {decision}. Exiting loop.")
                    break
                    
                if state.workflow_status == "error":
                    logger.error("Workflow entered error state during dynamic routing. Halting loop.")
                    break

            if step_count >= max_steps:
                logger.warning("Maximum graph iterations reached. Forced exit.")

            # Step 3: Finalize status
            state = await self._node_approval(state)
            
        except Exception as e:
            logger.error(f"Critical unhandled error in LifelineAgentGraph: {e}")
            state = state.model_copy(update={
                "workflow_status": "error",
                "last_updated": generate_utc_timestamp()
            })
            
        overall_elapsed = time.time() - overall_start
        logger.info(f"--- Dynamic Execution Finished in {overall_elapsed:.2f}s | Status: {state.workflow_status} ---")
        return state
