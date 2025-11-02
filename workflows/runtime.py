from __future__ import annotations

from collections.abc import Iterable as IterableCollection
from typing import Any, Dict, Iterable, Optional, Tuple

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents.budget_agent import BudgetAgent
from agents.chat_agent import ChatAgent
from agents.itinerary_agent import ItineraryAgent
from agents.research_agent import ResearchAgent
from workflows.state import TravelPlannerState
from workflows.travel_graph import build_travel_planner_graph


class TravelPlannerRuntime:
    """Runtime helper that owns agent instances and LangGraph execution."""

    def __init__(
        self,
        *,
        chat_agent: Optional[ChatAgent] = None,
        research_agent: Optional[ResearchAgent] = None,
        itinerary_agent: Optional[ItineraryAgent] = None,
        budget_agent: Optional[BudgetAgent] = None,
    ) -> None:
        self.chat_agent = chat_agent or ChatAgent()
        self.research_agent = research_agent or ResearchAgent()
        self.itinerary_agent = itinerary_agent or ItineraryAgent()
        self.budget_agent = budget_agent or BudgetAgent()

        self.checkpointer = MemorySaver()
        self.graph = build_travel_planner_graph(
            self.chat_agent,
            self.research_agent,
            self.itinerary_agent,
            self.budget_agent,
            checkpointer=self.checkpointer,
        )

    async def run_turn(
        self,
        state: Optional[TravelPlannerState] = None,
        user_input: Optional[Any] = None,
    ) -> Tuple[TravelPlannerState, Iterable[Any]]:
        """Run a single turn of the workflow and return updated state + interrupts."""

        if state is None:
            state = TravelPlannerState()

        config = {"configurable": {"thread_id": state.thread_id}}

        invocation = None
        phase = state.phase

        if phase in {
            "awaiting_attraction_selection",
            "awaiting_itinerary_approval",
            "awaiting_budget_confirmation",
        }:
            resume_payload = self._build_resume_payload(phase, user_input)
            invocation = Command(resume=[resume_payload])
        else:
            if user_input is None and not state.conversation_turns:
                state.pending_user_input = ""
                state.phase = "collecting_preferences"
            elif isinstance(user_input, str):
                state.push_user_turn(user_input)
                state.phase = "collecting_preferences"
            elif isinstance(user_input, dict):
                # Allow direct state updates when resuming without interrupt
                if "selected_attractions" in user_input:
                    state.selected_attractions = list(user_input["selected_attractions"])
                    state.phase = "building_itinerary"
                if "itinerary_approved" in user_input:
                    state.itinerary_approved = bool(user_input["itinerary_approved"])
                    state.phase = "budgeting" if state.itinerary_approved else state.phase
                if "budget_confirmed" in user_input:
                    state.budget_confirmed = bool(user_input["budget_confirmed"])
                    state.phase = "complete" if state.budget_confirmed else state.phase

            invocation = state.model_dump()

        result: Dict[str, Any]
        if hasattr(self.graph, "ainvoke"):
            result = await self.graph.ainvoke(invocation, config=config)
        else:  # pragma: no cover - fallback for sync graphs
            result = self.graph.invoke(invocation, config=config)

        interrupts = result.pop("__interrupt__", [])
        new_state = TravelPlannerState(**result)
        return new_state, interrupts

    def _build_resume_payload(self, phase: str, user_input: Optional[Any]) -> Dict[str, Any]:
        if phase == "awaiting_attraction_selection":
            if user_input is None:
                raise ValueError("Selection payload required to resume attraction step.")
            if isinstance(user_input, dict):
                return user_input
            if isinstance(user_input, IterableCollection) and not isinstance(user_input, (str, bytes)):
                return {"selected_indices": list(user_input)}
            if isinstance(user_input, str):
                indices = [int(part.strip()) for part in user_input.split(",") if part.strip().isdigit()]
                return {"selected_indices": indices}
            raise ValueError("Unsupported selection payload type.")

        if phase == "awaiting_itinerary_approval":
            decision = self._boolean_from_input(user_input)
            return {"approved": decision}

        if phase == "awaiting_budget_confirmation":
            decision = self._boolean_from_input(user_input)
            return {"confirmed": decision}

        raise ValueError(f"Unsupported resume phase: {phase}")

    @staticmethod
    def _boolean_from_input(value: Optional[Any]) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in {"y", "yes", "ok", "approve", "approved", "confirm", "confirmed"}
        if isinstance(value, dict):
            for key in ("approved", "confirm", "confirmed", "itinerary_approved", "budget_confirmed"):
                if key in value:
                    return bool(value[key])
        raise ValueError("Unable to interpret confirmation payload.")

