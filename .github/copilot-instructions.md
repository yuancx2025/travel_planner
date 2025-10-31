# Copilot Rules — Multi‑Agent Travel Planner (GCP)

Make the smallest, repo‑aligned change that can ship on GCP Cloud Run using the existing layout:

agents/ • tools/ • workflows/ • tests/ • app.py • requirements.txt • README.md

## Operating mode
- Repo‑aware first. Reuse files/patterns; no folder reshuffles.
- Minimal patches. Edit in place; single responsibility per file.
- Cloud‑ready. Code must be containerizable and configured via env vars.

## Response format (every answer)
1) Scope – files (≤2) and purpose
2) Diff estimate – ~N lines, new files? yes/no
3) Plan/Code – if >80 LOC, output plan only (tree + interfaces + pseudocode)
4) Run/Verify – pytest/uvicorn/gcloud commands
5) Ops notes – new env vars, secrets, IAM

## Online docs check (mandatory)
- Before implementing: look up latest official docs/release notes for any API/library you will use or modify.
- Cite 1–2 authoritative links and relevant version(s) in the response. Prefer vendor docs over blogs.
- If docs conflict or are unclear, ask a one‑sentence clarification before changing code.

## Guardrails
- Diff limit ≈ 80 added lines; function size ≈ 60 LOC.
- Ask‑before‑create for any new file (name, purpose, integration).
- No unrelated refactors/moves.

## Deps & stack
- Priority: (1) existing imports, (2) requirements.txt pins, (3) approved stack, (4) anything new → ask first.
- Approved: fastapi, uvicorn[standard], httpx, pydantic, pydantic-ai, langgraph, google-generativeai or google-cloud-aiplatform, google-cloud-secret-manager, google-cloud-firestore or sqlalchemy, tenacity.
- Translate legacy/LangChain tutorials to LangGraph + Pydantic‑AI + google‑generativeai style.

## Contracts (do not break)
- Tools: weather_v2, attractions, dining, hotels, car_rental, fuel_price, distance_matrix (repo file may be named distance_matirx.py).
- Return keys must stay: weather, attractions, dining, hotels, car_rentals, fuel_prices, distances.
- Normalize items: {id?, name?, price?, coord?, source, raw} with source ∈ {google, amadeus, rapidapi, open-meteo}.

## Tool/API rules
- httpx: timeout ≤ 20s; exponential backoff (tenacity) on 429/5xx.
- Fail fast; avoid broad try/except. Log endpoint, status, duration (no secrets/PII).

## FastAPI backend (Cloud Run)
- Endpoints only: /v1/plan, /v1/research, /health, /readiness.
- Async handlers, Pydantic models, versioned paths.
- Rate limit: 100 rpm/IP (RATE_LIMIT_RPM). CORS allowlist via CORS_ORIGINS (no wildcards in prod).
- Structured JSON logging with trace context; SSE only if asked.

## Agents & state
- Shared state = TypedDict with snake_case keys. Agents return new dicts (no in‑place mutation).
- Propose edges + state keys before adding a LangGraph node; include validation schemas.

## Data layer
- Cloud SQL (Postgres) → adapters/sql.py: SQLAlchemy with pooling (min 5, max 20), ctx‑managed transactions, parameterized queries; Alembic for migrations.

## Config & secrets
- Never hardcode keys. Use os.environ or Secret Manager.
- Required envs: ENV, PORT, GOOGLE_PROJECT_ID, GOOGLE_LOCATION, GOOGLE_GENAI_MODEL, DATABASE_URL (or Firestore), plus API keys. Public vars prefixed NEXT_PUBLIC_.
- Security: rotate API keys ≤90 days; use Workload Identity; never log secrets.

## Build/Deploy/Observability
- Dockerfile: python:3.11‑slim, non‑root, multi‑stage, expose /health and /readiness.
- Health: /health → {"status":"ok"}; /readiness checks DB/external APIs.
- Cloud Build: lint → test → build → push → deploy (staging=main; prod=tags vX.Y.Z).
- Logs: structured JSON; Metrics/Tracing: p50/p95/p99 latency, error rate, API success/failure, X‑Cloud‑Trace‑Context, Error Reporting.

## Testing
- Unit tests for non‑trivial functions/endpoints; coverage ≥80%.
- Mock HTTP; no live APIs in CI. Integration tests for critical flows.
- Typical commands:
  - pytest tests/test_*.py -v --cov=. --cov-report=term-missing
  - uvicorn app:app --port 8080

## Errors & security
- Error model: {"error": "code", "message": "...", "trace_id": "..."}; include trace_id.
- Status codes: 400/401/404/429/500/503. Fail fast.
- Validate all inputs with Pydantic. Prevent SQL injection (parameterized). HTTPS in prod. No PII in logs.

## Performance budgets
- API p95 < 2s (ex‑LLM); external API timeout < 5s; DB p95 < 100ms; memory < 512MB/container.

## Anti‑bloat & hard no’s
- No new scaffolding unless asked. Extend existing agents/tools first.
- If change >80 lines → plan first (pseudocode + file tree).
- No Pub/Sub, Redis, BigQuery, or multi‑cloud adds without approval.
- No renaming tool functions/return keys, no secrets in code/tests, no folder re‑orgs, no wildcard CORS in prod.

## Final rule
If unsure, ask a one‑sentence clarification. If over diff budget, stop and output a plan instead of code.