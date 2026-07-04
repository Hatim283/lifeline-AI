import pytest
from datetime import datetime, timezone
import datetime as dt
from pydantic import ValidationError

from schema import (
    UserPreferences,
    CalendarBlock,
    DisruptionContext,
    LogisticalAlternative,
    AutomatedCommunication,
    AgentState
)

def test_user_preferences_valid():
    prefs = UserPreferences(
        home_currency="USD",
        default_emergency_contacts=[{"name": "Alice", "phone": "123", "relation": "Friend"}],
        base_location="NYC",
        preferred_language="en",
        timezone="America/New_York",
        preferred_transport_modes=["Taxi"],
        notification_channels=["Email"]
    )
    assert prefs.home_currency == "USD"
    assert len(prefs.default_emergency_contacts) == 1
    assert prefs.base_location == "NYC"

def test_calendar_block_valid():
    start = datetime.now(timezone.utc)
    end = start + dt.timedelta(hours=1)
    block = CalendarBlock(
        event_name="Meeting",
        location="Office",
        start_time=start,
        end_time=end,
        is_critical=True
    )
    assert block.is_critical is True
    assert block.event_name == "Meeting"

def test_calendar_block_invalid_time():
    start = datetime.now(timezone.utc)
    end = start - dt.timedelta(hours=1)
    with pytest.raises(ValidationError):
        CalendarBlock(
            event_name="Meeting",
            location="Office",
            start_time="not-a-date",  # Invalid type for datetime
            end_time=end,
            is_critical=True
        )

def test_disruption_context_valid():
    ctx = DisruptionContext(
        incident_type="Flight Delay",
        local_timestamp=datetime.now(timezone.utc),
        latitude=40.7128,
        longitude=-74.0060,
        raw_user_input_string="cancelled flight"
    )
    assert ctx.incident_type == "Flight Delay"
    assert ctx.latitude == 40.7128

def test_disruption_context_invalid_coordinates():
    with pytest.raises(ValidationError):
        DisruptionContext(
            incident_type="Flight Delay",
            local_timestamp=datetime.now(timezone.utc),
            latitude=95.0,  # Invalid latitude > 90
            longitude=-74.0060,
            raw_user_input_string="cancelled flight"
        )

def test_logistical_alternative_valid():
    alt = LogisticalAlternative(
        transport_or_venue_mode="Flight",
        provider_name="Airline",
        confidence_score=0.95,
        estimated_eta=datetime.now(timezone.utc),
        additional_cost_normalized=150.0,
        justification_text_block="Best option"
    )
    assert alt.confidence_score == 0.95
    assert alt.transport_or_venue_mode == "Flight"

def test_logistical_alternative_invalid_confidence():
    with pytest.raises(ValidationError):
        LogisticalAlternative(
            transport_or_venue_mode="Flight",
            provider_name="Airline",
            confidence_score=1.5,  # Invalid: > 1.0
            estimated_eta=datetime.now(timezone.utc),
            additional_cost_normalized=150.0,
            justification_text_block="Best option"
        )

def test_automated_communication_valid():
    comm = AutomatedCommunication(
        recipient_name="Boss",
        communication_channel="Email",
        generated_message_draft="I will be late",
        user_approval_granted=False
    )
    assert comm.recipient_name == "Boss"
    
def test_automated_communication_invalid_channel():
    with pytest.raises(ValidationError):
        AutomatedCommunication(
            recipient_name="Boss",
            communication_channel="Pigeon",  # Not matching schema literal
            generated_message_draft=123,  # Invalid type
            user_approval_granted=False
        )

def test_agent_state_valid():
    prefs = UserPreferences(
        home_currency="USD",
        default_emergency_contacts=[],
        base_location="NYC",
        preferred_language="en",
        timezone="America/New_York",
        preferred_transport_modes=[],
        notification_channels=[]
    )
    state = AgentState(
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
    assert state.workflow_status == "idle"

def test_agent_state_invalid_status():
    prefs = UserPreferences(
        home_currency="USD",
        default_emergency_contacts=[],
        base_location="NYC",
        preferred_language="en",
        timezone="America/New_York",
        preferred_transport_modes=[],
        notification_channels=[]
    )
    with pytest.raises(ValidationError):
        AgentState(
            messages=[],
            active_disruptions=[],
            logistical_alternatives=[],
            validation_flags={},
            active_graph_node_tracking_steps=[],
            user_preferences=prefs,
            current_calendar=[],
            pending_communications=[],
            current_session_id="session123",
            workflow_status="non-existent-status",  # Invalid literal
            last_updated=datetime.now(timezone.utc)
        )
