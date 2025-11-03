"""Streamlit front end for interacting with the travel planner API."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx
import streamlit as st

API_BASE_URL = os.getenv("TRAVEL_PLANNER_API_URL", "http://localhost:8000")


@st.cache_resource
def get_http_client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE_URL, timeout=30.0)


def _update_session(data: Dict[str, Any]) -> None:
    st.session_state["state"] = data.get("state", {})
    st.session_state["interrupts"] = data.get("interrupts", [])


def _create_session(client: httpx.Client) -> None:
    response = client.post("/sessions")
    response.raise_for_status()
    data = response.json()
    st.session_state["session_id"] = data["session_id"]
    _update_session(data)


def _ensure_session(client: httpx.Client) -> None:
    if st.session_state.get("session_id"):
        return
    _create_session(client)


def _send_turn(
    client: httpx.Client,
    *,
    message: str | None = None,
    interrupt: Dict[str, Any] | None = None,
    extra: Dict[str, Any] | None = None,
) -> None:
    session_id = st.session_state.get("session_id")
    if not session_id:
        _create_session(client)
        session_id = st.session_state["session_id"]

    payload: Dict[str, Any] = {}
    if message is not None:
        payload["message"] = message
    if interrupt is not None:
        payload["interrupt"] = interrupt
    if extra:
        payload.update(extra)

    response = client.post(f"/sessions/{session_id}/turns", json=payload)
    if response.status_code == 404:
        _create_session(client)
        st.experimental_rerun()
        return
    response.raise_for_status()
    _update_session(response.json())


def _render_preferences_sidebar(state: Dict[str, Any]) -> None:
    with st.sidebar:
        st.header("Traveler profile")
        prefs = state.get("preferences", {}).get("fields", {})
        if not prefs:
            st.write("Share your travel preferences to begin.")
            return
        for label, value in prefs.items():
            if value in (None, ""):
                continue
            st.markdown(f"**{label.replace('_', ' ').title()}**: {value}")


def _render_itinerary(state: Dict[str, Any]) -> None:
    itinerary = state.get("itinerary", {}).get("days") or []
    if not itinerary:
        return

    st.subheader("Proposed itinerary")
    for day in itinerary:
        day_number = day.get("day", "Day")
        header = f"Day {day_number}"
        with st.expander(header, expanded=False):
            stops = day.get("stops", [])
            if not stops:
                st.write("Flex day / no scheduled stops yet.")
            for stop in stops:
                name = stop.get("name", "Attraction")
                address = stop.get("address")
                start_time = stop.get("start_time")
                duration = stop.get("duration_hours")
                lines: List[str] = [f"**{name}**"]
                if address:
                    lines.append(address)
                if start_time or duration:
                    schedule = []
                    if start_time:
                        schedule.append(f"Starts at {start_time}")
                    if duration:
                        schedule.append(f"{duration} hour block")
                    lines.append(" · ".join(schedule))
                st.markdown("<br/>".join(lines), unsafe_allow_html=True)
                if stop.get("streetview_url"):
                    st.markdown(f"[Street View preview]({stop['streetview_url']})")

            route = day.get("route") or {}
            if route.get("distance_m") or route.get("duration_s"):
                km = (route.get("distance_m") or 0) / 1000
                minutes = (route.get("duration_s") or 0) / 60
                mode = route.get("mode", "DRIVE")
                st.info(f"Route total: {km:.1f} km – {minutes:.0f} min ({mode})")


def _render_budget(state: Dict[str, Any]) -> None:
    budget = state.get("budget") or {}
    if not budget:
        return

    st.subheader("Budget estimate")
    expected = budget.get("expected")
    currency = budget.get("currency", "USD")
    if expected is not None:
        st.metric("Expected", f"{currency} {expected}")
    low = budget.get("low")
    high = budget.get("high")
    if low is not None and high is not None:
        st.caption(f"Range: {currency} {low} – {currency} {high}")

    breakdown = budget.get("breakdown") or {}
    if breakdown:
        with st.expander("Breakdown", expanded=False):
            for label, value in breakdown.items():
                st.markdown(f"**{label.title()}**: {currency} {value}")


def _render_interrupts(client: httpx.Client, interrupts: List[Dict[str, Any]]) -> None:
    for idx, interrupt in enumerate(interrupts):
        interrupt_type = interrupt.get("type")
        if interrupt_type == "select_attractions":
            options = interrupt.get("options") or []
            if not options:
                continue
            with st.form(key=f"select_attractions_{idx}"):
                st.subheader("Choose the attractions that excite you")
                entries = []
                for opt_idx, option in enumerate(options):
                    name = option.get("name", "Attraction")
                    rating = option.get("rating")
                    address = option.get("address")
                    details = []
                    if rating:
                        details.append(f"{rating}⭐")
                    if address:
                        details.append(address)
                    label = f"{opt_idx + 1}. {name}"
                    if details:
                        label += " — " + " | ".join(details)
                    entries.append((label, opt_idx))

                labels = [entry[0] for entry in entries]
                defaults = labels[: min(2, len(labels))]
                selected = st.multiselect(
                    "Pick your must-see spots",
                    labels,
                    default=defaults,
                    key=f"select_{idx}",
                )
                submitted = st.form_submit_button("Send selection")
                if submitted:
                    index_map = {label: i for label, i in entries}
                    indices = [index_map[label] for label in selected]
                    _send_turn(client, interrupt={"selected_indices": indices})
                    st.experimental_rerun()

        elif interrupt_type == "confirm_itinerary":
            with st.form(key=f"confirm_itinerary_{idx}"):
                st.subheader("Do you approve this itinerary?")
                choice = st.radio(
                    "",
                    ("Approve", "Revise"),
                    horizontal=True,
                    key=f"itinerary_choice_{idx}",
                )
                if st.form_submit_button("Submit response"):
                    _send_turn(client, interrupt={"approved": choice == "Approve"})
                    st.experimental_rerun()

        elif interrupt_type == "confirm_budget":
            with st.form(key=f"confirm_budget_{idx}"):
                st.subheader("Does the budget work for you?")
                choice = st.radio(
                    "",
                    ("Confirm", "Adjust"),
                    horizontal=True,
                    key=f"budget_choice_{idx}",
                )
                if st.form_submit_button("Submit response"):
                    _send_turn(client, interrupt={"confirmed": choice == "Confirm"})
                    st.experimental_rerun()


def main() -> None:
    st.set_page_config(page_title="Travel Planner Companion", page_icon="🧭", layout="wide")
    st.title("🧭 Travel Planner Companion")

    st.session_state.setdefault("state", {})
    st.session_state.setdefault("interrupts", [])
    st.session_state.setdefault("session_id", None)

    client = get_http_client()
    try:
        _ensure_session(client)
    except httpx.HTTPError as exc:  # pragma: no cover - network failure feedback
        st.error(f"Unable to connect to the planner API: {exc}")
        return

    state = st.session_state.get("state", {})
    interrupts = st.session_state.get("interrupts", [])

    _render_preferences_sidebar(state)

    for turn in state.get("conversation_turns", []):
        role = turn.get("role", "assistant")
        speaker = "assistant" if role != "user" else "user"
        with st.chat_message(speaker):
            st.markdown(turn.get("content", ""))

    prompt = st.chat_input("Share more details about your trip")
    if prompt:
        try:
            _send_turn(client, message=prompt)
        except httpx.HTTPError as exc:  # pragma: no cover - network failure feedback
            st.error(f"Request failed: {exc}")
        st.experimental_rerun()

    if interrupts:
        _render_interrupts(client, interrupts)

    _render_itinerary(state)
    _render_budget(state)


if __name__ == "__main__":
    main()

