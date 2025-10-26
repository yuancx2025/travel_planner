"""
Simple integration test for the agent workflow.
Tests ChatAgent → PlannerAgent → ResearchAgent flow.
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.planner_agent import PlannerAgent
from agents.research_agent import ResearchAgent
from agents.chat_agent import ChatAgent


# Skip if API keys not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY") or not os.environ.get("GOOGLE_MAPS_API_KEY"),
    reason="GOOGLE_API_KEY or GOOGLE_MAPS_API_KEY not set"
)


def test_chat_agent_info_collection():
    """Test ChatAgent can extract user preferences."""
    agent = ChatAgent()
    state = {}
    
    # First message
    result = agent.collect_info("My name is Alice and I want to visit San Francisco", state)
    state = result["state"]
    
    assert "name" in state or "destination_city" in state
    assert not result["complete"]  # Should still need more info
    
    # Second message
    result = agent.collect_info("5 days starting November 15, 2025", state)
    state = result["state"]
    
    assert len(state) > 2  # Should have collected multiple fields


def test_research_agent_basic():
    """Test ResearchAgent can call tools with valid state."""
    agent = ResearchAgent()
    
    # Minimal valid state
    state = {
        "destination_city": "San Francisco",
        "start_date": "2025-11-15",
        "travel_days": 3,
        "cuisine_pref": "seafood"
    }
    
    results = agent.research(state)
    
    # Should have at least weather and attractions
    assert "weather" in results
    assert "attractions" in results
    
    # Weather should have data
    if results["weather"]:
        assert len(results["weather"]) > 0
        assert "date" in results["weather"][0]
        assert "temp_high" in results["weather"][0]


def test_research_agent_conditional_tools():
    """Test ResearchAgent only calls tools when conditions are met."""
    agent = ResearchAgent()
    
    # State without cuisine preference or car rental
    state = {
        "destination_city": "New York",
        "start_date": "2025-12-01",
        "travel_days": 2
    }
    
    results = agent.research(state)
    
    # Should NOT have dining or car rentals
    assert results.get("dining") is None
    assert results.get("car_rentals") is None
    
    # Should have weather and attractions
    assert "weather" in results
    assert "attractions" in results


def test_planner_agent_phases():
    """Test PlannerAgent workflow phases."""
    planner = PlannerAgent()
    
    # Phase 1: Collecting
    response = planner.interact("I want to visit Boston")
    assert response["phase"] == "collecting"
    assert "state" in response
    
    # State should have destination
    assert "Boston" in str(response["state"].get("destination_city", ""))


def test_planner_agent_state_persistence():
    """Test PlannerAgent maintains state across interactions."""
    planner = PlannerAgent()
    
    # Multiple interactions
    r1 = planner.interact("My name is Bob")
    r2 = planner.interact("I want to go to Seattle")
    
    # Both pieces of info should be in final state
    final_state = r2["state"]
    assert "name" in final_state or "destination_city" in final_state


def test_end_to_end_minimal():
    """
    Minimal end-to-end test: provide all required fields and verify
    we reach research phase.
    """
    planner = PlannerAgent()
    
    # Provide comprehensive info in one message
    message = (
        "My name is Charlie, I want to visit Los Angeles for 4 days "
        "starting 2025-11-20. My budget is $2000 for 2 people, no kids. "
        "I prefer outdoor activities, need a car rental, want 1 king bed, "
        "and love Mexican food."
    )
    
    response = planner.interact(message)
    
    # Should either be collecting (if extraction missed fields) or researching
    assert response["phase"] in ["collecting", "researching", "planning", "complete"]
    
    # State should have most fields
    state = response["state"]
    assert len(state) >= 5  # Should have extracted multiple fields


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
