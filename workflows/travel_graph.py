from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from workflows.state import PreferencesState, TravelPlannerState


def _stream_to_text(stream: Any) -> str:
    if stream is None:
        return ""

    chunks: List[str] = []
    try:
        for chunk in stream:
            if hasattr(chunk, "content"):
                content = chunk.content
            else:
                content = getattr(chunk, "text", "")

            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("content")
                        if text:
                            chunks.append(str(text))
                    elif isinstance(part, str):
                        chunks.append(part)
            elif isinstance(content, str):
                chunks.append(content)
    except Exception:
        return ""

    return "".join(chunks).strip()


def _format_attraction_summary(attractions: Sequence[Dict[str, Any]]) -> str:
    if not attractions:
        return ""

    lines = ["Here are a few attractions you might enjoy:"]
    for idx, item in enumerate(attractions[:6], 1):
        name = item.get("name", "Attraction")
        rating = item.get("rating")
        rating_text = f" – {rating}⭐" if rating else ""
        lines.append(f"{idx}. {name}{rating_text}")
    lines.append("Let me know which ones you'd like to include.")
    return "\n".join(lines)


def _format_itinerary_summary(itinerary: Dict[str, Any]) -> str:
    days = itinerary.get("days") or []
    if not days:
        return ""

    lines = ["Here's a draft itinerary:"]
    for day in days:
        day_label = day.get("day") or len(lines)
        stops = day.get("stops") or []
        summary = ", ".join(stop.get("name", "Attraction") for stop in stops) or "Flex day"
        lines.append(f"Day {day_label}: {summary}")
    lines.append("Does this schedule look good to you?")
    return "\n".join(lines)


def _format_budget_summary(budget: Dict[str, Any]) -> str:
    if not budget:
        return ""

    expected = budget.get("expected")
    low = budget.get("low")
    high = budget.get("high")
    currency = budget.get("currency", "USD")
    if expected is None:
        return ""

    lines = ["Here's the estimated budget:"]
    lines.append(f"Expected: {currency} {expected}")
    if low is not None and high is not None:
        lines.append(f"Range: {currency} {low} – {currency} {high}")
    lines.append("Let me know if you'd like to adjust anything.")
    return "\n".join(lines)


def build_travel_planner_graph(
    chat_agent,
    research_agent,
    itinerary_agent,
    budget_agent,
    *,
    checkpointer=None,
):
    builder = StateGraph(TravelPlannerState)

    def route(state: TravelPlannerState) -> Dict[str, Any]:
        return state.model_dump()

    def collect_preferences(state: TravelPlannerState) -> Dict[str, Any]:
        user_input = state.pending_user_input
        if user_input is None and state.conversation_turns:
            state.phase = "awaiting_user_input"
            return state.model_dump()

        input_text = user_input or ""
        result = chat_agent.collect_info(input_text, state.preferences.fields.copy())
        response_text = _stream_to_text(result.get("stream"))
        if response_text:
            chat_agent.conversation_history.append(AIMessage(content=response_text))
            state.push_agent_turn(response_text)
        if result.get("error") and not response_text:
            state.push_agent_turn(f"⚠️ {result['error']}")

        prefs = PreferencesState(
            fields=result.get("state", state.preferences.fields),
            missing_fields=result.get("missing_fields", []),
            complete=bool(result.get("complete")),
        )
        state.preferences = prefs
        state.pending_user_input = None
        state.phase = "researching" if prefs.complete else "awaiting_user_input"
        return state.model_dump()

    def run_research(state: TravelPlannerState) -> Dict[str, Any]:
        if not state.preferences.complete:
            state.phase = "awaiting_user_input"
            return state.model_dump()

        results = research_agent.research(state.preferences.fields)
        state.research = results or {}
        state.candidate_attractions = list((results or {}).get("attractions") or [])
        state.selected_attractions = []

        summary = _format_attraction_summary(state.candidate_attractions)
        if summary:
            state.push_agent_turn(summary)

        state.phase = "awaiting_attraction_selection" if state.candidate_attractions else "building_itinerary"
        return state.model_dump()

    def await_attraction_selection(state: TravelPlannerState) -> Dict[str, Any]:
        if state.selected_attractions:
            state.phase = "building_itinerary"
            return state.model_dump()

        if not state.candidate_attractions:
            state.phase = "building_itinerary"
            return state.model_dump()

        selection = interrupt(
            {
                "type": "select_attractions",
                "options": state.candidate_attractions,
            }
        )

        if isinstance(selection, dict):
            if "selected_attractions" in selection:
                chosen = selection["selected_attractions"]
            elif "selected_indices" in selection:
                indices = [i for i in selection["selected_indices"] if isinstance(i, int)]
                chosen = [
                    state.candidate_attractions[i]
                    for i in indices
                    if 0 <= i < len(state.candidate_attractions)
                ]
            else:
                chosen = []
        elif isinstance(selection, Iterable):
            chosen = list(selection)
        else:
            chosen = []

        if chosen:
            state.selected_attractions = list(chosen)
            state.phase = "building_itinerary"
        return state.model_dump()

    def build_itinerary(state: TravelPlannerState) -> Dict[str, Any]:
        attractions = state.selected_attractions or state.candidate_attractions
        if not attractions:
            state.phase = "awaiting_user_input"
            return state.model_dump()

        itinerary = itinerary_agent.build_itinerary(state.preferences.fields, attractions, state.research)
        state.itinerary = itinerary or {}
        state.itinerary_approved = False

        summary = _format_itinerary_summary(state.itinerary)
        if summary:
            state.push_agent_turn(summary)

        state.phase = "awaiting_itinerary_approval"
        return state.model_dump()

    def await_itinerary_approval(state: TravelPlannerState) -> Dict[str, Any]:
        if state.itinerary_approved:
            state.phase = "budgeting"
            return state.model_dump()

        decision = interrupt(
            {
                "type": "confirm_itinerary",
                "itinerary": state.itinerary,
            }
        )

        approved = False
        if isinstance(decision, dict):
            approved = bool(
                decision.get("approved")
                or decision.get("itinerary_approved")
                or decision.get("confirm")
            )
        elif isinstance(decision, bool):
            approved = decision

        state.itinerary_approved = approved
        state.phase = "budgeting" if approved else "awaiting_itinerary_approval"
        return state.model_dump()

    def compute_budget(state: TravelPlannerState) -> Dict[str, Any]:
        if not state.itinerary or not state.itinerary_approved:
            state.phase = "awaiting_itinerary_approval"
            return state.model_dump()

        budget = budget_agent.compute_budget(state.preferences.fields, state.research, state.itinerary)
        state.budget = budget or {}
        state.budget_confirmed = False

        summary = _format_budget_summary(state.budget)
        if summary:
            state.push_agent_turn(summary)

        state.phase = "awaiting_budget_confirmation"
        return state.model_dump()

    def await_budget_confirmation(state: TravelPlannerState) -> Dict[str, Any]:
        if state.budget_confirmed:
            state.phase = "complete"
            return state.model_dump()

        decision = interrupt(
            {
                "type": "confirm_budget",
                "budget": state.budget,
            }
        )

        confirmed = False
        if isinstance(decision, dict):
            confirmed = bool(
                decision.get("confirmed")
                or decision.get("budget_confirmed")
                or decision.get("approve")
            )
        elif isinstance(decision, bool):
            confirmed = decision

        state.budget_confirmed = confirmed
        state.phase = "complete" if confirmed else "awaiting_budget_confirmation"
        return state.model_dump()

    builder.add_node("route", route)
    builder.add_node("collect_preferences", collect_preferences)
    builder.add_node("run_research", run_research)
    builder.add_node("await_attraction_selection", await_attraction_selection)
    builder.add_node("build_itinerary", build_itinerary)
    builder.add_node("await_itinerary_approval", await_itinerary_approval)
    builder.add_node("compute_budget", compute_budget)
    builder.add_node("await_budget_confirmation", await_budget_confirmation)

    builder.add_edge(START, "route")
    builder.add_edge("collect_preferences", "route")
    builder.add_edge("run_research", "route")
    builder.add_edge("await_attraction_selection", "route")
    builder.add_edge("build_itinerary", "route")
    builder.add_edge("await_itinerary_approval", "route")
    builder.add_edge("compute_budget", "route")
    builder.add_edge("await_budget_confirmation", "route")

    def next_phase(state: Dict[str, Any]) -> str:
        return state.get("phase", "complete")

    builder.add_conditional_edges(
        "route",
        next_phase,
        {
            "collecting_preferences": "collect_preferences",
            "awaiting_user_input": END,
            "researching": "run_research",
            "awaiting_attraction_selection": "await_attraction_selection",
            "building_itinerary": "build_itinerary",
            "awaiting_itinerary_approval": "await_itinerary_approval",
            "budgeting": "compute_budget",
            "awaiting_budget_confirmation": "await_budget_confirmation",
            "complete": END,
        },
    )

    return builder.compile(checkpointer=checkpointer)

