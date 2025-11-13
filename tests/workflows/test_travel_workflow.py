"""Tests for multi-agent travel planning workflow."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from workflows.state import PreferencesState, ResearchState, TravelPlannerState
from workflows.workflow import TravelPlannerWorkflow


class _StubResearchAgent:
    """Stub research agent for testing."""

    def __init__(self):
        self.call_count = 0
        self.last_focus = None

    def research(self, state: Dict[str, Any], focus: Dict[str, Any] = None) -> Dict[str, Any]:
        self.call_count += 1
        self.last_focus = focus

        # Simulate finding attractions
        base_attractions = [
            {"id": "attr_1", "name": "Generic Museum", "rating": 4.5},
            {"id": "attr_2", "name": "City Park", "rating": 4.3},
        ]

        # If focus is provided, add those attractions first
        if focus and focus.get("attractions"):
            focused_attractions = [
                {"id": f"focus_{i}", "name": name, "rating": 4.8, "source": "user_request"}
                for i, name in enumerate(focus["attractions"])
            ]
            return {
                "attractions": focused_attractions + base_attractions,
                "dining": [],
            }

        return {
            "attractions": base_attractions,
            "dining": [{"id": "rest_1", "name": "Local Restaurant", "rating": 4.2}],
        }


@pytest.mark.skip(reason="Workflow integration tests to be implemented")
def test_travel_workflow_end_to_end():
    """Test complete travel planning workflow from intake to final plan."""
    # TODO: Implement workflow integration test
    # This should test:
    # - Chat agent collects user preferences
    # - Research agent fetches travel data
    # - Planner agent creates itinerary
    # - Budget agent validates costs
    # - Complete workflow produces final plan
    pass


@pytest.mark.skip(reason="Workflow integration tests to be implemented")
def test_travel_workflow_handles_incomplete_preferences():
    """Test workflow behavior when user provides incomplete information."""
    # TODO: Test workflow handles missing required fields
    pass


@pytest.mark.skip(reason="Workflow integration tests to be implemented")
def test_travel_workflow_multi_turn_interaction():
    """Test workflow supports multi-turn conversation for preference gathering."""
    # TODO: Test conversation flow across multiple interactions
    pass


def test_refinement_workflow_accepts_focus_criteria():
    """Test that refinement workflow passes focus criteria to research agent."""
    stub_research = _StubResearchAgent()
    workflow = TravelPlannerWorkflow(research_agent=stub_research)

    # Create a state with completed preferences
    state = TravelPlannerState(
        thread_id="test-123",
        phase="selecting_attractions",
        preferences=PreferencesState(
            fields={
                "destination_city": "Paris",
                "travel_days": 3,
                "start_date": "2025-12-01",
                "budget_usd": 2000,
                "num_people": 2,
                "kids": "no",
                "activity_pref": "indoor",
                "need_car_rental": "no",
                "hotel_room_pref": "king bed",
                "cuisine_pref": "french",
            },
            complete=True,
        ),
        research=ResearchState(
            attractions=[
                {"id": "attr_1", "name": "Generic Museum", "rating": 4.5},
            ],
            dining=[],
        ),
    )

    # Trigger refinement with specific attraction
    refinement_payload = {
        "action": "refine",
        "refinement_criteria": {
            "additional_attractions": ["Louvre Museum"],
        },
    }

    new_state, interrupts = workflow.handle_interrupt(state, refinement_payload)

    # Verify research was called with focus
    assert stub_research.call_count == 1
    assert stub_research.last_focus is not None
    assert stub_research.last_focus.get("attractions") == ["Louvre Museum"]

    # Verify state was updated
    assert new_state.research_iteration == 1
    assert len(new_state.research_refinement_history) == 1
    assert new_state.research_refinement_history[0]["focus"]["attractions"] == ["Louvre Museum"]


def test_refinement_workflow_respects_iteration_limit():
    """Test that refinement workflow enforces max iteration limit."""
    stub_research = _StubResearchAgent()
    workflow = TravelPlannerWorkflow(research_agent=stub_research)

    # Create a state that has already hit max iterations
    state = TravelPlannerState(
        thread_id="test-456",
        phase="selecting_attractions",
        preferences=PreferencesState(
            fields={"destination_city": "Tokyo", "travel_days": 3},
            complete=True,
        ),
        research=ResearchState(
            attractions=[{"id": "attr_1", "name": "Temple", "rating": 4.7}],
            dining=[],
        ),
        research_iteration=2,  # Already at max (default max is 2)
        max_refinement_iterations=2,
    )

    # Try to refine again
    refinement_payload = {
        "action": "refine",
        "refinement_criteria": {
            "additional_attractions": ["Tokyo Tower"],
        },
    }

    new_state, interrupts = workflow.handle_interrupt(state, refinement_payload)

    # Verify research was NOT called again
    assert stub_research.call_count == 0

    # Verify we got a message about exceeding limit
    assert any(
        "refined your search" in turn.content.lower()
        for turn in new_state.conversation_turns
    )

    # State should still be in selection phase
    assert new_state.phase == "selecting_attractions"


def test_refinement_workflow_tracks_history():
    """Test that refinement workflow maintains history of refinements."""
    stub_research = _StubResearchAgent()
    workflow = TravelPlannerWorkflow(research_agent=stub_research)

    state = TravelPlannerState(
        thread_id="test-789",
        phase="selecting_attractions",
        preferences=PreferencesState(
            fields={"destination_city": "London", "travel_days": 4},
            complete=True,
        ),
        research=ResearchState(
            attractions=[{"id": "attr_1", "name": "Museum", "rating": 4.5}],
            dining=[],
        ),
    )

    # First refinement
    refinement1 = {
        "action": "refine",
        "refinement_criteria": {"additional_attractions": ["Tower of London"]},
    }
    state, _ = workflow.handle_interrupt(state, refinement1)

    assert state.research_iteration == 1
    assert len(state.research_refinement_history) == 1
    assert state.research_refinement_history[0]["iteration"] == 1

    # Second refinement
    refinement2 = {
        "action": "refine",
        "refinement_criteria": {"additional_attractions": ["British Museum"]},
    }
    state, _ = workflow.handle_interrupt(state, refinement2)

    assert state.research_iteration == 2
    assert len(state.research_refinement_history) == 2
    assert state.research_refinement_history[1]["iteration"] == 2


def test_refinement_handles_empty_criteria():
    """Test refinement workflow handles empty criteria gracefully."""
    stub_research = _StubResearchAgent()
    workflow = TravelPlannerWorkflow(research_agent=stub_research)

    state = TravelPlannerState(
        thread_id="test-empty",
        phase="selecting_attractions",
        preferences=PreferencesState(
            fields={"destination_city": "Rome", "travel_days": 3},
            complete=True,
        ),
        research=ResearchState(
            attractions=[{"id": "attr_1", "name": "Colosseum", "rating": 4.9}],
            dining=[],
        ),
    )

    # Refinement with empty criteria
    refinement = {
        "action": "refine",
        "refinement_criteria": {},
    }

    new_state, _ = workflow.handle_interrupt(state, refinement)

    # Should still call research but with empty focus
    assert stub_research.call_count == 1
    assert stub_research.last_focus == {}


def test_refinement_supports_both_attractions_and_restaurants():
    """Test refinement can specify both attractions and restaurants."""
    stub_research = _StubResearchAgent()
    workflow = TravelPlannerWorkflow(research_agent=stub_research)

    state = TravelPlannerState(
        thread_id="test-both",
        phase="selecting_attractions",
        preferences=PreferencesState(
            fields={"destination_city": "Barcelona", "travel_days": 5},
            complete=True,
        ),
        research=ResearchState(
            attractions=[{"id": "attr_1", "name": "Park", "rating": 4.6}],
            dining=[],
        ),
    )

    refinement = {
        "action": "refine",
        "refinement_criteria": {
            "additional_attractions": ["Sagrada Familia", "Park Guell"],
            "additional_restaurants": ["El Celler de Can Roca"],
        },
    }

    new_state, _ = workflow.handle_interrupt(state, refinement)

    # Verify both were passed to research
    assert stub_research.last_focus.get("attractions") == ["Sagrada Familia", "Park Guell"]
    assert stub_research.last_focus.get("dining") == ["El Celler de Can Roca"]
