# Lifeline AI

Lifeline AI is an autonomous, multi-agent concierge designed to handle logistical disruptions. Built for the Google × Kaggle AI Agents Intensive Capstone, it uses Google's Gemini models to assess crises, orchestrate external API tools, evaluate risk, and draft stakeholder communications.

---

## Problem Statement

When unexpected logistical disruptions occur, individuals must manually navigate across various data sources to find alternatives, assess the impact on their schedule, and notify affected parties. This process is time-consuming, fragmented, and error-prone.

---

## Solution

Lifeline AI acts as an autonomous orchestrator. The agent ingests a natural language description of a disruption, determines which APIs to query for missing context, and formulates an end-to-end recovery plan. It identifies schedule conflicts, factors in environmental variables, and prepares communications for human review.

---

## Features

### Implemented Features
- ✅ Incident analysis
- ✅ Weather integration
- ✅ Google Maps integration
- ✅ Calendar conflict detection
- ✅ Risk assessment
- ✅ Communication drafting
- ✅ Streamlit dashboard
- ✅ Demo mode
- ✅ Local state persistence

### Future Enhancements
- ⬜ OAuth2 integration for authenticated Google Calendar modifications
- ⬜ Integration with flight status APIs
- ⬜ Multi-user session management

---

## Architecture

Lifeline AI uses a stateful, dynamic agent graph pattern. Rather than executing a linear script, the core agent uses a routing node to determine its next action based on current state and missing context.

```mermaid
graph TD
    Input([User Prompt]) --> Assessor[Assessor Node]
    Assessor --> Router{Dynamic Router}
    
    Router -->|Needs Weather| Weather[Weather Tool]
    Router -->|Needs Location| Maps[Maps Tool]
    Router -->|Needs Schedule| Calendar[Calendar Tool]
    
    Weather --> Router
    Maps --> Router
    Calendar --> Router
    
    Router -->|Context Complete| Planner[Planner Node]
    Planner --> Risk[Risk Engine]
    Risk --> Comms[Communication Node]
    
    Comms --> HITL{Human Approval}
    HITL -->|Approved| Dispatch[Dispatch Alerts]
    HITL -->|Rejected| Planner
```

### Components

- **Assessor Node:** Parses the initial prompt to classify the incident type and extract entities.
- **Dynamic Router:** Decides which tools need to be executed based on the `AgentState`.
- **Tools (Weather, Maps, Calendar):** Asynchronous API wrappers that retrieve environmental and scheduling context.
- **Planner Node:** Synthesizes the gathered context into actionable logistical alternatives.
- **Risk Engine:** Normalizes the disruption parameters into a quantitative risk score (0-100).
- **Communication Node:** Generates tailored messages for stakeholders.
- **Human-in-the-Loop (HITL):** Awaits user review via the Streamlit interface before finalizing actions.

---

## Technology Stack

| Component | Technology | Use Case |
| :--- | :--- | :--- |
| Core Language | Python 3.11+ | Primary application logic |
| LLM Reasoning | Google Gemini 1.5 Pro | Agent orchestration and text synthesis |
| Data Validation | Pydantic | State management and strict schema definition |
| Web Framework | Streamlit | Reactive frontend and state visualization |
| Asynchronous I/O | `asyncio`, `httpx` | Non-blocking API requests |
| External APIs | Google Maps, OpenWeather | Contextual data retrieval |

---

## Project Structure

```text
lifeline/
├── app.py                 # Streamlit UI and session management
├── agent_graph.py         # Agent orchestration and node execution
├── mcp_tools.py           # External tool integrations (Maps, Weather, Calendar)
├── schema.py              # Pydantic data models for state tracking
├── config.py              # Application configuration
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container configuration
├── .env.example           # Example environment variables
├── .lifeline_sessions/    # Locally persisted session JSON files
└── tests/                 # Unit and integration tests (pytest)
```

- `schema.py`: Pydantic models defining the `AgentState` and various data structures.
- `agent_graph.py`: The core state machine and reasoning loop.
- `mcp_tools.py`: Asynchronous clients for external integrations.
- `app.py`: Streamlit frontend that renders the agent's workflow.
- `tests/`: Asynchronous unit tests validating tools and graph logic.

---

## Security

Following Google Cloud and GitHub security best practices:
- **Never commit API keys:** Ensure you never place raw API keys into source control or inline terminal commands.
- **Rotate compromised keys:** If a key is accidentally committed, revoke and rotate it immediately via the respective provider dashboard.
- **Environment files:** Keep `.env` strictly local. Ensure it is listed in `.gitignore`.
- **Cloud Run Deployment:** Do not pass secrets directly via `--set-env-vars`. Use Google Cloud Secret Manager or an ignored `env.yaml` file for secure deployments.

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Hatim283/lifeline-AI.git
   cd lifeline-AI
   ```

2. **Initialize a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up configuration:**
   ```bash
   cp .env.example .env
   ```

---

## Environment Variables

Edit the `.env` file locally and populate it with the required keys:

- `GEMINI_API_KEY`: Required. Your Google Gemini API key for core reasoning. If using a Google Cloud Platform API key, ensure the **Generative Language API** is enabled. You can enable it in Google Cloud Shell by running: `gcloud services enable generativelanguage.googleapis.com`
- `OPENWEATHER_API_KEY`: Required. Used by the Weather Tool to fetch live meteorological data. Ensure the **Weather API** is enabled.
- `GOOGLE_MAPS_API_KEY`: Required. Used by the Maps Tool for geocoding and routing. Ensure the following APIs are enabled for this key:
  - Directions API
  - Geocoding API
  - Geolocation API
  - Places API (New)
  - Places API
  - Time Zone API
  - Routes API
- `GOOGLE_CALENDAR_CREDENTIALS`: Optional. Path to a GCP service account JSON file for calendar synchronization.

---

## Running the Application

### Local

Run the application directly using Streamlit:

```bash
streamlit run app.py
```

Navigate to `http://localhost:8501` in your browser.

### Docker

Build and run the container locally. Note that the container maps to port 8080 by default to align with Cloud Run conventions.

```bash
docker build -t lifeline-ai .
docker run -p 8080:8080 --env-file .env lifeline-ai
```

Navigate to `http://localhost:8080` in your browser.

### Google Cloud Run

For secure deployment to Google Cloud Run, avoid inline secrets. Instead, create an `env.yaml` file in the root directory (this file is ignored by Git).

Format your `env.yaml` like this:
```yaml
GEMINI_API_KEY: "your_gemini_key"
OPENWEATHER_API_KEY: "your_openweather_key"
GOOGLE_MAPS_API_KEY: "your_maps_key"
```

Deploy directly to Google Cloud Run using the `gcloud` CLI:

```bash
gcloud run deploy lifeline-ai \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --env-vars-file=env.yaml
```

Alternatively, use **Google Cloud Secret Manager** to natively inject secrets into the container environment.

---

## Demo Mode

If you do not have access to the required API keys, you can test the application logic using Demo Mode. Toggling "Enable Demo Mode" in the sidebar bypasses external API calls and injects deterministic mock data. This allows evaluation of the UI, agent state transitions, and generated communications for predefined scenarios (e.g., flight cancellation, medical emergency).

---

## Example Workflow

1. **Input:** The user submits: *"My flight EK001 from Dubai to London just got cancelled."*
2. **Assessment:** The agent classifies this as a `Flight Delay` and extracts the locations.
3. **Routing & Tool Execution:** The router queries the Weather Tool (detecting storms in Dubai) and the Calendar Tool (finding a scheduled meeting in London).
4. **Planning:** The planner generates alternative flight options that arrive before the meeting.
5. **Risk Assessment:** A risk score of `85` is generated due to the severe weather and critical meeting conflict.
6. **Communication:** An email draft is prepared to notify the meeting participants of the delay.
7. **Output:** The agent pauses and presents the proposed plan and draft message in the UI for human approval.

---

## Screenshots

![Demo Mode Screenshot](docs/demo_screenshot.png)

---

## Testing

The project uses `pytest` and `pytest-asyncio` for test execution.

To run the test suite:

```bash
pytest tests/ -v
```

---

## Known Limitations

- **Prototype:** This is a hackathon prototype built for an educational capstone, not a production system.
- **External Dependencies:** The system relies on third-party APIs which may experience rate limits or failures.
- **Human Verification Required:** The system generates plans and communications based on LLM reasoning. A human must verify all actions before executing them.
- **Not for Emergencies:** This application is not intended for real-world emergency response or life-critical decision making.

---

## Future Work

- Implement OAuth2 flow for native Google Calendar integration.
- Expand test coverage for complex edge cases in the dynamic router.
- Implement retry mechanisms and exponential backoff for API calls.

---

## Contributing

Contributions are welcome. Please ensure that you:
1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Ensure all tests pass (`pytest`).
4. Submit a Pull Request detailing your changes.

---

## License

MIT

---

## Acknowledgements

- Google Gemini
- Streamlit
- Pydantic
- Google Maps
- OpenWeather
- Google × Kaggle AI Agents Intensive
