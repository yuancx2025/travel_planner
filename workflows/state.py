from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    """A single conversational exchange turn."""

    role: str
    content: str


class PreferencesState(BaseModel):
    """Holds extracted preference fields and completion metadata."""

    fields: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    complete: bool = False


class TravelPlannerState(BaseModel):
    """State container shared across the travel planning workflow graph."""

    thread_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    conversation_turns: List[ConversationTurn] = Field(default_factory=list)
    preferences: PreferencesState = Field(default_factory=PreferencesState)
    preferences_signature: Optional[str] = None
    research_preferences_signature: Optional[str] = None
    research: Dict[str, Any] = Field(default_factory=dict)
    candidate_attractions: List[Dict[str, Any]] = Field(default_factory=list)
    selected_attractions: List[Dict[str, Any]] = Field(default_factory=list)
    itinerary: Dict[str, Any] = Field(default_factory=dict)
    itinerary_approved: bool = False
    budget: Dict[str, Any] = Field(default_factory=dict)
    budget_confirmed: bool = False
    phase: str = "collecting_preferences"
    pending_user_input: Optional[str] = None
    last_agent_response: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    def push_user_turn(self, content: str) -> None:
        if content:
            self.conversation_turns.append(ConversationTurn(role="user", content=content))
            self.pending_user_input = content

    def push_agent_turn(self, content: str) -> None:
        if content:
            self.conversation_turns.append(ConversationTurn(role="assistant", content=content))
            self.last_agent_response = content

    @property
    def preference_fields(self) -> Dict[str, Any]:
        return dict(self.preferences.fields)

