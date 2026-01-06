"""Typed state models shared across the travel planner workflow."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from workflows.schemas import CriticEvaluation, UserPreferences, ResearchOutput


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
    def from_raw(cls, payload: Optional[Any]) -> "ResearchState":
        """Create ResearchState from ResearchOutput schema or dict."""
        if payload is None:
            return cls()
        
        # If it's a ResearchOutput schema, convert it
        if isinstance(payload, ResearchOutput):
            return cls(
                attractions=[attr.model_dump(exclude_none=True) for attr in payload.attractions],
                dining=[rest.model_dump(exclude_none=True) for rest in payload.dining],
                raw=payload.to_dict(),
            )
        
        # Otherwise, treat as dict (backward compatibility)
        if isinstance(payload, dict):
            return cls(
                attractions=list(payload.get("attractions") or []),
                dining=list(payload.get("dining") or []),
                raw=dict(payload),
            )
        
        return cls()


class TravelPlannerState(BaseModel):
    thread_id: str
    phase: Literal[
        "collecting",
        "researching",
        "selecting_attractions",
        "refining_research",
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
    research_iteration: int = 0
    research_refinement_history: List[Dict[str, Any]] = Field(default_factory=list)
    max_refinement_iterations: int = 2
    # New fields for critic loop
    critic_iterations: int = 0
    max_critic_iterations: int = 3
    last_critic_evaluation: Optional[CriticEvaluation] = None
    requirement_explanation: Optional[str] = None
