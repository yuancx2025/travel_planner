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
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pathlib import Path
import sys

import json
from datetime import datetime, timedelta

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
            self._save_user_profile(state.preferences.fields, state.thread_id)
            state, interrupts = self._run_research(state)

        return state, interrupts

    def handle_interrupt(
        self, state: TravelPlannerState, payload: Dict[str, Any]
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """Process structured input from an interrupt (selection UI)."""

        if state.phase == "selecting_attractions":
            # Check if user wants to refine research instead of selecting
            if payload.get("action") == "refine":
                return self._handle_refinement(state, payload.get("refinement_criteria", {}))

            indices = self._normalize_indices(payload.get("selected_indices"))
            state = self._apply_selection(state, indices, kind="attractions")
            return self._after_attractions_selected(state)

        if state.phase == "selecting_restaurants":
            # Check if user wants to refine research for restaurants
            if payload.get("action") == "refine":
                return self._handle_refinement(state, payload.get("refinement_criteria", {}))

            indices = self._normalize_indices(payload.get("selected_indices"))
            state = self._apply_selection(state, indices, kind="restaurants")
            state = state.model_copy(update={"phase": "building_itinerary"})
            return self._finalize_plan(state)

        # Any other interrupts are ignored gracefully.
        return state, []

    def _handle_refinement(
        self, state: TravelPlannerState, criteria: Dict[str, Any]
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """Handle research refinement request with additional focus criteria."""

        # Check if we've exceeded max refinement iterations
        if state.research_iteration >= state.max_refinement_iterations:
            # Exceeded limit - return message and force selection
            message = (
                f"You've already refined your search {state.research_iteration} times. "
                "Please make a selection from the current results."
            )
            turns = state.conversation_turns + [ConversationTurn(role="assistant", content=message)]
            state = state.model_copy(update={"conversation_turns": turns})

            # Return current research results for selection
            research = state.research or ResearchState()
            if state.phase == "selecting_attractions":
                attractions = [item for item in research.attractions if not item.get("error")]
                if attractions:
                    return state, [self._build_selection_interrupt("attractions", attractions)]
            elif state.phase == "selecting_restaurants":
                restaurants = [item for item in research.dining if not item.get("error")]
                if restaurants:
                    return state, [self._build_selection_interrupt("restaurants", restaurants)]

            # Fallback - move to next phase
            return self._after_attractions_selected(state)

        # Extract refinement criteria
        additional_attractions = criteria.get("additional_attractions", [])
        additional_restaurants = criteria.get("additional_restaurants", [])

        # Build focus dict for research agent
        focus: Dict[str, List[str]] = {}
        if additional_attractions:
            focus["attractions"] = additional_attractions if isinstance(additional_attractions, list) else [additional_attractions]
        if additional_restaurants:
            focus["dining"] = additional_restaurants if isinstance(additional_restaurants, list) else [additional_restaurants]

        # Record refinement in history
        refinement_record = {
            "iteration": state.research_iteration + 1,
            "criteria": criteria,
            "focus": focus,
        }

        # Update state for refinement
        state = state.model_copy(update={
            "phase": "refining_research",
            "research_iteration": state.research_iteration + 1,
            "research_refinement_history": state.research_refinement_history + [refinement_record],
        })

        # Re-run research with focus
        return self._run_research(state, focus=focus)

    def _save_user_profile(self, fields: dict, thread_id: str):
        """Save the gathered user preferences into a JSON file."""
        # Convert your raw fields into human-readable format
        profile = {
            "Traveler Profile": {
                "Thread ID": thread_id,
                "Generated At": datetime.utcnow().isoformat(),
                "Name": fields.get("name"),
                "Destination City": fields.get("destination_city")
                or fields.get("city"),
                "Travel Days": fields.get("travel_days"),
                "Start Date": fields.get("start_date"),
                "Budget USD": fields.get("budget_usd") or fields.get("budget"),
                "Num People": fields.get("num_people"),
                "Kids": fields.get("kids"),
                "Activity Pref": fields.get("activity_pref")
                or fields.get("activities"),
                "Need Car Rental": fields.get("need_car_rental"),
                "Hotel Room Pref": fields.get("hotel_room_pref"),
                "Cuisine Pref": fields.get("cuisine_pref"),
            }
        }
        folder = "user_profiles"
        os.makedirs(folder, exist_ok=True)

        # Choose filename (thread_id makes it unique)
        filename = os.path.join(folder, f"user_profile_{thread_id}.json")

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

        print(f"[TravelPlanner] Saved user profile to: {filename}")

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
        self, state: TravelPlannerState, focus: Optional[Dict[str, List[str]]] = None
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        preferences = dict(state.preferences.fields)

        try:
            research_results = self.research_agent.research(preferences, focus=focus)
        except Exception as exc:  # pragma: no cover - defensive logging
            research_results = {"error": str(exc)}

        research_state = ResearchState.from_raw(research_results)

        # Customize message based on whether this is initial research or refinement
        if focus and state.research_iteration > 0:
            message = (
                f"I've refined the search based on your preferences. "
                f"Here are updated results (refinement #{state.research_iteration})."
            )
        else:
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

        # Save itinerary JSON
        try:
            self._save_itinerary(itinerary, state.thread_id)
        except Exception:
            pass

        # Validate plan against profile
        try:
            profile_fields = dict(state.preferences.fields) if state.preferences else {}
            issues = self._validate_plan(profile_fields, itinerary, budget_summary)
            if issues:
                # add a short assistant turn summarizing the top issues
                summary = "Validation issues detected: " + "; ".join(issues[:3])
                turns = state.conversation_turns + [ConversationTurn(role="assistant", content=summary)]
                state = state.model_copy(update={"conversation_turns": turns})
        except Exception as e:
            # don't crash workflow on validation errors
            print(f"[TravelPlanner] Validation failed: {e}")

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

    def _save_itinerary(self, itinerary: Dict[str, Any], thread_id: str) -> str:
        """Save the generated itinerary to a JSON file and return filename."""
        folder = "generated_plans"
        os.makedirs(folder, exist_ok=True)

        filename = os.path.join(folder, f"itinerary_{thread_id}.json")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(itinerary or {}, f, indent=2, ensure_ascii=False)
            print(f"[TravelPlanner] Saved itinerary to: {filename}")
        except Exception as e:
            print(f"[TravelPlanner] Failed to save itinerary: {e}")
        return filename


    def _validate_plan(
        self,
        profile_fields: Dict[str, Any],
        itinerary: Optional[Dict[str, Any]],
        budget_summary: Optional[Dict[str, Any]],
    ) -> List[str]:
        """
        Robust validation checks for contradictions between user profile and generated itinerary.
        Returns a list of human-readable issue strings (empty list == no issues found).
        This version normalizes values so .lower() is only called on strings.
        """
        issues: List[str] = []

        if not profile_fields:
            issues.append("No user profile available to validate against.")
            return issues

        # ---- Helpers ----
        def normalize_value(v: Any) -> Optional[str]:
            """Turn common incoming types into a simple string (or None)."""
            if v is None:
                return None
            if isinstance(v, str):
                return v.strip()
            if isinstance(v, (int, float)):
                return str(v)
            if isinstance(v, list) and v:
                # take the first item if it's a list
                first = v[0]
                if isinstance(first, (str, int, float)):
                    return str(first).strip()
                # otherwise try stringify
                return str(first)
            # fallback to string representation
            try:
                return str(v).strip()
            except Exception:
                return None

        def safe_lower(v: Any) -> str:
            s = normalize_value(v)
            return s.lower() if isinstance(s, str) else ""

        def parse_date(s: Optional[str]) -> Optional[datetime]:
            if not s:
                return None
            s_norm = normalize_value(s)
            if not s_norm:
                return None
            # try common formats
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    return datetime.strptime(s_norm, fmt)
                except Exception:
                    continue
            # try ISO parse fallback
            try:
                return datetime.fromisoformat(s_norm)
            except Exception:
                # final fallback: try to pull first 10 chars (date part)
                try:
                    return datetime.strptime(s_norm[:10], "%Y-%m-%d")
                except Exception:
                    return None

        # Normalize profile fields to simple map of strings for repeated access
        normalized = {k: normalize_value(v) for k, v in profile_fields.items()}

        # --- Check 1: Start date in profile vs itinerary first day ---
        profile_start = parse_date(
            normalized.get("start_date") or normalized.get("Start Date")
        )
        itinerary_dates: List[datetime] = []
        if itinerary:
            days = (
                itinerary.get("days")
                or itinerary.get("itinerary")
                or itinerary.get("schedule")
                or []
            )
            if isinstance(days, dict):
                # maybe single-day encoded as dict
                days = [days]
            for d in days:
                if isinstance(d, dict):
                    date_str = normalize_value(
                        d.get("date") or d.get("day_date") or d.get("day")
                    )
                    dt = parse_date(date_str)
                    if dt:
                        itinerary_dates.append(dt)

        if profile_start and itinerary_dates:
            first_itin = min(itinerary_dates)
            if abs((first_itin.date() - profile_start.date()).days) > 1:
                issues.append(
                    f"Profile start date ({profile_start.date()}) does not match itinerary first day ({first_itin.date()})."
                )

        # --- Check 2: Travel days vs itinerary length ---
        try:
            profile_days = int(
                normalized.get("travel_days") or normalized.get("Travel Days") or 0
            )
        except Exception:
            profile_days = 0
        if profile_days and itinerary_dates:
            itin_span_days = (
                max(itinerary_dates).date() - min(itinerary_dates).date()
            ).days + 1
            if profile_days != itin_span_days:
                issues.append(
                    f"Profile travel days ({profile_days}) ≠ itinerary span ({itin_span_days})."
                )

        # --- Check 3: Budget vs estimated cost (if available) ---
        try:
            profile_budget = float(
                normalized.get("budget_usd")
                or normalized.get("Budget Usd")
                or normalized.get("budget")
                or 0
            )
        except Exception:
            profile_budget = 0.0
        if profile_budget and budget_summary:
            total = None
            for k in ("total", "total_cost", "estimated_total", "total_usd", "amount"):
                if budget_summary.get(k) is not None:
                    try:
                        total_val = budget_summary.get(k)
                        # if it's a list, take first item
                        if isinstance(total_val, list) and total_val:
                            total_val = total_val[0]
                        total = float(total_val)
                        break
                    except Exception:
                        continue
            if total is not None and total > 0 and profile_budget > 0:
                if total > profile_budget * 1.05:  # 5% slack
                    issues.append(
                        f"Estimated trip cost ({total}) exceeds profile budget ({profile_budget})."
                    )

        # --- Check 4: Car rental requirement vs itinerary transport modes ---
        need_car = safe_lower(
            normalized.get("need_car_rental") or normalized.get("Need Car Rental")
        )
        if need_car in ("yes", "true", "1", "y"):
            transport_used = False
            if itinerary:
                try:
                    raw = json.dumps(itinerary).lower()
                    if any(
                        token in raw
                        for token in (
                            "car",
                            "drive",
                            "rental",
                            "pickup",
                            "rent a car",
                            "rent-car",
                        )
                    ):
                        transport_used = True
                except Exception:
                    transport_used = False
            if not transport_used:
                issues.append(
                    "Profile requests a car rental but the itinerary contains no car/drive segments."
                )

        # --- Check 5: Kids constraints (heuristic) ---
        kids = safe_lower(normalized.get("kids") or normalized.get("Kids"))
        if kids in ("yes", "true", "1", "y"):
            if itinerary:
                try:
                    raw = json.dumps(itinerary).lower()
                    # basic heuristic: if nightlife-related keywords are dominant, flag
                    if ("nightclub" in raw or "bar" in raw) and not any(
                        k in raw for k in ("park", "museum", "family", "children", "zoo")
                    ):
                        issues.append(
                            "Profile indicates children but itinerary seems focused on adult nightlife or lacks family-friendly activities."
                        )
                except Exception:
                    pass

        # --- Check 6: Hotel room preference (soft check) ---
        room_pref = normalize_value(
            normalized.get("hotel_room_pref") or normalized.get("Hotel Room Pref")
        )
        if room_pref and itinerary:
            try:
                raw = json.dumps(itinerary).lower()
                # if certain explicit room types expected (king/queen/twin) but not found: warn
                if any(
                    token in room_pref.lower()
                    for token in ("king", "queen", "twin", "double", "single")
                ):
                    if room_pref.lower() not in raw:
                        issues.append(
                            f"Hotel room preference '{room_pref}' not mentioned in itinerary lodging details (verify hotel booking)."
                        )
            except Exception:
                pass

        return issues


# ----------------------------------------------------------------------
# Smoke test helpers
# ----------------------------------------------------------------------


# @dataclass
# class _StubAgentReply:
#     content: str


# class _StubChatAgent:
#     """Deterministic chat agent used in the smoke test."""

#     def __init__(self) -> None:
#         self._called = False

#     def collect_info(self, message: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
#         state = dict(state or {})
#         if not self._called:
#             reply = "Tell me about your travel plans."
#         else:
#             reply = "Wonderful! I'll research options now."
#             state.update(
#                 {
#                     "destination_city": "Seattle",
#                     "travel_days": 3,
#                     "start_date": "2024-07-01",
#                     "budget_usd": 2500,
#                     "num_people": 2,
#                     "kids": "no",
#                     "activity_pref": "outdoor",
#                     "need_car_rental": "no",
#                     "hotel_room_pref": "king bed",
#                     "cuisine_pref": "seafood",
#                 }
#             )
#         self._called = True
#         return {
#             "stream": [_StubAgentReply(reply)],
#             "state": state,
#             "missing_fields": [],
#             "complete": True,
#         }


# class _StubResearchAgent:
#     def research(self, state: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - simple stub
#         return {
#             "attractions": [
#                 {
#                     "id": "attr_1",
#                     "name": "Space Needle",
#                     "address": "400 Broad St",
#                     "rating": 4.7,
#                     "review_count": 1234,
#                     "coord": {"lat": 47.6205, "lng": -122.3493},
#                 },
#                 {
#                     "id": "attr_2",
#                     "name": "Pike Place Market",
#                     "address": "85 Pike St",
#                     "rating": 4.8,
#                     "review_count": 5230,
#                     "coord": {"lat": 47.6097, "lng": -122.3425},
#                 },
#             ],
#             "dining": [
#                 {
#                     "id": "rest_1",
#                     "name": "Elliott's Oyster House",
#                     "address": "1201 Alaskan Way",
#                     "rating": 4.5,
#                     "review_count": 3487,
#                     "price_level": 3,
#                     "coord": {"lat": 47.6053, "lng": -122.3405},
#                 }
#             ],
#         }


# class _StubItineraryAgent:
#     def build_itinerary(self, preferences: Dict[str, Any], attractions: Sequence[Dict[str, Any]], research: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - simple stub
#         return {
#             "days": [
#                 {
#                     "day": 1,
#                     "stops": [
#                         {
#                             "name": attractions[0]["name"],
#                             "coord": attractions[0].get("coord"),
#                             "streetview_url": "https://www.google.com/maps",
#                         }
#                     ],
#                 }
#             ]
#         }

#     def build_planning_context(
#         self,
#         *,
#         user_state: Dict[str, Any],
#         research_results: Dict[str, Any],
#         itinerary: Optional[Dict[str, Any]],
#         budget: Optional[Dict[str, Any]],
#         selected_attractions: Optional[Sequence[Dict[str, Any]]],
#     ) -> str:  # pragma: no cover - simple stub
#         return "Enjoy Seattle!"


# class _StubBudgetAgent:
#     def compute_budget(
#         self,
#         *,
#         preferences: Dict[str, Any],
#         research: Dict[str, Any],
#         itinerary: Optional[Dict[str, Any]],
#     ) -> Dict[str, Any]:  # pragma: no cover - simple stub
#         return {"currency": "USD", "expected": 2100}


# def run_smoke_test() -> None:
#     """Run a deterministic smoke test to validate the workflow wiring."""

#     workflow = TravelPlannerWorkflow(
#         chat_agent=_StubChatAgent(),
#         research_agent=_StubResearchAgent(),
#         itinerary_agent=_StubItineraryAgent(),
#         budget_agent=_StubBudgetAgent(),
#     )

#     state = workflow.initial_state("smoke-thread")
#     state, _ = workflow.start(state)

#     state, interrupts = workflow.handle_user_message(state, "Let's plan a Seattle getaway")
#     assert interrupts, "Expected attraction selection interrupt"
#     assert interrupts[0]["type"] == "select_attractions"

#     state, interrupts = workflow.handle_interrupt(state, {"selected_indices": [0]})
#     assert interrupts, "Expected restaurant selection interrupt"
#     assert interrupts[0]["type"] == "select_restaurants"

#     state, interrupts = workflow.handle_interrupt(state, {"selected_indices": [0]})
#     assert state.phase == "complete"
#     assert not interrupts

#     print("Smoke test passed – workflow completed successfully.")


# def run_interactive_test() -> None:
#     """Run an interactive smoke test where you can chat with the workflow.

#     This simulates the full travel planning experience:
#     - Chat with the assistant to provide preferences
#     - System researches attractions/restaurants
#     - You select your favorites interactively
#     - System generates itinerary and budget
#     """
#     import json

#     workflow = TravelPlannerWorkflow(
#         chat_agent=_StubChatAgent(),
#         research_agent=_StubResearchAgent(),
#         itinerary_agent=_StubItineraryAgent(),
#         budget_agent=_StubBudgetAgent(),
#     )

#     print("=" * 70)
#     print("🌍 INTERACTIVE TRAVEL PLANNER SMOKE TEST")
#     print("=" * 70)
#     print("\nThis is a simulated workflow using stub agents (no real API calls).")
#     print("You can chat naturally and make selections to test the workflow.\n")

#     state = workflow.initial_state("interactive-test-thread")
#     state, _ = workflow.start(state)

#     # Show initial greeting
#     last_assistant_msg = state.conversation_turns[-1].content
#     print(f"\n🤖 Assistant: {last_assistant_msg}\n")

#     # Phase 1: Collect preferences through conversation
#     while state.phase == "collecting":
#         user_input = input("👤 You: ").strip()
#         if not user_input:
#             continue
#         if user_input.lower() in ["quit", "exit", "q"]:
#             print("\nExiting interactive test.")
#             return

#         state, interrupts = workflow.handle_user_message(state, user_input)

#         # Show assistant response
#         last_turn = state.conversation_turns[-1]
#         if last_turn.role == "assistant":
#             print(f"\n🤖 Assistant: {last_turn.content}\n")

#         # Check if we got interrupts (research completed)
#         if interrupts:
#             break

#     # Phase 2: Handle attraction selection
#     if state.phase == "selecting_attractions" and state.research:
#         print("\n" + "=" * 70)
#         print("🏛️  ATTRACTION SELECTION")
#         print("=" * 70)

#         attractions = state.research.attractions
#         print(f"\nFound {len(attractions)} attractions:\n")

#         for idx, attr in enumerate(attractions):
#             print(f"  [{idx}] {attr['name']}")
#             print(f"      📍 {attr.get('address', 'N/A')}")
#             print(f"      ⭐ {attr.get('rating', 'N/A')} ({attr.get('review_count', 0)} reviews)")
#             print()

#         while True:
#             selection = input(f"👤 Select attractions (e.g., '0,1' or '0 1'): ").strip()
#             if selection.lower() in ["quit", "exit", "q"]:
#                 print("\nExiting interactive test.")
#                 return

#             # Parse selection
#             try:
#                 if "," in selection:
#                     indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
#                 else:
#                     indices = [int(x.strip()) for x in selection.split() if x.strip()]

#                 state, interrupts = workflow.handle_interrupt(
#                     state, {"selected_indices": indices}
#                 )

#                 print(f"\n✅ Selected {len(state.selected_attractions)} attractions:")
#                 for attr in state.selected_attractions:
#                     print(f"   • {attr['name']}")
#                 break
#             except (ValueError, IndexError) as e:
#                 print(f"❌ Invalid selection. Please try again (e.g., '0,1')\n")

#     # Phase 3: Handle restaurant selection
#     if state.phase == "selecting_restaurants" and state.research:
#         print("\n" + "=" * 70)
#         print("🍽️  RESTAURANT SELECTION")
#         print("=" * 70)

#         # Show assistant message
#         last_turn = state.conversation_turns[-1]
#         if last_turn.role == "assistant":
#             print(f"\n🤖 Assistant: {last_turn.content}\n")

#         restaurants = state.research.dining
#         print(f"\nFound {len(restaurants)} restaurants:\n")

#         for idx, rest in enumerate(restaurants):
#             print(f"  [{idx}] {rest['name']}")
#             print(f"      📍 {rest.get('address', 'N/A')}")
#             print(f"      ⭐ {rest.get('rating', 'N/A')} ({rest.get('review_count', 0)} reviews)")
#             price = rest.get('price_level')
#             if price:
#                 print(f"      💰 {'$' * price}")
#             print()

#         while True:
#             selection = input(f"👤 Select restaurants (e.g., '0' or '0,1'): ").strip()
#             if selection.lower() in ["quit", "exit", "q"]:
#                 print("\nExiting interactive test.")
#                 return

#             try:
#                 if "," in selection:
#                     indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
#                 else:
#                     indices = [int(x.strip()) for x in selection.split() if x.strip()]

#                 state, interrupts = workflow.handle_interrupt(
#                     state, {"selected_indices": indices}
#                 )

#                 print(f"\n✅ Selected {len(state.selected_restaurants)} restaurants:")
#                 for rest in state.selected_restaurants:
#                     print(f"   • {rest['name']}")
#                 break
#             except (ValueError, IndexError) as e:
#                 print(f"❌ Invalid selection. Please try again (e.g., '0')\n")

#     # Phase 4: Show final results
#     if state.phase == "complete":
#         print("\n" + "=" * 70)
#         print("✨ FINAL ITINERARY")
#         print("=" * 70)

#         # Show assistant message
#         last_turn = state.conversation_turns[-1]
#         if last_turn.role == "assistant":
#             print(f"\n🤖 Assistant: {last_turn.content}\n")

#         # Show preferences
#         print("📋 Your Preferences:")
#         prefs = state.preferences.fields
#         for key, value in prefs.items():
#             formatted_key = key.replace("_", " ").title()
#             print(f"   • {formatted_key}: {value}")

#         # Show itinerary
#         if state.itinerary:
#             print("\n📅 Itinerary:")
#             days = state.itinerary.get("days", [])
#             for day_info in days:
#                 day_num = day_info.get("day", "?")
#                 print(f"\n   Day {day_num}:")
#                 for stop in day_info.get("stops", []):
#                     print(f"      • {stop.get('name', 'Unknown')}")

#         # Show budget
#         if state.budget:
#             print(f"\n💰 Budget Estimate:")
#             budget = state.budget
#             print(f"   {budget.get('currency', 'USD')} {budget.get('expected', 0):,.2f}")

#         # Show planning context
#         if state.planning_context:
#             print(f"\n💬 Planning Context:")
#             print(f"   {state.planning_context}")

#         print("\n" + "=" * 70)
#         print("✅ WORKFLOW COMPLETE!")
#         print("=" * 70)

#         # Show conversation history
#         print(f"\n📜 Conversation History ({len(state.conversation_turns)} turns):")
#         for i, turn in enumerate(state.conversation_turns, 1):
#             role_icon = "🤖" if turn.role == "assistant" else "👤"
#             print(f"   {i}. {role_icon} {turn.role.title()}: {turn.content[:60]}...")

#         print()


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Travel planner workflow utilities")
#     parser.add_argument("--smoke", action="store_true", help="Run a smoke test against stub agents")
#     parser.add_argument("--interactive", action="store_true", help="Run an interactive smoke test")
#     args = parser.parse_args()

#     if args.smoke:
#         run_smoke_test()
#     elif args.interactive:
#         run_interactive_test()
#     else:
#         print("Run with --smoke to execute the automated workflow smoke test.")
#         print("Run with --interactive to chat with the workflow interactively.")
