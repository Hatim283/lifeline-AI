from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import datetime, timezone
from typing import Any

class UserPreferences(BaseModel):
    """Stores the user's personal preferences for the concierge service."""
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True
    )
    
    home_currency: str = Field(default="AED", description="The user's home currency")
    default_emergency_contacts: List[Dict[str, str]] = Field(
        default_factory=list, 
        description="List of default emergency contacts"
    )
    base_location: str = Field(default="Dubai", description="The base location of the user")
    preferred_language: str = Field(default="en", description="User's preferred language")
    timezone: str = Field(default="Asia/Dubai", description="User's local timezone")
    preferred_transport_modes: List[str] = Field(
        default_factory=list,
        description="List of user's preferred modes of transportation"
    )
    notification_channels: List[Literal["WhatsApp", "Email"]] = Field(
        default_factory=list,
        description="User's preferred channels for notifications"
    )

class CalendarBlock(BaseModel):
    """Represents a scheduled event in the user's calendar."""
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True
    )

    event_name: str = Field(..., description="The name of the event")
    location: str = Field(..., description="The location of the event")
    start_time: datetime = Field(..., description="Start time of the event")
    end_time: datetime = Field(..., description="End time of the event")
    is_critical: bool = Field(..., description="Flag indicating if the event is critical")

    @model_validator(mode="after")
    def check_time_order(self) -> 'CalendarBlock':
        """Validates that the end time of an event occurs after its start time."""
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        return self

class DisruptionContext(BaseModel):
    """Contextual information regarding an active disruption."""
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True
    )

    incident_type: Literal[
        "Vehicle Breakdown", 
        "Flight Delay", 
        "Weather Emergency", 
        "Medical Emergency", 
        "Traffic Congestion", 
        "Other"
    ] = Field(..., description="Type of incident affecting the user's schedule")
    local_timestamp: datetime = Field(..., description="Local timestamp of the disruption")
    latitude: Optional[float] = Field(
        default=None, 
        ge=-90.0, 
        le=90.0, 
        description="Geographic latitude of the disruption"
    )
    longitude: Optional[float] = Field(
        default=None, 
        ge=-180.0, 
        le=180.0, 
        description="Geographic longitude of the disruption"
    )
    raw_user_input_string: str = Field(..., description="Raw string input provided by the user")

class LogisticalAlternative(BaseModel):
    """A proposed alternative for logistics during a disruption."""
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True
    )

    transport_or_venue_mode: str = Field(..., description="Mode of transport or venue")
    estimated_eta: datetime = Field(..., description="Estimated time of arrival or availability")
    additional_cost_normalized: float = Field(
        ..., 
        ge=0.0,
        description="Additional cost normalized to base currency"
    )
    justification_text_block: str = Field(
        ..., 
        description="Detailed justification for this alternative"
    )
    confidence_score: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence score for this alternative (0-1)"
    )
    reason: str = Field(
        default="",
        description="Specific reason for this recommendation"
    )
    missing_information: str = Field(
        default="",
        description="Any missing information that could affect this alternative"
    )
    estimated_reliability: str = Field(
        default="High",
        description="Estimated reliability of this option (e.g., High, Medium, Low)"
    )
    provider_name: Optional[str] = Field(
        default=None, 
        description="Name of the service provider"
    )
    booking_url: Optional[str] = Field(
        default=None, 
        description="URL for booking the alternative if available"
    )

class AutomatedCommunication(BaseModel):
    """Draft or sent automated communication to stakeholders."""
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True
    )

    recipient_name: str = Field(..., min_length=1, description="Name of the recipient")
    communication_channel: Literal["WhatsApp", "Email"] = Field(
        ..., 
        description="Channel for communication"
    )
    generated_message_draft: str = Field(
        ..., 
        min_length=1, 
        description="The drafted message to be sent"
    )
    user_approval_granted: bool = Field(
        ..., 
        description="Explicit flag indicating if user approved the message"
    )

class ChatMessage(BaseModel):
    """A single message within the conversational state."""
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True
    )

    role: Literal["system", "user", "assistant", "tool"] = Field(..., description="Role of the message sender")
    content: str = Field(..., min_length=1, description="Content of the message, cannot be empty")
    timestamp: datetime = Field(..., description="Timestamp when the message was created")

class AgentState(BaseModel):
    """The complete state of the autonomous concierge agent."""
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True
    )

    messages: List[ChatMessage] = Field(
        default_factory=list, 
        description="Conversational message logs"
    )
    active_disruptions: List[DisruptionContext] = Field(
        default_factory=list, 
        description="Current active disruption profiles"
    )
    logistical_alternatives: List[LogisticalAlternative] = Field(
        default_factory=list, 
        description="List of proposed logistical alternatives"
    )
    validation_flags: Dict[str, bool] = Field(
        default_factory=dict, 
        description="Validation flags for current state"
    )
    risk_score: Optional[float] = Field(
        default=None,
        description="Computed risk score (0-100)"
    )
    risk_explanation: Optional[str] = Field(
        default=None,
        description="Explanation of the calculated risk score"
    )
    workflow_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary runtime metadata"
    )
    active_graph_node_tracking_steps: List[str] = Field(
        default_factory=list, 
        description="Active graph node tracking steps"
    )
    user_preferences: UserPreferences = Field(
        ..., 
        description="User's concierge preferences"
    )
    current_calendar: List[CalendarBlock] = Field(
        default_factory=list,
        description="User's current schedule of events"
    )
    pending_communications: List[AutomatedCommunication] = Field(
        default_factory=list,
        description="Communications queued for approval or dispatch"
    )
    current_session_id: str = Field(
        ..., 
        description="Unique identifier for the current active session"
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of the last state update"
    )
    workflow_status: Literal[
        "idle", 
        "planning", 
        "executing", 
        "awaiting_user", 
        "completed", 
        "error"
    ] = Field(..., description="Current status of the agent's workflow")
