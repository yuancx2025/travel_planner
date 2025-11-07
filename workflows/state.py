"""Typed state models shared across the travel planner workflow."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PreferencesState(BaseModel):
    fields: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    complete: bool = False


class ResearchState(BaseModel):
    attractions: List[Dict[str, Any]] = Field(default_factory=list)
    dining: List[Dict[str, Any]] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, payload: Optional[Dict[str, Any]]) -> "ResearchState":
        payload = payload or {}
        return cls(
            attractions=list(payload.get("attractions") or []),
            dining=list(payload.get("dining") or []),
            raw=dict(payload),
        )


class TravelPlannerState(BaseModel):
    thread_id: str
    phase: Literal[
        "collecting",
        "researching",
        "selecting_attractions",
        "selecting_restaurants",
        "building_itinerary",
        "complete",
    ] = "collecting"
    preferences: PreferencesState = Field(default_factory=PreferencesState)
    conversation_turns: List[ConversationTurn] = Field(default_factory=list)
    research: Optional[ResearchState] = None
    selected_attractions: List[Dict[str, Any]] = Field(default_factory=list)
    selected_restaurants: List[Dict[str, Any]] = Field(default_factory=list)
    itinerary: Optional[Dict[str, Any]] = None
    planning_context: Optional[str] = None
    budget: Optional[Dict[str, Any]] = None
