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
import json
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
from workflows.schemas import UserPreferences, ItineraryOutput, BudgetOutput


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


class TravelPlannerOrchestrator:
    """Orchestrate the travel-planning workflow with critic loop for requirement validation."""

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
            return self._critic_loop(state)

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
        
        try:
            # ResearchAgent now returns ResearchOutput schema
            research_state = ResearchState.from_raw(research_results)

            # Check if research failed completely (only fail if we have NO attractions AND NO dining)
            research_error = None
            if isinstance(research_results, dict) and research_results.get("error"):
                research_error = research_results.get("error")
            elif research_state.raw and research_state.raw.get("error"):
                research_error = research_state.raw.get("error")
            
            # Filter out error items to check if we have any valid results
            valid_attractions = [item for item in research_state.attractions if not item.get("error")]
            valid_dining = [item for item in research_state.dining if not item.get("error")]
            
            # Only treat as failure if we have NO valid attractions AND NO valid dining
            # (Weather/hotels/flights failures are acceptable - we can still plan with attractions/dining)
            if research_error and len(valid_attractions) == 0 and len(valid_dining) == 0:
                error_message = (
                    f"I encountered an issue while researching your destination: {research_error}. "
                    "Please check your API keys or try again later."
                )
                turns = state.conversation_turns + [ConversationTurn(role="assistant", content=error_message)]
                state = state.model_copy(update={
                    "research": research_state,
                    "conversation_turns": turns,
                    "phase": "collecting",  # Stay in collecting phase so user can retry
                })
                return state, []

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
            
            # Check if all attractions failed (all have errors)
            if len(research_state.attractions) > 0 and len(attractions) == 0:
                error_messages = [item.get("error") for item in research_state.attractions if item.get("error")]
                error_summary = error_messages[0] if error_messages else "Failed to fetch attractions"
                error_message = (
                    f"I couldn't find any attractions for your destination. "
                    f"Error: {error_summary}. Please check your API keys or try a different destination."
                )
                turns = state.conversation_turns + [ConversationTurn(role="assistant", content=error_message)]
                state = state.model_copy(update={
                    "research": research_state,
                    "conversation_turns": turns,
                    "phase": "collecting",  # Stay in collecting phase so user can retry
                })
                return state, []
            
            if attractions:
                state = state.model_copy(update={"phase": "selecting_attractions"})
                interrupt = self._build_selection_interrupt("attractions", attractions)
                return state, [interrupt]

            # No attractions to choose. Move straight to restaurants / itinerary.
            state = state.model_copy(update={
                "selected_attractions": [],
                "phase": "selecting_restaurants",
            })
            return self._after_attractions_selected(state)
        except Exception as e:
            # Return error state
            error_message = f"I encountered an error while processing research results: {e}"
            turns = state.conversation_turns + [ConversationTurn(role="assistant", content=error_message)]
            return state.model_copy(update={
                "conversation_turns": turns,
                "phase": "collecting",
            }), []

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
            interrupt = self._build_selection_interrupt("restaurants", restaurants)
            return state, [interrupt]

        state = state.model_copy(update={
            "selected_restaurants": [],
            "phase": "building_itinerary",
        })
        return self._critic_loop(state)

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

    def _critic_loop(
        self, state: TravelPlannerState
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """
        Critic loop: Generate itinerary, evaluate against requirements, iterate if needed.
        Maximum 3 iterations before giving up and explaining failures.
        """
        research_dict = state.research.raw if state.research else {}
        preferences_dict = dict(state.preferences.fields)
        
        # Convert preferences to UserPreferences schema
        try:
            user_preferences = UserPreferences(**preferences_dict)
        except Exception:
            # Fallback: create with minimal validation
            user_preferences = UserPreferences.model_validate(preferences_dict)
        
        attractions = state.selected_attractions or (
            (state.research.attractions if state.research else [])
        )
        
        max_iterations = state.max_critic_iterations
        last_evaluation = None
        requirement_explanation = None
        
        for iteration in range(max_iterations):
            # Generate itinerary with feedback from previous iteration (if any)
            itinerary: Optional[ItineraryOutput] = None
            try:
                if attractions:
                    itinerary = self.itinerary_agent.build_itinerary(
                        preferences=preferences_dict,
                        attractions=attractions,
                        research=research_dict,
                        feedback=last_evaluation,  # Pass previous evaluation as feedback
                    )
            except Exception as exc:  # pragma: no cover - defensive logging
                itinerary = None
                # Create error itinerary
                itinerary_dict = {"error": str(exc)}
            else:
                itinerary_dict = itinerary.to_dict() if itinerary else None
            
            # Compute budget
            budget: Optional[BudgetOutput] = None
            try:
                budget = self.budget_agent.compute_budget(
                    preferences=preferences_dict,
                    research=research_dict,
                    itinerary=itinerary_dict,
                )
            except Exception:
                budget = None
            
            # Evaluate requirements (critic functionality)
            if itinerary and budget:
                try:
                    evaluation = self.budget_agent.evaluate_requirements(
                        preferences=user_preferences,
                        itinerary=itinerary,
                        budget=budget,
                    )
                    last_evaluation = evaluation
                    
                    if evaluation.requirements_met:
                        # Requirements met! Generate final plan
                        return self._create_final_state(
                            state, itinerary_dict, budget, user_preferences, research_dict, attractions
                        )
                    
                    # If last iteration, get explanation
                    if iteration == max_iterations - 1:
                        try:
                            explanation_result = self.budget_agent.explain_failure(
                                evaluation, preferences=user_preferences
                            )
                            requirement_explanation = explanation_result.explanation
                        except Exception:
                            requirement_explanation = (
                                "Unfortunately, the itinerary does not meet all your requirements. "
                                "Please consider adjusting your preferences or budget."
                            )
                        break
                    
                    # Otherwise, continue to next iteration with feedback
                    # (last_evaluation will be passed as feedback to ItineraryAgent in next iteration)
                    continue
                except Exception:
                    # If evaluation fails, break and use current itinerary
                    break
            else:
                # If we can't generate itinerary or budget, break
                break
        
        # If we get here, either requirements weren't met or there was an error
        # Create final state with explanation
        return self._create_final_state(
            state, itinerary_dict, budget, user_preferences, research_dict, attractions,
            last_evaluation=last_evaluation,
            requirement_explanation=requirement_explanation,
        )
    
    def _create_final_state(
        self,
        state: TravelPlannerState,
        itinerary_dict: Optional[Dict[str, Any]],
        budget: Optional[BudgetOutput],
        user_preferences: UserPreferences,
        research_dict: Dict[str, Any],
        attractions: List[Dict[str, Any]],
        last_evaluation: Optional[Any] = None,
        requirement_explanation: Optional[str] = None,
    ) -> Tuple[TravelPlannerState, List[SelectionInterrupt]]:
        """Create final state with itinerary, budget, and planning context."""
        planning_context: Optional[str] = None
        budget_dict = budget.to_dict() if budget else None
        
        try:
            planning_context = self.itinerary_agent.build_planning_context(
                user_state=user_preferences.to_dict(),
                research_results=research_dict,
                itinerary=itinerary_dict,
                budget=budget_dict,
                selected_attractions=attractions,
            )
        except Exception:
            planning_context = None
        
        message = "Here's a draft itinerary based on everything you've shared."
        if requirement_explanation:
            message += f"\n\n{requirement_explanation}"
        
        turns = state.conversation_turns + [ConversationTurn(role="assistant", content=message)]
        
        state = state.model_copy(update={
            "itinerary": itinerary_dict,
            "planning_context": planning_context,
            "budget": budget_dict,
            "conversation_turns": turns,
            "phase": "complete",
            "last_critic_evaluation": last_evaluation,
            "requirement_explanation": requirement_explanation,
            "critic_iterations": state.critic_iterations + 1,
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
