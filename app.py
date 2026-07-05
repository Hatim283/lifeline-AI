import logging
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import pandas as pd
import sqlite3
import folium
from streamlit_folium import st_folium
import streamlit as st
import os
import json
from dotenv import load_dotenv

load_dotenv()

from schema import (
    AgentState, 
    UserPreferences, 
    CalendarBlock, 
    ChatMessage, 
    DisruptionContext, 
    LogisticalAlternative, 
    AutomatedCommunication
)
from agent_graph import LifelineAgentGraph
from mcp_tools import generate_utc_timestamp

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def init_agent_state() -> AgentState:
    """Initializes and returns a fresh AgentState instance with default preferences."""
    prefs = UserPreferences(
        home_currency="AED",
        default_emergency_contacts=[{"name": "Manager", "phone": "+971501234567", "relation": "Work"}],
        base_location="Dubai",
        preferred_language="en",
        timezone="Asia/Dubai",
        preferred_transport_modes=["Taxi", "Metro", "Flight"],
        notification_channels=["Email", "WhatsApp"]
    )
    
    return AgentState(
        messages=[],
        active_disruptions=[],
        logistical_alternatives=[],
        validation_flags={},
        risk_explanation=None,
        workflow_metadata={},
        active_graph_node_tracking_steps=[],
        user_preferences=prefs,
        current_calendar=[],
        pending_communications=[],
        current_session_id=str(uuid.uuid4()),
        workflow_status="idle",
        last_updated=generate_utc_timestamp()
    )

def format_local_time(dt_obj: datetime) -> str:
    """Formats a datetime object to a local string representation."""
    return dt_obj.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def format_time_only(dt_obj: datetime) -> str:
    """Formats a datetime object to output just the time (HH:MM)."""
    return dt_obj.astimezone().strftime("%H:%M")

def append_log(message: str, step: str = "System", status: str = "INFO") -> None:
    """Appends a log message to the Streamlit session state and standard logger."""
    timestamp = format_local_time(generate_utc_timestamp())
    st.session_state.agent_logs.append({
        "timestamp": timestamp,
        "step": step,
        "status": status,
        "message": message
    })
    logger.info(message)

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
DB_PATH = "lifeline.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS sessions
                        (session_id TEXT PRIMARY KEY, data TEXT)''')

init_db()

def save_state(state: AgentState) -> None:
    """Persists AgentState to SQLite."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT OR REPLACE INTO sessions (session_id, data) VALUES (?, ?)",
                         (state.current_session_id, state.model_dump_json()))
        logger.info(f"Session {state.current_session_id} saved to DB")
    except Exception as e:
        logger.error(f"Failed to save session state: {e}")

def load_state(session_id: str) -> Optional[AgentState]:
    """Loads AgentState from SQLite."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("SELECT data FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                return AgentState.model_validate_json(row[0])
    except Exception as e:
        logger.error(f"Failed to load session state {session_id}: {e}")
    return None

# ---------------------------------------------------------------------------
# Demo Data Generator
# ---------------------------------------------------------------------------
def generate_demo_state(scenario: str) -> AgentState:
    """Generates a mock AgentState for demonstration purposes based on the given scenario."""
    base_state = init_agent_state()
    now = generate_utc_timestamp()
    
    if scenario == "Flight Cancelled":
        disruption = DisruptionContext(
            incident_type="Flight Delay",
            local_timestamp=now,
            latitude=25.2532,
            longitude=55.3657,
            raw_user_input_string="My flight EK001 from Dubai to London just got cancelled."
        )
        base_state.active_disruptions = [disruption]
        
        base_state.messages = [
            ChatMessage(role="user", content="My flight EK001 from Dubai to London just got cancelled.", timestamp=now - timedelta(minutes=5)),
            ChatMessage(role="assistant", content="I analyzed your disruption. Weather conditions have been checked. Three recovery options were generated. One communication draft is waiting for your approval.", timestamp=now - timedelta(minutes=4))
        ]
        
        base_state.validation_flags = {
            "weather_data_fetched": True,
            "nearby_hospitals_found": False,
            "calendar_conflicts_detected": True,
            "high_risk": True
        }
        base_state.risk_explanation = "Severe travel delay of 450 mins. Schedule conflicts detected."
        
        base_state.current_calendar = [
            CalendarBlock(event_name="Team Sync", location="Zoom", start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1), is_critical=False),
            CalendarBlock(event_name="Board Meeting", location="London Office", start_time=now + timedelta(hours=4), end_time=now + timedelta(hours=6), is_critical=True)
        ]
        
        base_state.logistical_alternatives = [
            LogisticalAlternative(
                transport_or_venue_mode="Emirates Next Available Flight",
                estimated_eta=now + timedelta(hours=7),
                additional_cost_normalized=0.0,
                justification_text_block="Rebooking on the same airline minimizes out-of-pocket costs and leverages your frequent flyer status.",
                confidence_score=0.95,
                provider_name="Emirates",
                booking_url="https://emirates.com/manage"
            ),
            LogisticalAlternative(
                transport_or_venue_mode="British Airways Direct Flight",
                estimated_eta=now + timedelta(hours=8),
                additional_cost_normalized=3500.0,
                justification_text_block="Fastest alternative option, though requires a new ticket purchase.",
                confidence_score=0.85,
                provider_name="British Airways",
                booking_url="https://ba.com/book"
            ),
            LogisticalAlternative(
                transport_or_venue_mode="Qatar Airways via Doha",
                estimated_eta=now + timedelta(hours=11),
                additional_cost_normalized=2200.0,
                justification_text_block="Cost-effective alternative but involves a layover which adds to travel time.",
                confidence_score=0.75,
                provider_name="Qatar Airways",
                booking_url="https://qatarairways.com/book"
            )
        ]
        
        base_state.pending_communications = [
            AutomatedCommunication(
                recipient_name="Manager",
                communication_channel="Email",
                generated_message_draft="Hi Manager,\n\nI wanted to alert you that my flight (EK001) to London has been cancelled. I am currently reviewing alternative flights and expect to be delayed. Unfortunately, I may miss or be late to the Board Meeting at 14:00. I will keep you updated once I have a confirmed rebooking.\n\nBest regards.",
                user_approval_granted=False
            )
        ]
        
        base_state.workflow_status = "awaiting_user"

    elif scenario == "Medical Emergency":
        disruption = DisruptionContext(
            incident_type="Medical Emergency",
            local_timestamp=now,
            latitude=25.2048,
            longitude=55.2708,
            raw_user_input_string="I'm having severe chest pains at the hotel."
        )
        base_state.active_disruptions = [disruption]
        
        base_state.messages = [
            ChatMessage(role="user", content="I'm having severe chest pains at the hotel.", timestamp=now - timedelta(minutes=2)),
            ChatMessage(role="assistant", content="I have immediately located the nearest hospitals and prioritized a rapid response plan. A notification to your emergency contact is drafted.", timestamp=now - timedelta(minutes=1))
        ]
        
        base_state.validation_flags = {
            "weather_data_fetched": True,
            "nearby_hospitals_found": True,
            "calendar_conflicts_detected": True,
            "high_risk": True
        }
        base_state.risk_explanation = "High risk incident type: Medical Emergency."
        
        base_state.current_calendar = [
            CalendarBlock(event_name="Client Dinner", location="Downtown", start_time=now + timedelta(hours=1), end_time=now + timedelta(hours=3), is_critical=True)
        ]
        
        base_state.logistical_alternatives = [
            LogisticalAlternative(
                transport_or_venue_mode="Ambulance Dispatch",
                estimated_eta=now + timedelta(minutes=8),
                additional_cost_normalized=0.0,
                justification_text_block="Immediate medical dispatch is required for severe symptoms. Nearest facility is Mediclinic City Hospital.",
                confidence_score=0.99,
                provider_name="Dubai Ambulance Services",
                booking_url=None
            ),
            LogisticalAlternative(
                transport_or_venue_mode="Emergency Taxi",
                estimated_eta=now + timedelta(minutes=5),
                additional_cost_normalized=50.0,
                justification_text_block="A taxi is slightly faster to arrive, but lacks medical equipment en route.",
                confidence_score=0.60,
                provider_name="Uber",
                booking_url="https://uber.com"
            )
        ]
        
        base_state.pending_communications = [
            AutomatedCommunication(
                recipient_name="Emergency Contact (Spouse)",
                communication_channel="WhatsApp",
                generated_message_draft="URGENT: I am experiencing a medical emergency (chest pains) at the hotel in Dubai. I am seeking immediate medical attention. Will update you ASAP.",
                user_approval_granted=False
            )
        ]
        
        base_state.workflow_status = "awaiting_user"

    elif scenario == "Vehicle Breakdown":
        disruption = DisruptionContext(
            incident_type="Vehicle Breakdown",
            local_timestamp=now,
            latitude=25.2048,
            longitude=55.2708,
            raw_user_input_string="My car broke down on Sheikh Zayed Road."
        )
        base_state.active_disruptions = [disruption]
        
        base_state.messages = [
            ChatMessage(role="user", content="My car broke down on Sheikh Zayed Road.", timestamp=now - timedelta(minutes=3)),
            ChatMessage(role="assistant", content="I have located your position. Towing services are available. A message to your next meeting has been drafted.", timestamp=now - timedelta(minutes=1))
        ]
        
        base_state.validation_flags = {
            "weather_data_fetched": True,
            "nearby_hospitals_found": False,
            "calendar_conflicts_detected": True,
            "high_risk": True
        }
        base_state.risk_explanation = "Stranded on a major highway. High risk of accident."
        
        base_state.current_calendar = [
            CalendarBlock(event_name="Investor Pitch", location="DIFC", start_time=now + timedelta(minutes=30), end_time=now + timedelta(hours=2), is_critical=True)
        ]
        
        base_state.logistical_alternatives = [
            LogisticalAlternative(
                transport_or_venue_mode="Premium Towing & Replacement Car",
                estimated_eta=now + timedelta(minutes=15),
                additional_cost_normalized=250.0,
                justification_text_block="Fastest response time on this highway. Includes a replacement vehicle to get you to your pitch.",
                confidence_score=0.90,
                provider_name="AAA Roadside",
                booking_url="https://aaa.com/request"
            )
        ]
        
        base_state.pending_communications = [
            AutomatedCommunication(
                recipient_name="Investors",
                communication_channel="Email",
                generated_message_draft="I am currently experiencing a vehicle breakdown on the highway and will be approximately 15 minutes late to our pitch. I am in a replacement vehicle now.",
                user_approval_granted=False
            )
        ]
        
        base_state.workflow_status = "awaiting_user"

    else:
        disruption = DisruptionContext(
            incident_type="Other",
            local_timestamp=now,
            latitude=25.2048,
            longitude=55.2708,
            raw_user_input_string=f"Experiencing {scenario}"
        )
        base_state.active_disruptions = [disruption]
        
        base_state.messages = [
            ChatMessage(role="user", content=f"Experiencing {scenario}", timestamp=now - timedelta(minutes=2)),
            ChatMessage(role="assistant", content=f"I have analyzed the {scenario} situation. One alternative generated.", timestamp=now - timedelta(minutes=1))
        ]
        
        base_state.validation_flags = {
            "weather_data_fetched": True,
            "nearby_hospitals_found": False,
            "calendar_conflicts_detected": False,
            "high_risk": False
        }
        base_state.risk_explanation = f"Moderate risk due to {scenario}."
        
        base_state.current_calendar = []
        
        base_state.logistical_alternatives = [
            LogisticalAlternative(
                transport_or_venue_mode="Wait it out",
                estimated_eta=now + timedelta(hours=1),
                additional_cost_normalized=0.0,
                justification_text_block="The safest option right now is to wait for conditions to improve.",
                confidence_score=0.75,
                provider_name="Self",
                booking_url=None
            )
        ]
        
        base_state.pending_communications = [
            AutomatedCommunication(
                recipient_name="Team",
                communication_channel="Email",
                generated_message_draft=f"I am currently delayed due to {scenario}. Will update when I am moving again.",
                user_approval_granted=False
            )
        ]
        
        base_state.workflow_status = "awaiting_user"

    return base_state

# ---------------------------------------------------------------------------
# Core Execution
# ---------------------------------------------------------------------------
def handle_user_input(user_input: str) -> None:
    """Processes user input, updates agent state, and triggers the async graph."""
    state: AgentState = st.session_state.agent_state
    
    new_msg = ChatMessage(role="user", content=user_input, timestamp=generate_utc_timestamp())
    state.messages.append(new_msg)
    append_log(f"Received user input: '{user_input[:30]}...'", step="User Input", status="INFO")
    
    with st.spinner("Lifeline AI is analyzing the situation..."):
        if st.session_state.get("demo_mode_enabled", False):
            import time
            time.sleep(1.5)
            demo_scenario = st.session_state.get("demo_scenario", "Flight Cancelled")
            new_state = generate_demo_state(demo_scenario)
            new_state.current_session_id = state.current_session_id
            st.session_state.agent_state = new_state
            save_state(new_state)
            
            append_log(f"Agent workflow completed via Demo Mode. Status: {new_state.workflow_status}", step="AgentGraph", status="SUCCESS")
        else:
            graph: LifelineAgentGraph = st.session_state.agent_graph
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                new_state = loop.run_until_complete(graph.run(state, user_input))
                loop.close()
                
                st.session_state.agent_state = new_state
                save_state(new_state)
                
                if new_state.workflow_status == "error":
                    summary = "I encountered a critical error while trying to analyze your situation. Please check the Developer Logs for more details."
                else:
                    summary = "I have analyzed your situation. "
                    if new_state.logistical_alternatives:
                        summary += f"Generated {len(new_state.logistical_alternatives)} recovery options. "
                    if new_state.pending_communications:
                        summary += f"There is a communication draft waiting for your approval."
                    
                reply_msg = ChatMessage(role="assistant", content=summary.strip(), timestamp=generate_utc_timestamp())
                st.session_state.agent_state.messages.append(reply_msg)
                save_state(st.session_state.agent_state)
                append_log(f"Agent workflow completed. Status: {new_state.workflow_status}", step="AgentGraph", status="SUCCESS")
                
            except Exception as e:
                st.error(f"Critical Execution Error: {e}")
                append_log(f"Execution failed: {str(e)}", step="AgentGraph", status="ERROR")
            
    st.rerun()

def handle_quick_demo() -> None:
    """Quickly injects a demo scenario into the state without running the graph."""
    st.session_state.demo_mode_enabled = True
    demo_scenario = st.session_state.get("demo_scenario", "Flight Cancelled")
    new_state = generate_demo_state(demo_scenario)
    st.session_state.agent_state = new_state
    save_state(new_state)
    append_log(f"Loaded demo scenario: {demo_scenario}", step="Demo System", status="INFO")
    st.rerun()

# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------
def render_sidebar() -> str:
    """Renders the standard sidebar navigation and configuration panel.
    
    Returns:
        The selected navigation view string (Dashboard or About).
    """
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Google_%22G%22_logo.svg/120px-Google_%22G%22_logo.svg.png", width=40)
        st.markdown("### Lifeline AI Concierge")
        st.caption("Google × Kaggle AI Agents Capstone")
        st.divider()

        nav_choice = st.radio("Navigation", ["Dashboard", "About Project"], index=0)
        st.divider()

        st.markdown("## ⚙️ Config & Features")
        
        st.markdown("### Demo Mode (Hackathon)")
        demo_mode = st.checkbox("☑ Enable Demo Mode", value=st.session_state.get("demo_mode_enabled", False))
        st.session_state.demo_mode_enabled = demo_mode
        
        if demo_mode:
            st.info("Demo mode bypasses live APIs for fast, deterministic presentations.")
            scenarios = ["Flight Cancelled", "Flight Delayed", "Vehicle Breakdown", "Heavy Traffic", "Weather Emergency", "Medical Emergency"]
            demo_scenario = st.selectbox("Select Demo Scenario", options=scenarios)
            st.session_state.demo_scenario = demo_scenario
            
            if st.button("▶ Run Full Demo", use_container_width=True, type="primary"):
                handle_quick_demo()
                
        st.divider()
        st.markdown("### Session Management")
        restore_id = st.text_input("Restore Session ID:", placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000")
        if st.button("Restore Session", use_container_width=True):
            if restore_id.strip():
                restored = load_state(restore_id.strip())
                if restored:
                    st.session_state.agent_state = restored
                    st.success(f"Restored session {restore_id}")
                else:
                    st.error("Session not found.")
        
        st.divider()
        
        with st.expander("Enabled APIs"):
            st.write("✅ Google Gemini API")
            st.write("✅ OpenWeather API")
            st.write("✅ Google Maps API")
            st.write("✅ Google Calendar API")
            
        st.divider()
        st.markdown("### UI Theme")
        
        is_dark_mode = True
        try:
            import os
            if os.path.exists(".streamlit/config.toml"):
                with open(".streamlit/config.toml", "r") as f:
                    content = f.read()
                    if 'base="light"' in content or "base = 'light'" in content or 'base = "light"' in content:
                        is_dark_mode = False
        except Exception:
            pass

        dark_mode_override = st.checkbox("Dark Mode Override", value=is_dark_mode)
        
        if dark_mode_override != is_dark_mode:
            try:
                import os
                os.makedirs(".streamlit", exist_ok=True)
                with open(".streamlit/config.toml", "w") as f:
                    theme_base = "dark" if dark_mode_override else "light"
                    f.write(f'[theme]\nbase="{theme_base}"\n')
                st.rerun()
            except Exception:
                pass
                
        st.divider()
        st.warning(
            "**DISCLAIMER**\n\n"
            "This project is a demonstration created for the Google × Kaggle AI Agents Intensive Capstone. "
            "This application is not intended for real emergency response. "
            "Do not rely on generated recommendations for life-critical situations. "
            "Always verify information before acting."
        )
        return nav_choice

def render_hero(state: AgentState) -> None:
    """Renders the hero header and session metadata."""
    st.warning("⚠️ **NOTICE**: This project is a demonstration created for educational purposes. It is not intended for real emergency response or life-critical situations. Always verify information.")
    
    st.title("🆘 Lifeline AI")
    st.markdown("#### Autonomous Crisis & Disruptive Logistics Concierge")
    st.caption("*AI-powered disruption detection, intelligent recovery planning, and automated stakeholder communication.*")
    
    col1, col2, _ = st.columns([1, 1, 3])
    with col1:
        st.info(f"**Session ID:** `{state.current_session_id[:8]}`")
    with col2:
        status = state.workflow_status.upper()
        if status in ["COMPLETED"]:
            st.success(f"**Workflow Status:** {status}")
        elif status in ["ERROR"]:
            st.error(f"**Workflow Status:** {status}")
        elif status in ["AWAITING_USER", "EXECUTING", "PLANNING"]:
            st.warning(f"**Workflow Status:** {status}")
        else:
            st.info(f"**Workflow Status:** {status}")
    st.divider()

def render_kpis(state: AgentState) -> None:
    """Renders the top key performance indicators metric row."""
    kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)
    
    active_incidents = len(state.active_disruptions)
    risk_level = "High" if state.validation_flags.get("high_risk") else "Low"
    alt_plans = len(state.logistical_alternatives)
    pending_msgs = sum(1 for c in state.pending_communications if not c.user_approval_granted)
    
    est_delay = "N/A"
    added_cost = f"0 {state.user_preferences.home_currency}"
    if alt_plans > 0:
        best_alt = state.logistical_alternatives[0]
        if state.active_disruptions:
            delay = best_alt.estimated_eta - state.active_disruptions[-1].local_timestamp
            hours, remainder = divmod(delay.total_seconds(), 3600)
            minutes = remainder // 60
            est_delay = f"{int(hours)}h {int(minutes)}m"
        added_cost = f"{best_alt.additional_cost_normalized:,.0f} {state.user_preferences.home_currency}"

    with kpi_col1:
        st.metric("🚨 Active Incidents", active_incidents)
    with kpi_col2:
        st.metric("⚠️ Risk Level", risk_level)
    with kpi_col3:
        st.metric("🛣️ Alternative Plans", alt_plans)
    with kpi_col4:
        st.metric("⏳ Est. Delay", est_delay)
    with kpi_col5:
        st.metric("💸 Added Cost", added_cost)
        
    st.divider()

def render_left_panel(state: AgentState) -> None:
    """Renders the chat interface and interaction panel."""
    st.subheader("💬 Emergency Comms")
    chat_container = st.container(height=520, border=True)
    
    with chat_container:
        if not state.messages:
            st.info("How can the Lifeline Concierge assist you today?")
            
        for msg in state.messages:
            avatar = "🆘" if msg.role == "user" else "🤖"
            with st.chat_message(msg.role, avatar=avatar):
                st.write(msg.content)
                st.caption(format_local_time(msg.timestamp))

    with st.form("chat_form", clear_on_submit=True):
        user_input = st.text_input("Describe the emergency or disruption:", placeholder="e.g., My flight to London just got cancelled...")
        submitted = st.form_submit_button("Submit Emergency", use_container_width=True)
        if submitted and user_input.strip():
            handle_user_input(user_input.strip())

def render_center_panel(state: AgentState) -> None:
    """Renders maps, risk factors, and logistical alternatives."""
    st.subheader("🗺️ Operational Dashboard")
    
    if not state.active_disruptions:
        st.info("No active disruptions detected. The dashboard is currently idle.")
        return
        
    current_disruption = state.active_disruptions[-1]
    
    col_weather, col_risk = st.columns(2)
    with col_weather:
        with st.container(border=True):
            st.markdown("##### 🌦️ Weather Status")
            if state.validation_flags.get("weather_service_unavailable"):
                st.warning("⚠ Weather service unavailable.")
            elif state.validation_flags.get("weather_data_fetched"):
                st.success("Real-time weather data retrieved successfully.")
            else:
                st.warning("Weather data is currently unavailable.")
            
    with col_risk:
        with st.container(border=True):
            st.markdown("##### ⚠️ Risk Assessment")
            if "high_risk" in state.validation_flags:
                risk_flag = state.validation_flags["high_risk"]
                if risk_flag:
                    st.error(f"🔴 **HIGH RISK** - {state.risk_explanation or 'No details available.'}")
                else:
                    st.success(f"🟢 **LOW RISK** - {state.risk_explanation or 'No details available.'}")
            else:
                st.info("Pending risk calculation engine...")
    
    with st.container(border=True):
        st.markdown("##### 📍 Geospatial Analysis")
        if state.validation_flags.get("maps_service_unavailable"):
            st.warning("⚠ Maps service unavailable.")
        elif current_disruption.latitude is not None and current_disruption.longitude is not None:
            m = folium.Map(location=[current_disruption.latitude, current_disruption.longitude], zoom_start=13)
            folium.Marker(
                [current_disruption.latitude, current_disruption.longitude],
                popup="Incident Location",
                icon=folium.Icon(color="red", icon="info-sign")
            ).add_to(m)
            
            st_folium(m, width="100%", height=400)
        else:
            st.info("🗺️ Waiting for location coordinates to display the map...")

    st.subheader("🛣️ Alternative Logistics")
    if state.logistical_alternatives:
        for i, alt in enumerate(state.logistical_alternatives):
            with st.container(border=True):
                col_title, col_badge = st.columns([3, 1])
                with col_title:
                    st.markdown(f"#### {alt.transport_or_venue_mode}")
                with col_badge:
                    if i == 0:
                        st.success("⭐ RECOMMENDED")
                    else:
                        st.info(f"Priority {i+1}")
                        
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Confidence", f"{alt.confidence_score * 100:.0f}%")
                with c2:
                    st.metric("ETA", format_local_time(alt.estimated_eta))
                with c3:
                    st.metric("Added Cost", f"{alt.additional_cost_normalized:,.0f}")
                    
                st.markdown(f"**Provider:** {alt.provider_name or 'N/A'}")
                st.markdown(f"> *{alt.justification_text_block}*")
                
                if alt.booking_url:
                    st.link_button("Initiate Booking", alt.booking_url, type="primary")
    else:
        st.info("No viable logistical alternatives have been generated yet.")

def render_right_panel(state: AgentState) -> None:
    """Renders schedule timeline and pending communications."""
    st.subheader("📅 Schedule & Comms")
    
    with st.container(border=True):
        st.markdown("##### ✉️ Pending Approvals")
        if state.pending_communications:
            for i, comm in enumerate(state.pending_communications):
                if not comm.user_approval_granted:
                    st.warning(f"**Recipient:** {comm.recipient_name} | **Channel:** {comm.communication_channel}")
                    st.info(comm.generated_message_draft)
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("Approve", key=f"approve_comm_{i}", type="primary", use_container_width=True):
                            comm.user_approval_granted = True
                            save_state(state)
                            append_log(f"User approved communication to {comm.recipient_name}.", step="User Action", status="SUCCESS")
                            st.rerun()
                    with c2:
                        st.button("Reject", key=f"reject_comm_{i}", use_container_width=True)
                    with c3:
                        st.button("Edit", key=f"edit_comm_{i}", use_container_width=True)
        else:
            st.write("No outbound messages pending approval.")

    with st.container(border=True):
        st.markdown("##### ⏱️ Calendar Timeline")
        if state.current_calendar:
            if state.validation_flags.get("calendar_service_unavailable"):
                st.warning("⚠ Calendar service unavailable.")
            elif state.validation_flags.get("calendar_conflicts_detected"):
                st.error("Urgent schedule conflicts detected due to the recent disruption.")
                
            for event in state.current_calendar:
                color = "red" if event.is_critical else "blue"
                icon = "🔴" if event.is_critical else "🔵"
                st.markdown(f"{icon} **:{color}[{event.event_name}]**")
                st.caption(f"{format_time_only(event.start_time)} - {format_time_only(event.end_time)} | 📍 {event.location}")
                st.divider()
        else:
            st.write("Your schedule is currently clear.")

    with st.expander("🤖 Reasoning Trace (Agent Thoughts)"):
        if state.active_graph_node_tracking_steps:
            for step in state.active_graph_node_tracking_steps:
                st.markdown(f"- {step}")
        else:
            st.write("No reasoning trace yet.")

    with st.expander("🛠️ Developer / Execution Logs"):
        logs = st.session_state.agent_logs[-20:]
        if logs:
            for log in reversed(logs):
                color = "green" if log["status"] == "SUCCESS" else "red" if log["status"] == "ERROR" else "blue"
                st.markdown(f"`{log['timestamp']}` | **:{color}[{log['step']}]** {log['message']}")
        else:
            st.write("System idle. No logs to display.")

def render_about_page() -> None:
    """Renders an informational About page for the project."""
    st.title("ℹ️ About Lifeline AI")
    st.markdown("""
    **Lifeline AI** is an Autonomous Crisis & Disruptive Logistics Concierge.
    
    Built as a demonstration project for the **Google × Kaggle AI Agents Intensive Capstone**, Lifeline AI showcases the power of multi-tool agentic orchestration leveraging the Gemini API.
    
    ### Architecture
    Lifeline uses a stateful agent graph that processes disruptions sequentially:
    1. **Assessor Node:** Understands and standardizes the incident via Gemini.
    2. **Resource Router:** Dynamically fetches context from Google Maps (services, geocoding), OpenWeather, and Calendar APIs.
    3. **Planner Node:** Synthesizes the constraints to formulate logical recovery alternatives.
    4. **Communication Node:** Drafts stakeholder alerts for pending human-in-the-loop approval.
    
    ### Disclaimers
    - **Educational Purpose:** This is a hackathon prototype, not a production-ready safety app.
    - **Liability:** Do not rely on generated recommendations for life-critical situations. Always verify information manually.
    - **Mocked Data:** "Demo Mode" uses predefined datasets and bypasses live APIs for presentation stability.
    """)

def render_footer() -> None:
    """Renders the standard footer note with disclaimers."""
    st.divider()
    st.caption("Powered by Google Gemini • Python 3.11 • Streamlit • Version 2.0.0-rc1 • © 2026 Lifeline AI")
    st.caption("*Demonstration project only. Not intended for real emergency response.*")

# ---------------------------------------------------------------------------
# Main Application Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Lifeline AI | Disruption Concierge", 
        layout="wide", 
        page_icon="🆘",
        initial_sidebar_state="expanded"
    )

    if "agent_state" not in st.session_state:
        st.session_state.agent_state = init_agent_state()
    if "agent_graph" not in st.session_state:
        st.session_state.agent_graph = LifelineAgentGraph()
    if "agent_logs" not in st.session_state:
        st.session_state.agent_logs = []
        append_log("Lifeline Concierge system initialized successfully.", step="System", status="SUCCESS")

    nav_choice = render_sidebar()

    if nav_choice == "Dashboard":
        current_state: AgentState = st.session_state.agent_state
        render_hero(current_state)
        
        if current_state.active_disruptions:
            render_kpis(current_state)

        left_col, center_col, right_col = st.columns([1.2, 2.0, 1.2], gap="large")
        
        with left_col:
            render_left_panel(current_state)
        with center_col:
            render_center_panel(current_state)
        with right_col:
            render_right_panel(current_state)
    else:
        render_about_page()
        
    render_footer()

if __name__ == "__main__":
    main()
