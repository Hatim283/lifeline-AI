import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

os.environ["GEMINI_API_KEY"] = "test"
os.environ["OPENWEATHER_API_KEY"] = "test"
os.environ["GOOGLE_MAPS_API_KEY"] = "test"

from schema import (
    AgentState,
    UserPreferences,
    DisruptionContext,
    LogisticalAlternative,
    AutomatedCommunication
)
from agent_graph import LifelineAgentGraph

@pytest.fixture
def empty_state():
    prefs = UserPreferences(
        home_currency="USD",
        default_emergency_contacts=[{"name": "Alice", "phone": "123", "relation": "Friend"}],
        base_location="NYC",
        preferred_language="en",
        timezone="America/New_York",
        preferred_transport_modes=["Taxi"],
        notification_channels=["Email"]
    )
    return AgentState(
        messages=[],
        active_disruptions=[],
        logistical_alternatives=[],
        validation_flags={},
        active_graph_node_tracking_steps=[],
        user_preferences=prefs,
        current_calendar=[],
        pending_communications=[],
        current_session_id="session123",
        workflow_status="idle",
        last_updated=datetime.now(timezone.utc)
    )

@pytest.mark.asyncio
@patch("agent_graph.GeminiReasoningTool")
@patch("agent_graph.WeatherTool")
@patch("agent_graph.MapsTool")
@patch("agent_graph.CalendarTool")
@patch("agent_graph.CommunicationTool")
@patch("agent_graph.RiskAssessmentTool")
async def test_agent_graph_full_run(
    mock_risk, mock_comm, mock_cal, mock_maps, mock_weather, mock_reasoning, empty_state
):
    reasoning_instance = mock_reasoning.return_value
    reasoning_instance.summarize_disruption = AsyncMock(return_value=DisruptionContext(
        incident_type="Flight Delay",
        local_timestamp=datetime.now(timezone.utc),
        latitude=10.0,
        longitude=20.0,
        raw_user_input_string="delayed"
    ))
    
    # Mock dynamic routing decisions
    reasoning_instance.decide_next_step = AsyncMock(side_effect=[
        "WEATHER", "MAPS", "CALENDAR", "PLANNER", "COMMUNICATION", "FINISH"
    ])
    
    alt = LogisticalAlternative(
        transport_or_venue_mode="Train",
        provider_name="Amtrak",
        confidence_score=0.9,
        estimated_eta=datetime.now(timezone.utc),
        additional_cost_normalized=50.0,
        justification_text_block="Good"
    )
    reasoning_instance.generate_alternative_plan = AsyncMock(return_value=[alt])
    
    comm_draft = AutomatedCommunication(
        recipient_name="Alice",
        communication_channel="Email",
        generated_message_draft="Draft message",
        user_approval_granted=False
    )
    reasoning_instance.draft_communication = AsyncMock(return_value=comm_draft)
    
    weather_instance = mock_weather.return_value
    weather_instance.get_weather = AsyncMock(return_value={"weather": [{"main": "Clear"}]})
    
    maps_instance = mock_maps.return_value
    maps_instance.search_nearby_services = AsyncMock(return_value=[])
    
    cal_instance = mock_cal.return_value
    cal_instance.find_conflicts = AsyncMock(return_value=[])
    
    risk_instance = mock_risk.return_value
    risk_instance.calculate_risk_score = AsyncMock(return_value=(20.0, "Low risk"))
    
    comm_instance = mock_comm.return_value
    async def mock_queue(comm, st):
        st.pending_communications.append(comm)
        return st
    comm_instance.queue_message = AsyncMock(side_effect=mock_queue)

    graph = LifelineAgentGraph()
    final_state = await graph.run(empty_state, "My flight is delayed")
    
    assert final_state.workflow_status == "awaiting_user"
    assert len(final_state.active_disruptions) == 1
    assert len(final_state.logistical_alternatives) == 1
    assert len(final_state.pending_communications) == 1
    assert final_state.validation_flags.get("weather_data_fetched") is True
    assert final_state.risk_score == 20.0

@pytest.mark.asyncio
@patch("agent_graph.GeminiReasoningTool")
async def test_agent_graph_assessor_error(mock_reasoning, empty_state):
    reasoning_instance = mock_reasoning.return_value
    reasoning_instance.summarize_disruption = AsyncMock(side_effect=Exception("API Down"))
    
    graph = LifelineAgentGraph()
    final_state = await graph.run(empty_state, "My flight is delayed")
    
    assert final_state.workflow_status == "error"
    assert len(final_state.active_disruptions) == 0
