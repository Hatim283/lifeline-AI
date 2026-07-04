import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone
import datetime as dt

os.environ["GEMINI_API_KEY"] = "test"
os.environ["OPENWEATHER_API_KEY"] = "test"
os.environ["GOOGLE_MAPS_API_KEY"] = "test"

from mcp_tools import (
    GeminiReasoningTool,
    WeatherTool,
    MapsTool,
    CalendarTool,
    CommunicationTool,
    RiskAssessmentTool,
    ToolError,
    APIConnectionError,
    ValidationError
)
from schema import (
    DisruptionContext,
    UserPreferences,
    LogisticalAlternative,
    AutomatedCommunication,
    AgentState,
    CalendarBlock
)

@pytest.fixture
def disruption_context():
    return DisruptionContext(
        incident_type="Flight Delay",
        local_timestamp=datetime.now(timezone.utc),
        latitude=0.0,
        longitude=0.0,
        raw_user_input_string="Flight delayed"
    )

@pytest.mark.asyncio
@patch("mcp_tools.genai.GenerativeModel")
async def test_gemini_summarize_disruption(mock_model):
    mock_gen_content = AsyncMock()
    mock_gen_content.return_value.text = '{"incident_type": "Flight Delay", "latitude": 0.0, "longitude": 0.0}'
    mock_instance = mock_model.return_value
    mock_instance.generate_content_async = mock_gen_content

    tool = GeminiReasoningTool()
    res = await tool.summarize_disruption("Flight delayed")
    
    assert res.incident_type == "Flight Delay"
    assert res.latitude == 0.0

@pytest.mark.asyncio
@patch("mcp_tools.genai.GenerativeModel")
async def test_gemini_summarize_disruption_invalid_json(mock_model):
    mock_gen_content = AsyncMock()
    mock_gen_content.return_value.text = 'not valid json'
    mock_instance = mock_model.return_value
    mock_instance.generate_content_async = mock_gen_content

    tool = GeminiReasoningTool()
    res = await tool.summarize_disruption("Flight delayed")
    assert isinstance(res, dict)
    assert res.get("status") == "error"

@pytest.mark.asyncio
@patch("mcp_tools.httpx.AsyncClient.get")
async def test_weather_tool_success(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "weather": [{"main": "Clear", "description": "clear sky"}],
        "main": {"temp": 20.0, "humidity": 50}
    }
    mock_get.return_value = mock_resp

    tool = WeatherTool()
    data = await tool.get_weather(0.0, 0.0)
    assert data["weather"][0]["main"] == "Clear"
    assert data["main"]["temp"] == 20.0

@pytest.mark.asyncio
@patch("mcp_tools.httpx.AsyncClient.get")
async def test_weather_tool_unauthorized(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    tool = WeatherTool()
    res = await tool.get_weather(1.0, 1.0)
    assert isinstance(res, dict)
    assert res.get("status") == "error"

@pytest.mark.asyncio
@patch("mcp_tools.httpx.AsyncClient.get")
async def test_maps_tool_geocode_success(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "OK",
        "results": [{"geometry": {"location": {"lat": 10.0, "lng": 20.0}}}]
    }
    mock_get.return_value = mock_resp

    tool = MapsTool()
    lat, lng = await tool.geocode_location("Test Address")
    assert lat == 10.0
    assert lng == 20.0

@pytest.mark.asyncio
async def test_calendar_tool_find_conflicts():
    tool = CalendarTool()
    tool.credentials_configured = True  # Mock configured credentials for the test
    now = datetime.now(timezone.utc)
    ev1 = CalendarBlock(
        event_name="Event 1", location="", start_time=now, end_time=now + dt.timedelta(hours=1), is_critical=True
    )
    ev2 = CalendarBlock(
        event_name="Event 2", location="", start_time=now + dt.timedelta(minutes=30), end_time=now + dt.timedelta(hours=2), is_critical=False
    )
    
    conflicts = await tool.find_conflicts([ev1], ev2)
    assert isinstance(conflicts, list)
    assert len(conflicts) == 1
    assert conflicts[0].event_name == "Event 1"

@pytest.mark.asyncio
async def test_communication_tool_validate():
    tool = CommunicationTool()
    comm = AutomatedCommunication(
        recipient_name="Test",
        communication_channel="Email",
        generated_message_draft="Short",
        user_approval_granted=False
    )
    is_valid = await tool.validate_message(comm)
    assert is_valid is False

@pytest.mark.asyncio
async def test_risk_tool_high_risk(disruption_context):
    tool = RiskAssessmentTool()
    disruption_context.incident_type = "Medical Emergency"
    weather = {"weather": [{"main": "snow"}], "main": {"temp": -5.0, "humidity": 80}}
    score, explanation = await tool.calculate_risk_score(
        disruption_context,
        has_calendar_conflicts=True,
        weather_conditions=weather,
        travel_delay_minutes=150
    )
    assert score >= 50.0
    assert "Medical Emergency" in explanation
