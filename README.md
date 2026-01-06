# Travel Planner

## 📖 What is This Project?

**Travel Planner** is an AI-powered multi-agent system that helps users plan complete trips through natural conversation. Built with Google Gemini, it orchestrates specialized AI agents to gather preferences, research destinations, create detailed itineraries, and estimate budgets—all while keeping humans in the loop for key decisions.

The system features:
- 🤖 **Multi-agent architecture** with specialized agents for chat, research, itinerary planning, and budgeting
- 🔄 **Human-in-the-loop workflow** for selecting attractions and restaurants
- 💾 **Redis-backed session persistence** across page refreshes
- 🌐 **Real-time integration** with Google Maps, weather APIs, hotel booking, and flight search
- 🚀 **Production-ready deployment** with Docker + AWS App Runner support
- 🎯 **Critic-driven validation** to ensure plans meet user requirements and constraints

## 🏗️ Multi-Agent Architecture

```mermaid
graph TB
    User[👤 User via Streamlit UI]
    
    subgraph Frontend["🖥️ Frontend Layer"]
        Streamlit[Streamlit Chat Interface<br/>Port 8501]
        SessionURL[Session ID in URL<br/>Persists across refresh]
    end
    
    subgraph Backend["⚙️ Backend Layer - FastAPI Port 8000"]
        API[FastAPI REST API<br/>/sessions, /health]
        Runtime[TravelPlannerRuntime<br/>Session orchestration]
        Redis[(Redis<br/>Session Storage<br/>24hr TTL)]
    end
    
    subgraph Workflow["🔄 Multi-Agent Workflow Orchestrator"]
        State[TravelPlannerState<br/>Shared context & history]
        
        subgraph Agents["🤖 Specialized Agents"]
            Chat[ChatAgent<br/>Extract preferences<br/>Guide conversation]
            Research[ResearchAgent<br/>Parallel tool calls<br/>Data aggregation]
            Itinerary[ItineraryAgent<br/>Day-by-day scheduling<br/>Route optimization]
            Budget[BudgetAgent<br/>Cost estimation<br/>Constraint validation]
        end
        
        Critic[Critic Loop<br/>Requirement validation<br/>Auto-correction]
    end
    
    subgraph Tools["🔧 External Tool Layer"]
        Weather[Weather API<br/>Open-Meteo]
        Maps[Google Maps<br/>Places, Routes, Distance]
        Hotels[Hotel Search<br/>Amadeus API]
        Flights[Flight Search<br/>Amadeus API]
        CarFuel[Car & Fuel Prices<br/>Gemini-powered]
        StreetView[Street View<br/>Preview generation]
    end
    
    User -->|HTTP requests| Streamlit
    Streamlit -->|POST /sessions/id/turns| API
    API --> Runtime
    Runtime -->|Save/Load state| Redis
    Runtime --> State
    
    State -->|Phase: collecting| Chat
    Chat -->|Preferences complete| Research
    Research -->|Parallel calls| Tools
    Research -->|Returns data| State
    
    State -->|Interrupt: select_attractions| User
    State -->|Interrupt: select_restaurants| User
    User -->|Selection response| State
    
    State -->|Phase: planning| Itinerary
    Itinerary -->|Uses routes & street view| Maps
    Itinerary -->|Generate schedule| State
    
    State -->|Phase: budgeting| Budget
    Budget -->|Calculate costs| State
    
    State -->|Validate requirements| Critic
    Critic -->|Violations found| Itinerary
    Critic -->|Plan approved| State
    
    State -->|Updated state + interrupts| Runtime
    Runtime -->|JSON response| API
    API -->|Display results| Streamlit
    Streamlit -->|Render UI| User
    
    Weather -.->|Data| Research
    Maps -.->|Places, distances| Research
    Hotels -.->|Availability| Research
    Flights -.->|Flight options| Research
    CarFuel -.->|Pricing| Research
    StreetView -.->|Images| Itinerary
    
    style User fill:#e1f5ff
    style Frontend fill:#fff4e6
    style Backend fill:#e8f5e9
    style Workflow fill:#f3e5f5
    style Tools fill:#fce4ec
    style State fill:#fff9c4
    style Critic fill:#ffebee
```

## 🧭 System Overview

- **Streamlit UI (`streamlit_app.py`)** – provides the chat interface and calls the backend over HTTP. Session IDs persist in URL query params to maintain state across page refreshes.
- **FastAPI backend (`api/main.py`)** – exposes `/sessions` and `/sessions/{id}/turns` endpoints, forwarding every turn to the runtime and returning updated state plus any human-in-the-loop interrupts.
- **Redis Session Storage (`workflows/storage.py`)** – persists `TravelPlannerState` with 24-hour TTL, falling back to in-memory storage if Redis is unavailable.
- **TravelPlannerRuntime (`workflows/runtime.py`)** – manages workflow orchestration, maintains thread-specific workflow instances, and coordinates agent execution.
- **Multi-Agent Orchestrator (`workflows/workflow.py`)** – coordinates the four-phase workflow (collecting → researching → planning → budgeting) with human-in-the-loop interrupts.
- **Agents & tools (`agents/`, `tools/`)** – specialized components that gather preferences (chat), research data (weather, attractions, dining, hotels, car + fuel, distances), craft itineraries, and estimate budgets.

## � How It Works

### Workflow Phases

The system operates through four distinct phases with critic-driven validation:

#### 1️⃣ **Collecting Phase** (ChatAgent)
- Extracts 8 core preferences through natural conversation:
  - Destination city
  - Start date and trip duration
  - Number of travelers
  - Budget constraints
  - Accommodation and transportation preferences
  - Cuisine and activity interests
- Uses Gemini LLM with structured prompts
- Maintains conversation history for context
- Streams responses for real-time UI updates

#### 2️⃣ **Researching Phase** (ResearchAgent)
- **Parallel tool execution** with configurable concurrency (default: 5 concurrent tasks)
- Aggregates data from multiple sources:
  - **Weather**: 7-day forecast with temperature, precipitation, conditions
  - **Attractions**: POIs from Google Places with ratings, categories, coordinates
  - **Dining**: Restaurants with price levels, ratings, cuisine types
  - **Hotels**: Availability and pricing via Amadeus API
  - **Flights**: Optional flight search for trip planning
  - **Car & Fuel**: Combined pricing (daily rates + fuel costs per gallon)
  - **Distance Matrix**: Travel times and distances between locations
- **Retry logic**: Exponential backoff for 429/5xx errors (3 retries max)
- **Normalization**: Standardized output format with `{id, name, price, coord, source, raw}`
- **Human-in-the-Loop Interrupts**:
  - `select_attractions`: User chooses favorite places
  - `select_restaurants`: User picks dining spots
  - Supports refinement (add specific places not in initial results)

#### 3️⃣ **Planning Phase** (ItineraryAgent)
- **LLM-assisted scheduling** with Gemini
- Creates day-by-day itineraries with:
  - Time blocks (start time + duration)
  - Stop sequencing based on proximity
  - Activity categorization (morning/afternoon/evening)
- **Route enrichment**:
  - Live routing via Google Maps Directions API
  - Distance and duration calculations
  - Travel mode support (DRIVE, WALK, TRANSIT)
- **Street View integration**: Preview images for each stop
- **Validation & auto-correction**:
  - Checks time conflicts, impossible schedules
  - Validates coordinates and addresses
  - Auto-fixes common LLM errors

#### 4️⃣ **Budgeting Phase** (BudgetAgent)
- Estimates costs across categories:
  - **Hotels**: Based on actual search results or default rates
  - **Dining**: Per-person daily estimates
  - **Activities**: Per-stop admission fees
  - **Fuel**: Distance-based calculation using fuel efficiency (26 MPG default)
  - **Car Rental**: Daily rates from combined car_price tool
- **Critic Loop Validation**:
  - Checks budget constraints from preferences
  - Identifies requirement violations
  - Generates user-friendly explanations via LLM
  - Can trigger replanning if violations found
- Outputs: expected cost, low/high range, detailed breakdown

### Session Management

- **Redis-backed persistence**: Sessions survive restarts, 24-hour TTL
- **URL-based session recovery**: Session ID in query params enables refresh

## 🛠️ Available Tools

### Core Research Tools

| Tool | Provider | Function | Output |
|------|----------|----------|--------|
| **Weather** | Open-Meteo | `get_weather(city, start_date, duration, units)` | 7-day forecast with temp, precip, conditions |
| **Attractions** | Google Places | `search_attractions(city, keyword, limit)` | POIs with ratings, categories, coordinates |
| **Dining** | Google Places | `search_restaurants(lat, lng, radius, keyword)` | Restaurants with price levels, ratings |
| **Hotels** | Amadeus | `search_hotels_by_city(city, checkin, checkout, adults, currency)` | Hotels with availability, pricing |
| **Flights** | Amadeus | `search_flights(origin, dest, date, adults, currency)` | Flight options with pricing |
| **Car & Fuel** | Gemini | `get_car_and_fuel_prices(location)` | Combined fuel + rental pricing by vehicle type |
| **Distance Matrix** | Google Maps | `get_distance_matrix(origins, dests, mode)` | Travel times and distances |

### Enrichment Tools

| Tool | Provider | Function | Output |
|------|----------|----------|--------|
| **Routes** | Google Maps | `get_route(origin, dest, mode)` | Turn-by-turn directions with polylines |
| **Street View** | Google Maps | `get_streetview_url(lat, lng, heading)` | Preview image URLs for locations |

### Tool Features

- **Timeout management**: 20s default, configurable per tool
- **Retry logic**: Manual exponential backoff (no `tenacity` dependency in tools)
- **Error handling**: Fail-fast with status-specific retries (429, 5xx)
- **Logging**: Request/response logging without secrets
- **Normalization**: Consistent schema with `source` attribution

### API Key Configuration

All tools use centralized config (`config.py`) with support for:
- Environment variables (`.env` file via `python-dotenv`)
- AWS Secrets Manager integration (production deployment)
- Graceful degradation (warnings instead of crashes)

Required keys:
- `GOOGLE_MAPS_API_KEY` - Maps, Places, Routes, Distance Matrix, Street View
- `GOOGLE_API_KEY` or `GEMINI_API_KEY` - LLM calls (Gemini)
- `AMADEUS_API_KEY` + `AMADEUS_API_SECRET` - Hotels and flights

## �🚀 Running the Travel Planning Agent

### 1. Setup (One-time)
```bash
# Clone and install deps
cd travel_planner-main
pip install -r requirements.txt

# Copy .env.example to .env and add your API keys
cp .env.example .env
# Then edit .env with your actual API keys

# Or create .env manually:
cat > .env <<'EOF'
GOOGLE_MAPS_API_KEY=your_key_here
GOOGLE_API_KEY=your_gemini_key_here
AMADEUS_API_KEY=your_amadeus_key_here
AMADEUS_API_SECRET=your_amadeus_secret_here
EOF
```

**Note:** The project now uses `python-dotenv` to automatically load environment variables from `.env`. All configuration is centralized in `config.py`.


### 2. Run the FastAPI backend with Redis
```bash
# Start Redis container
docker run -d -p 6379:6379 redis:7-alpine

# Set environment variables
export REDIS_URL="redis://localhost:6379/0"

# Run FastAPI
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**Expected output:**
```
INFO:     Connected to Redis for session storage
INFO:     Started server process [xxxxx]
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Expose required API keys as environment variables before launching the service.

### 3. Run the Streamlit front end
```bash
export TRAVEL_PLANNER_API_URL="http://localhost:8000"
streamlit run streamlit_app.py
```

**Features:**
- Session persistence via URL query params (survives refresh!)
- Real-time streaming responses
- Interactive selection UI for attractions/restaurants
- Refinement option to add specific places
- Budget and itinerary visualization

**Access:** Open browser to http://localhost:8501

### 4. Health check
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok"}
```

### 5. Run the automated tests
```bash
pytest -v
```

### 5. Run the automated tests
```bash
pytest -v
```


## 📦 Deployment to AWS App Runner
See [DEPLOYMENT.md](DEPLOYMENT.md) for complete step-by-step instructions.

---

## 🧪 End-to-End Flow

1. **User sends message** → Streamlit POSTs to `/sessions/{id}/turns`
2. **Runtime processes turn** → `TravelPlannerOrchestrator` updates state machine
3. **Agent execution** → ChatAgent → ResearchAgent → (interrupt) → ItineraryAgent → BudgetAgent
4. **Tool calls** → Parallel execution with retry/backoff, normalize results
5. **Critic validation** → Check requirements, auto-correct violations
6. **State update** → Save to Redis with 24hr TTL
7. **Response** → Updated state + interrupts returned to Streamlit
8. **UI render** → Chat history, selections, itinerary, budget displayed

### Session Persistence

- Session ID stored in URL query params
- Survives page refresh and browser restarts
- Redis backend ensures data survives service restarts
- 24-hour TTL (configurable via `SESSION_TTL_SECONDS`)

---

## 📋 Configuration & Environment Variables

### Required (Production)
- `GOOGLE_MAPS_API_KEY` - Maps/Places/Routes
- `GOOGLE_API_KEY` or `GEMINI_API_KEY` - LLM
- `AMADEUS_API_KEY` + `AMADEUS_API_SECRET` - Hotels/Flights
- `REDIS_URL` - Redis connection (e.g., `redis://:password@host:6379/0`)
- `CORS_ORIGINS` - Comma-separated allowed origins (no wildcards in prod!)

### Optional
- `DEFAULT_MODEL_NAME` - Gemini model (default: `gemini-3-flash-preview`)
- `DEFAULT_TEMPERATURE` - LLM temperature (default: `0.2`)
- `SESSION_TTL_SECONDS` - Redis TTL (default: `86400` = 24hrs)
- `RESEARCH_MAX_CONCURRENCY` - Parallel tool calls (default: `5`)
- `AWS_SECRETS_MANAGER_SECRET_NAME` - For production API key management

### AWS Deployment
- `AWS_REGION` - AWS region (default: `us-east-1`)
- `TRAVEL_PLANNER_API_URL` - FastAPI service URL (for Streamlit)

All configuration centralized in [`config.py`](config.py).

---

## 🏗️ Project Structure

```
travel_planner-main/
├── agents/                    # Specialized AI agents
│   ├── chat_agent.py         # Conversation & preference extraction
│   ├── research_agent.py     # Parallel tool orchestration
│   ├── itinerary_agent.py    # Day-by-day scheduling
│   ├── budget_agent.py       # Cost estimation & validation
│   └── prompts/              # LLM prompt templates
├── tools/                     # External API integrations
│   ├── weather.py            # Open-Meteo weather API
│   ├── attractions.py        # Google Places POI search
│   ├── dining.py             # Google Places restaurants
│   ├── hotels.py             # Amadeus hotel search
│   ├── flight.py             # Amadeus flight search
│   ├── car_price.py          # Gemini-powered fuel + car rental
│   ├── distance_matrix.py    # Google Maps distances
│   ├── routes.py             # Google Maps directions
│   └── streetview.py         # Street View image URLs
├── workflows/                 # Orchestration layer
│   ├── workflow.py           # Multi-agent coordinator
│   ├── runtime.py            # FastAPI runtime wrapper
│   ├── state.py              # Shared state schema
│   ├── storage.py            # Redis session storage
│   └── schemas.py            # Pydantic data models
├── api/                       # FastAPI backend
│   └── main.py               # REST endpoints
├── tests/                     # Test suite
│   ├── agents/               # Agent unit tests
│   ├── tools/                # Tool integration tests
│   └── workflows/            # Workflow tests
├── streamlit_app.py           # Frontend UI
├── config.py                  # Centralized configuration
├── requirements.txt           # Python dependencies
├── Dockerfile.fastapi         # Backend container
├── Dockerfile.streamlit       # Frontend container
├── deploy.sh                  # AWS deployment script
└── DEPLOYMENT.md              # AWS App Runner guide
```

---

## 📚 Key Technologies

- **LangChain** - Agent framework and LLM orchestration
- **Google Gemini** - LLM for chat, extraction, scheduling, validation
- **FastAPI** - High-performance async REST API
- **Streamlit** - Interactive chat UI
- **Redis** - Session persistence and caching
- **Pydantic** - Data validation and schemas
- **httpx** - Async HTTP client for tool calls
- **Docker** - Containerization for deployment
- **AWS App Runner** - Serverless container deployment

---
## 📄 License

See [LICENSE](LICENSE) file for details.

---