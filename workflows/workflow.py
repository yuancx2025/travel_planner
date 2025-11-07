"""Travel planner workflow orchestration.

This module exposes :class:`TravelPlannerWorkflow`, a high-level coordinator that
ties together the chat, research, itinerary, and budget agents.  The class is
pure-Python and intentionally lightweight so it can run both in interactive
scripts (see ``run_smoke_test`` at the bottom) and inside the FastAPI runtime.

The workflow operates in four phases:

1. Conversation: ``ChatAgent`` gathers structured preferences from the user.
2. Research: ``ResearchAgent`` uses those preferences to fetch attractions and
   restaurants.
3. Selection: the caller responds to interrupts to choose favourite
   attractions/dining spots.
4. Planning: ``ItineraryAgent`` and ``BudgetAgent`` craft an itinerary and cost
   estimate based on the selections.

The workflow keeps a single typed source of truth represented by
``TravelPlannerState`` (defined in :mod:`workflows.state`).
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.budget_agent import BudgetAgent
from agents.chat_agent import ChatAgent
from agents.itinerary_agent import ItineraryAgent

try:  # pragma: no cover - import guard for smoke test environments
    from agents.research_agent import ResearchAgent
    _RESEARCH_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - guard against missing credentials
    ResearchAgent = None  # type: ignore
    _RESEARCH_IMPORT_ERROR = exc
from workflows.state import (
    ConversationTurn,
    PreferencesState,
    ResearchState,
    TravelPlannerState,
)


SelectionInterrupt = Dict[str, Any]


def _consume_stream(stream: Optional[Iterable[Any]]) -> str:
    """Convert the streaming response from ``ChatAgent`` into plain text."""

    if stream is None:
        return ""

    chunks: List[str] = []
    for item in stream:
        content = getattr(item, "content", None)
        if content is None:
            continue
        if isinstance(content, (list, tuple)):
            chunks.extend(str(part) for part in content)
        else:
            chunks.append(str(content))
    return "".join(chunks)


class TravelPlannerWorkflow:
    """Coordinate the travel-planning workflow across all agents."""

    def __init__(
        self,
        *,
        chat_agent: Optional[ChatAgent] = None,
        research_agent: Optional[ResearchAgent] = None,
        itinerary_agent: Optional[ItineraryAgent] = None,
        budget_agent: Optional[BudgetAgent] = None,
    ) -> None:
        self.chat_agent = chat_agent or ChatAgent()
        if research_agent is not None:
            self.research_agent = research_agent
        else:
            if ResearchAgent is None:
                raise RuntimeError(
                    "ResearchAgent is unavailable. Check API credentials and optional dependencies."
                ) from _RESEARCH_IMPORT_ERROR
            self.research_agent = ResearchAgent()
        self.itinerary_agent = itinerary_agent or ItineraryAgent()
        self.budget_agent = budget_agent or BudgetAgent()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def initial_state(self, thread_id: str) -> TravelPlannerState:
        """Create a brand-new workflow state for ``thread_id``."""

        return TravelPlannerState(thread_id=thread_id, phase="collecting")

    def start(self, state: TravelPlannerState) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """Kick off the conversation with the user."""

        chat_result = self.chat_agent.collect_info("", state.preferences.fields)
        reply = _consume_stream(chat_result.get("stream")) or (
            "Hi there! Tell me a bit about the trip you're planning so I can help."
        )

        preferences = PreferencesState(
            fields=dict(chat_result.get("state", {})),
            missing_fields=list(chat_result.get("missing_fields", [])),
            complete=bool(chat_result.get("complete")),
        )

        new_turns = state.conversation_turns + [ConversationTurn(role="assistant", content=reply)]

        state = state.model_copy(update={
            "preferences": preferences,
            "conversation_turns": new_turns,
        })

        return state, []

    # ------------------------------------------------------------------
    # Public workflow API
    # ------------------------------------------------------------------
    def handle_user_message(
        self, state: TravelPlannerState, message: str
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """Process a free-form user message."""

        turns = state.conversation_turns + [ConversationTurn(role="user", content=message)]

        chat_result = self.chat_agent.collect_info(message, state.preferences.fields)
        reply = _consume_stream(chat_result.get("stream")) or (
            "Thanks! I'll keep that in mind."
        )

        preferences = PreferencesState(
            fields=dict(chat_result.get("state", {})),
            missing_fields=list(chat_result.get("missing_fields", [])),
            complete=bool(chat_result.get("complete")),
        )

        turns.append(ConversationTurn(role="assistant", content=reply))

        state = state.model_copy(update={
            "preferences": preferences,
            "conversation_turns": turns,
            "phase": "collecting",
        })

        interrupts: List[SelectionInterrupt] = []
        if preferences.complete:
            state, interrupts = self._run_research(state)

        return state, interrupts

    def handle_interrupt(
        self, state: TravelPlannerState, payload: Dict[str, Any]
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """Process structured input from an interrupt (selection UI)."""

        if state.phase == "selecting_attractions":
            indices = self._normalize_indices(payload.get("selected_indices"))
            state = self._apply_selection(state, indices, kind="attractions")
            return self._after_attractions_selected(state)

        if state.phase == "selecting_restaurants":
            indices = self._normalize_indices(payload.get("selected_indices"))
            state = self._apply_selection(state, indices, kind="restaurants")
            state = state.model_copy(update={"phase": "building_itinerary"})
            return self._finalize_plan(state)

        # Any other interrupts are ignored gracefully.
        return state, []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _normalize_indices(self, raw: Any) -> List[int]:
        if raw is None:
            return []
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            indices: List[int] = []
            for value in raw:
                try:
                    idx = int(value)
                except (TypeError, ValueError):
                    continue
                if idx >= 0:
                    indices.append(idx)
            return indices
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            return []
        return [idx] if idx >= 0 else []

    def _run_research(
        self, state: TravelPlannerState
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        preferences = dict(state.preferences.fields)

        try:
            research_results = self.research_agent.research(preferences)
        except Exception as exc:  # pragma: no cover - defensive logging
            research_results = {"error": str(exc)}

        research_state = ResearchState.from_raw(research_results)

        message = (
            "Great! I've gathered ideas for your trip. Let's pick the attractions you don't want to miss."
        )
        turns = state.conversation_turns + [ConversationTurn(role="assistant", content=message)]

        state = state.model_copy(update={
            "research": research_state,
            "conversation_turns": turns,
        })

        attractions = [item for item in research_state.attractions if not item.get("error")]
        if attractions:
            state = state.model_copy(update={"phase": "selecting_attractions"})
            return state, [self._build_selection_interrupt("attractions", attractions)]

        # No attractions to choose. Move straight to restaurants / itinerary.
        state = state.model_copy(update={
            "selected_attractions": [],
            "phase": "selecting_restaurants",
        })
        return self._after_attractions_selected(state)

    def _after_attractions_selected(
        self, state: TravelPlannerState
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        restaurants = []
        if state.research:
            restaurants = [item for item in state.research.dining if not item.get("error")]

        if restaurants:
            state = state.model_copy(update={"phase": "selecting_restaurants"})
            prompts = "Great choices! Fancy any of these dining spots?"
            turns = state.conversation_turns + [
                ConversationTurn(role="assistant", content=prompts)
            ]
            state = state.model_copy(update={"conversation_turns": turns})
            return state, [self._build_selection_interrupt("restaurants", restaurants)]

        state = state.model_copy(update={
            "selected_restaurants": [],
            "phase": "building_itinerary",
        })
        return self._finalize_plan(state)

    def _apply_selection(
        self, state: TravelPlannerState, indices: List[int], *, kind: str
    ) -> TravelPlannerState:
        research = state.research or ResearchState()
        options = research.attractions if kind == "attractions" else research.dining
        chosen: List[Dict[str, Any]] = []

        for idx in indices:
            if 0 <= idx < len(options):
                chosen.append(options[idx])

        field = "selected_attractions" if kind == "attractions" else "selected_restaurants"
        return state.model_copy(update={field: chosen})

    def _finalize_plan(
        self, state: TravelPlannerState
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        research_dict = state.research.raw if state.research else {}
        preferences = dict(state.preferences.fields)
        attractions = state.selected_attractions or (
            (state.research.attractions if state.research else [])
        )
        itinerary: Optional[Dict[str, Any]] = None
        planning_context: Optional[str] = None
        budget_summary: Optional[Dict[str, Any]] = None

        try:
            if attractions:
                itinerary = self.itinerary_agent.build_itinerary(
                    preferences=preferences,
                    attractions=attractions,
                    research=research_dict,
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            itinerary = {"error": str(exc)}

        try:
            planning_context = self.itinerary_agent.build_planning_context(
                user_state=preferences,
                research_results=research_dict,
                itinerary=itinerary if isinstance(itinerary, dict) else None,
                budget=budget_summary,
                selected_attractions=attractions,
            )
        except Exception:
            planning_context = None

        try:
            budget_summary = self.budget_agent.compute_budget(
                preferences=preferences,
                research=research_dict,
                itinerary=itinerary if isinstance(itinerary, dict) else None,
            )
        except Exception:
            budget_summary = None

        message = "Here's a draft itinerary based on everything you've shared."
        turns = state.conversation_turns + [ConversationTurn(role="assistant", content=message)]

        state = state.model_copy(update={
            "itinerary": itinerary,
            "planning_context": planning_context,
            "budget": budget_summary,
            "conversation_turns": turns,
            "phase": "complete",
        })

        return state, []

    def _build_selection_interrupt(
        self, kind: str, options: Sequence[Dict[str, Any]]
    ) -> SelectionInterrupt:
        enriched_options: List[Dict[str, Any]] = []
        for option in options:
            coord = option.get("coord") or {}
            lat = coord.get("lat")
            lng = coord.get("lng")
            street_view_url = None
            map_url = None
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                street_view_url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
                map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"

            enriched_options.append(
                {
                    "id": option.get("id"),
                    "name": option.get("name"),
                    "address": option.get("address"),
                    "rating": option.get("rating"),
                    "review_count": option.get("review_count"),
                    "price_level": self._format_price_level(option.get("price_level")),
                    "street_view_url": street_view_url,
                    "map_url": map_url,
                }
            )

        prompt = (
            "Select the attractions you want to visit"
            if kind == "attractions"
            else "Pick the dining spots you'd like to try"
        )

        return {
            "type": f"select_{kind}",
            "message": prompt,
            "options": enriched_options,
        }

    def _format_price_level(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str) and value.startswith("PRICE_LEVEL_"):
            return value.replace("PRICE_LEVEL_", "").title()
        if isinstance(value, str) and value.strip("$").isdigit():
            count = max(1, min(5, int(value.strip("$"))))
            return "$" * count
        if isinstance(value, (int, float)) and not math.isnan(float(value)):
            count = max(1, min(5, int(round(float(value)))))
            return "$" * count
        if isinstance(value, str) and value:
            return value
        return None


# ----------------------------------------------------------------------
# Smoke test helpers
# ----------------------------------------------------------------------


@dataclass
class _StubAgentReply:
    content: str


class _StubChatAgent:
    """Deterministic chat agent used in the smoke test."""

    def __init__(self) -> None:
        self._called = False

    def collect_info(self, message: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = dict(state or {})
        if not self._called:
            reply = "Tell me about your travel plans."
        else:
            reply = "Wonderful! I'll research options now."
            state.update(
                {
                    "destination_city": "Seattle",
                    "travel_days": 3,
                    "start_date": "2024-07-01",
                    "budget_usd": 2500,
                    "num_people": 2,
                    "kids": "no",
                    "activity_pref": "outdoor",
                    "need_car_rental": "no",
                    "hotel_room_pref": "king bed",
                    "cuisine_pref": "seafood",
                }
            )
        self._called = True
        return {
            "stream": [_StubAgentReply(reply)],
            "state": state,
            "missing_fields": [],
            "complete": True,
        }


class _StubResearchAgent:
    def research(self, state: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - simple stub
        return {
            "attractions": [
                {
                    "id": "attr_1",
                    "name": "Space Needle",
                    "address": "400 Broad St",
                    "rating": 4.7,
                    "review_count": 1234,
                    "coord": {"lat": 47.6205, "lng": -122.3493},
                },
                {
                    "id": "attr_2",
                    "name": "Pike Place Market",
                    "address": "85 Pike St",
                    "rating": 4.8,
                    "review_count": 5230,
                    "coord": {"lat": 47.6097, "lng": -122.3425},
                },
            ],
            "dining": [
                {
                    "id": "rest_1",
                    "name": "Elliott's Oyster House",
                    "address": "1201 Alaskan Way",
                    "rating": 4.5,
                    "review_count": 3487,
                    "price_level": 3,
                    "coord": {"lat": 47.6053, "lng": -122.3405},
                }
            ],
        }


class _StubItineraryAgent:
    def build_itinerary(self, preferences: Dict[str, Any], attractions: Sequence[Dict[str, Any]], research: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - simple stub
        return {
            "days": [
                {
                    "day": 1,
                    "stops": [
                        {
                            "name": attractions[0]["name"],
                            "coord": attractions[0].get("coord"),
                            "streetview_url": "https://www.google.com/maps",
                        }
                    ],
                }
            ]
        }

    def build_planning_context(
        self,
        *,
        user_state: Dict[str, Any],
        research_results: Dict[str, Any],
        itinerary: Optional[Dict[str, Any]],
        budget: Optional[Dict[str, Any]],
        selected_attractions: Optional[Sequence[Dict[str, Any]]],
    ) -> str:  # pragma: no cover - simple stub
        return "Enjoy Seattle!"


class _StubBudgetAgent:
    def compute_budget(
        self,
        *,
        preferences: Dict[str, Any],
        research: Dict[str, Any],
        itinerary: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:  # pragma: no cover - simple stub
        return {"currency": "USD", "expected": 2100}


def run_smoke_test() -> None:
    """Run a deterministic smoke test to validate the workflow wiring."""

    workflow = TravelPlannerWorkflow(
        chat_agent=_StubChatAgent(),
        research_agent=_StubResearchAgent(),
        itinerary_agent=_StubItineraryAgent(),
        budget_agent=_StubBudgetAgent(),
    )

    state = workflow.initial_state("smoke-thread")
    state, _ = workflow.start(state)

    state, interrupts = workflow.handle_user_message(state, "Let's plan a Seattle getaway")
    assert interrupts, "Expected attraction selection interrupt"
    assert interrupts[0]["type"] == "select_attractions"

    state, interrupts = workflow.handle_interrupt(state, {"selected_indices": [0]})
    assert interrupts, "Expected restaurant selection interrupt"
    assert interrupts[0]["type"] == "select_restaurants"

    state, interrupts = workflow.handle_interrupt(state, {"selected_indices": [0]})
    assert state.phase == "complete"
    assert not interrupts

    print("Smoke test passed – workflow completed successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Travel planner workflow utilities")
    parser.add_argument("--smoke", action="store_true", help="Run a smoke test against stub agents")
    args = parser.parse_args()

    if args.smoke:
        run_smoke_test()
    else:
        print("Run with --smoke to execute the workflow smoke test.")
