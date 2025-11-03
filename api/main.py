"""FastAPI application exposing the travel planner runtime."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from workflows.runtime import TravelPlannerRuntime
from workflows.state import TravelPlannerState

app = FastAPI(title="Travel Planner API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

runtime = TravelPlannerRuntime()
_sessions: Dict[str, TravelPlannerState] = {}


def _serialize_state(state: TravelPlannerState) -> Dict[str, Any]:
    return jsonable_encoder(state.model_dump())


def _serialize_interrupts(interrupts: Any) -> List[Any]:
    if not interrupts:
        return []
    if isinstance(interrupts, list):
        return jsonable_encoder(interrupts)
    return jsonable_encoder(list(interrupts))


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions")
async def create_session() -> Dict[str, Any]:
    state, interrupts = await runtime.run_turn(None, None)
    session_id = state.thread_id
    _sessions[session_id] = state
    return {
        "session_id": session_id,
        "state": _serialize_state(state),
        "interrupts": _serialize_interrupts(interrupts),
    }


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "state": _serialize_state(state),
        "interrupts": [],
    }


@app.post("/sessions/{session_id}/turns")
async def process_turn(
    session_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    payload = payload or {}
    message = payload.get("message")
    interrupt_payload = payload.get("interrupt")
    extra_payload = {k: v for k, v in payload.items() if k not in {"message", "interrupt"}}

    if interrupt_payload is not None:
        user_input: Any = interrupt_payload
    elif extra_payload:
        user_input = extra_payload
    else:
        user_input = message

    new_state, interrupts = await runtime.run_turn(state, user_input)
    _sessions[session_id] = new_state

    return {
        "session_id": session_id,
        "state": _serialize_state(new_state),
        "interrupts": _serialize_interrupts(interrupts),
    }

