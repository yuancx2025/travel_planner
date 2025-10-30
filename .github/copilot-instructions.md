# Copilot Instructions (Travel Planner Project)

These rules apply to Copilot Chat/Agents/Workspace when proposing code or edits in this multi-agent travel planning repository.

## 0) Default Mindset
- **Bias to minimalism.** Implement the smallest working solution (MVP) that meets the prompt.
- **Do not create new files** unless explicitly approved (see §2) or the prompt *explicitly* asks for it.
- **Prefer single-file solutions** unless the current file would exceed the limits below.
- **Small diffs first.** Propose incremental changes over large refactors.
- **Agent-first thinking.** Each agent should have a single, well-defined responsibility.

## 1) Size & Complexity Limits
- **Max diff budget:** 80 added lines per request (unless user says "bigger change approved").
- **Max function length:** ~60 LOC; split only when there are ≥3 distinct responsibilities.
- **Max file length target:** ~400–600 LOC. Only split when:
  - file would exceed ~600 LOC *and* separation reduces coupling, or
  - a module is clearly reusable across multiple agents.
- **Cyclomatic complexity:** Keep functions simple; favor early returns over deep nesting.
- **Agent methods:** Each agent's core logic (`run()`, `plan()`, `research()`) should be ≤80 LOC.

## 2) File/Folder Creation Policy
- **Ask-before-create rule (mandatory):**
  - Before adding a new file or directory, **propose a short plan**:
    - File name(s), path(s), 1–2 lines of purpose, and how they integrate with existing agents.
  - Wait for explicit approval in the chat/prompt (e.g., "approved to create X and Y").
- No scaffolding (boilerplate folders, configs, CI, or docs) unless requested.
- No codegen of "helper" modules if equivalent logic is ≤60 LOC and only used once.
- **New agents:** Only create new agent files when the responsibility is clearly distinct from existing agents.

## 3) "YAGNI" Checks & Validation
- Avoid defensive code that isn't requested or required by the immediate usage.
- Only add input validation when:
  - It blocks a known failure mode already encountered or
  - The user asks for robust CLI/API surfaces or
  - It's legally/compliance critical (not typical here).
- **No broad try/except** that masks errors. Fail fast with a clear message.
- **Pydantic models handle validation:** Use `BaseModel` field validators instead of manual checks.

## 4) Dependencies & Imports
- **Standard library first** (pathlib, json, argparse, datetime, os, typing, etc.)
- **Core framework stack (approved):**
  - `langgraph` (workflow orchestration, state graphs)
  - `pydantic` & `pydantic-ai` (data validation, AI agents)
  - `google-genai` (Gemini models, Google ADK/Genkit)
  - `fastapi` & `uvicorn` (REST API, async server)
  - `httpx` (async HTTP client for external APIs)
  - `streamlit` (UI only, optional)
- **External APIs (approved):**
  - Google Maps API (attractions, geocoding, distance matrix)
  - Amadeus API (flights, hotels)
  - RapidAPI (car rentals via Booking.com proxy)
  - Open-Meteo (weather, no key required)
- **Ask before adding:** New LLM providers, alternative agent frameworks, database layers, or UI libraries
- **Avoid:** Multiple LLM libraries (stick to Google ADK), overlapping API wrappers, heavyweight ORMs

## 5) Logging, Telemetry, and I/O
- Keep logging **minimal**: `INFO` for agent transitions, `ERROR` for failures; no verbose debug unless asked.
- Avoid generating logs/files/artifacts unless explicitly requested.
- **Agent output:** Use structured Pydantic models, not print statements.
- **State persistence:** Use in-memory state (LangGraph `StateGraph`) unless persistence is explicitly required.

## 6) Documentation & Comments
- Add a **1–2 line module docstring** and **short function docstrings** (Google or NumPy style).
- No long tutorials or extended prose in code comments unless asked.
- **Agent docstrings:** Clearly state the agent's responsibility and expected input/output state keys.
- **Tool docstrings:** Include provider, endpoint, and return schema in the first 3 lines.

## 7) Testing Policy
- If adding non-trivial logic, include **one focused pytest** test per new public function.
- Keep tests **short** (happy-path + one key edge case). No fixtures unless needed.
- **Agent tests:** Focus on state transformations, not mocking external APIs.
- **Tool tests:** Use `monkeypatch` fixtures (see `tests/conftest.py`) to fake API responses.
- **Integration tests:** Test full workflows (ChatAgent → ResearchAgent → PlannerAgent) sparingly.

## 8) Performance & Data
- Favor **async/await** for I/O-bound operations (API calls, file reads).
- **LangGraph streaming:** Use `agent.astream()` for real-time UI updates when available.
- **Caching:** Use `@lru_cache` for expensive, deterministic operations (geocoding, static data).
- Avoid premature micro-optimizations; do not parallelize unless asked or obviously necessary.
- **Rate limiting:** Respect API limits (use `time.sleep()` or backoff strategies).

## 9) Refactors
- Do not refactor unrelated code in the same change.
- If you believe a refactor is warranted, **propose a plan** (scope, risk, LOC estimate) and wait for approval.
- **Agent refactors:** Only split agents when a single agent exceeds 600 LOC or has ≥3 distinct responsibilities.

## 10) Interaction Protocol (for Copilot Chat/Agents)
When responding to a task:
1. **Confirm scope** in 1–3 bullets (e.g., "Add fuel price tool using Gemini + Google Search").
2. **State diff estimate** (± lines) and whether it needs new files (usually "no").
3. If new files are proposed, follow **Ask-before-create** (§2).
4. Provide a **minimal patch** or code block; keep it in one file unless approved otherwise.
5. Include **exact run/test instructions** if relevant (e.g., `pytest tests/test_fuel_price.py -v`).

---

## 11) Multi-Agent Architecture Conventions

### Agent Structure (Standard Pattern)
```python
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel

class AgentInput(BaseModel):
    """Input schema (state keys this agent consumes)."""
    field1: str
    field2: int

class AgentOutput(BaseModel):
    """Output schema (state keys this agent produces)."""
    result: str

model = GoogleModel("gemini-2.0-flash-exp")

agent = Agent(
    model=model,
    result_type=AgentOutput,
    system_prompt="You are a [role]. Do [task] based on the input.",
)

@agent.tool
def tool_name(ctx: RunContext[AgentInput], arg: str) -> str:
    """Tool docstring: provider, purpose, return type."""
    # Tool logic (max 30 LOC)
    return result

def main_function(input_data: dict) -> dict:
    """Public API for other agents/workflows."""
    inp = AgentInput(**input_data)
    result = agent.run_sync("prompt", deps=inp)
    return result.data.model_dump()
```

### LangGraph Workflow Pattern
```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class TravelState(TypedDict):
    """Shared state across all agents."""
    user_input: str
    preferences: dict
    research_data: dict
    plan: str

def build_graph():
    graph = StateGraph(TravelState)
    graph.add_node("chat", chat_agent.run)
    graph.add_node("research", research_agent.run)
    graph.add_node("planner", planner_agent.run)
    
    graph.set_entry_point("chat")
    graph.add_edge("chat", "research")
    graph.add_edge("research", "planner")
    graph.add_edge("planner", END)
    
    return graph.compile()
```

### Tool Design (External API Wrappers)
- **One tool per file** (unless tightly coupled, e.g., geocoding + search)
- **Normalize outputs:** Return `List[Dict[str, Any]]` with consistent keys (`id`, `name`, `price`, `coord`, `raw`)
- **Provider transparency:** Include `"source": "google"` or `"source": "amadeus"` in every output dict
- **Error handling:** Raise custom exceptions (e.g., `FuelPriceError`, `WeatherError`), not generic `Exception`
- **Retry logic:** Use exponential backoff for transient failures (429, 500, 503)

## 12) API Integration Best Practices
- **API keys:** Read from environment (`os.environ.get()`) with fallback to `.env` file
- **Required keys check:** Validate at module load or function entry, fail fast with clear message
- **Rate limiting:** Default sleep between requests (0.3–0.5s for Google APIs, 1s for RapidAPI)
- **Response validation:** Parse JSON, check `status` field, handle missing/malformed data gracefully
- **Caching:** Cache geocoding results (city → lat/lng) and static reference data
- **Timeout:** Set explicit timeouts (10–20s) for all HTTP requests

## 13) FastAPI Service Conventions
- **Minimal endpoints:** Only expose what agents/UI need (avoid CRUD boilerplate)
- **Request/Response models:** Use Pydantic models for all inputs/outputs
- **Error responses:** Return `{"error": str, "detail": dict}` with appropriate HTTP status codes
- **Async handlers:** Use `async def` for all endpoints that call agents or external APIs
- **Health check:** Include `/health` endpoint that returns `{"status": "ok"}`
- **CORS:** Enable only if UI is on different origin; restrict in production

### Example Endpoint
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Travel Planner API")

class PlanRequest(BaseModel):
    destination: str
    days: int

class PlanResponse(BaseModel):
    plan: str
    metadata: dict

@app.post("/plan", response_model=PlanResponse)
async def create_plan(req: PlanRequest):
    try:
        result = await planner_agent.run(req.model_dump())
        return PlanResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## 14) State Management (LangGraph)
- **Immutable state updates:** Return new dict, don't mutate input state
- **State keys convention:** Use snake_case (e.g., `destination_city`, `research_data`)
- **State typing:** Use `TypedDict` with required/optional fields clearly marked
- **Conditional edges:** Use lambda or function to decide next agent based on state
- **Checkpointing:** Only enable if explicitly needed for conversation persistence

## 15) Google ADK / Pydantic AI Specifics
- **Model selection:**
  - `gemini-2.0-flash-exp` (default, fast, cost-effective)
  - `gemini-2.0-flash-lite` (ultra-fast, simple tasks)
  - `gemini-1.5-pro` (complex reasoning, avoid unless necessary)
- **Google Search grounding:** Use `tools=["google_search_retrieval"]` for real-time web data
- **Structured outputs:** Always use `result_type=YourPydanticModel` for agent responses
- **Tool decorators:** Use `@agent.tool` for functions the model can call
- **Context passing:** Use `RunContext[YourDeps]` to pass state/config to tools
- **Streaming:** Use `agent.run_stream()` for UI responsiveness (optional)

## 16) Error Handling Strategy
- **Custom exceptions:** Define per-module (e.g., `WeatherError`, `FuelPriceError`)
- **Agent errors:** Return error state keys (`{"error": str}`), don't raise in graph nodes
- **API errors:** Retry transient failures (429, 5xx), fail fast on client errors (400, 401, 403)
- **Validation errors:** Let Pydantic raise `ValidationError`, catch at API boundary
- **Logging:** Log errors with context (agent name, state keys, API endpoint) before raising

## 17) Testing Strategy
- **Unit tests:** Test pure functions and tool wrappers with mocked API responses
- **Agent tests:** Test with fake LLM (see `tests/test_chatter_agent_all.py` for pattern)
- **Integration tests:** Test agent chains with minimal state (1–2 agents max)
- **Fixtures:** Use `conftest.py` for shared mocks (fake API responses, fake models)
- **Skip conditions:** Use `@pytest.mark.skipif` for tests requiring live API keys
- **Test data:** Use realistic samples in `tests/fixtures/` (10–20 records max)

---

## Quick Reference: File Organization

```
agents/                  # Agent implementations (1 agent per file)
├── chat_agent.py       # User interaction, preference collection
├── research_agent.py   # Tool orchestration, data gathering
├── planner_agent.py    # High-level workflow coordinator
└── budget_manager.py   # Budget estimation (FastAPI service)

tools/                   # External API wrappers (1 tool per file)
├── weather_v2.py       # Open-Meteo + Google Geocoding
├── attractions.py      # Google Places API
├── dining.py           # Google Places (restaurants)
├── hotels.py           # Amadeus Hotels API
├── flight.py           # Amadeus Flights API
├── car_rental.py       # RapidAPI Booking.com proxy
├── fuel_price.py       # Gemini + Google Search grounding
└── distance_matirx.py  # Google Routes API (distance matrix)

workflows/              # LangGraph workflow definitions
└── travel_graph.py     # Main agent orchestration graph

tests/                  # Pytest test suite
├── conftest.py         # Shared fixtures (fake APIs, models)
├── test_*_agent.py     # Agent unit tests
└── test_*.py           # Tool integration tests

app.py                  # Streamlit UI (optional, TBD)
requirements.txt        # Pinned dependencies
.env                    # API keys (git-ignored)
README.md               # Quick start guide
TESTING_GUIDE.md        # Test execution instructions
```

---

## 18) When to Create New Agents

**Create a new agent file ONLY if:**
1. The new responsibility is **orthogonal** to existing agents (e.g., a new data source)
2. The current agent would exceed **600 LOC** after adding the feature
3. The agent has a **distinct state contract** (different inputs/outputs)

**Do NOT create new agents for:**
- Helper functions (put in same file or `tools/`)
- Variations of existing logic (extend current agent)
- Single-use orchestration (use LangGraph workflow instead)

**Example decision tree:**
- "Add flight price comparison" → Extend `research_agent.py` (already orchestrates tools)
- "Add budget constraint checker" → **Maybe new agent** (distinct responsibility, ~200 LOC)
- "Add email notification" → Tool in `tools/notifications.py` (single function)