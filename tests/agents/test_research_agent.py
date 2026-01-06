"""Tests for ResearchAgent."""

from __future__ import annotations

from collections import Counter
from typing import Dict

from agents.research_agent import ResearchAgent


def test_research_agent_runs_all_enabled_tools(monkeypatch):
    """Test that ResearchAgent calls all enabled tools when state includes all required fields."""
    calls = []

    monkeypatch.setattr(ResearchAgent, "_get_weather", lambda self, state: calls.append("weather") or ["w"])
    monkeypatch.setattr(ResearchAgent, "_get_attractions", lambda self, state, priority_names=None: calls.append("attractions") or [
        {"coord": {"lat": 35.0, "lng": -78.9}}
    ])
    monkeypatch.setattr(ResearchAgent, "_get_dining", lambda self, state, attractions=None, priority_names=None: calls.append("dining") or ["d"])
    monkeypatch.setattr(ResearchAgent, "_get_hotels", lambda self, state: calls.append("hotels") or ["h"])
    monkeypatch.setattr(ResearchAgent, "_get_car_rentals", lambda self, state: calls.append("car_rentals") or ["c"])
    monkeypatch.setattr(ResearchAgent, "_get_fuel_prices", lambda self, state: calls.append("fuel_prices") or {"regular": 3.5})
    monkeypatch.setattr(ResearchAgent, "_get_distances", lambda self, attractions: calls.append("distances") or ["dist"])

    state: Dict[str, str] = {
        "destination_city": "Durham",
        "start_date": "2025-11-20",
        "travel_days": 3,
        "cuisine_pref": "ramen",
        "need_car_rental": "yes",
    }

    agent = ResearchAgent()
    result = agent.research(state)

    assert result["weather"] == ["w"]
    assert result["attractions"][0]["coord"] == {"lat": 35.0, "lng": -78.9}
    assert result["dining"] == ["d"]
    assert result["hotels"] == ["h"]
    assert result["car_rentals"] == ["c"]
    assert result["fuel_prices"]["regular"] == 3.5
    assert result["distances"] == ["dist"]
    expected = Counter([
        "weather",
        "attractions",
        "dining",
        "hotels",
        "car_rentals",
        "fuel_prices",
        "distances",
    ])
    assert Counter(calls) == expected


def test_research_agent_skips_optional_tools(monkeypatch):
    """Test that ResearchAgent skips optional tools when not needed."""
    monkeypatch.setattr(ResearchAgent, "_get_weather", lambda self, state: ["weather"])
    monkeypatch.setattr(ResearchAgent, "_get_attractions", lambda self, state, priority_names=None: [
        {"coord": {"lat": 0, "lng": 0}}
    ])
    monkeypatch.setattr(ResearchAgent, "_get_distances", lambda self, attractions: ["dist"])

    agent = ResearchAgent()
    state = {
        "destination_city": "Durham",
        "start_date": "2025-11-20",
        "travel_days": 2,
        "need_car_rental": "no",
    }

    result = agent.research(state)

    assert "dining" not in result
    assert "car_rentals" not in result
    assert "fuel_prices" not in result
    assert result["weather"] == ["weather"]
    assert result["distances"] == ["dist"]


def test_research_agent_handles_missing_city(monkeypatch):
    """Test that ResearchAgent returns empty dict when destination_city is missing."""
    monkeypatch.setattr(ResearchAgent, "_get_weather", lambda self, state: ["weather"])
    monkeypatch.setattr(ResearchAgent, "_get_attractions", lambda self, state: [])

    agent = ResearchAgent()
    state = {"start_date": "2025-11-20", "travel_days": 3}

    assert agent.research(state) == {"error": "destination_city is required"}


def test_get_attractions_prioritizes_user_preferences(monkeypatch):
    """Preferred attraction names should appear first in results."""
    from agents import research_agent as module

    base_results = [
        {"name": "Generic Museum", "source": "google"},
        {"name": "City Park", "source": "google"},
    ]

    monkeypatch.setattr(module, "search_attractions", lambda *args, **kwargs: list(base_results))

    agent = ResearchAgent()
    state = {"destination_city": "Paris"}

    def fake_lookup(self, name, city, coords):
        return {"name": name, "source": "google_search", "raw": {"note": "fetched"}}

    monkeypatch.setattr(ResearchAgent, "_lookup_attraction", fake_lookup)

    prioritized = agent._get_attractions(state, ["Louvre Museum"])
    assert prioritized[0]["name"] == "Louvre Museum"
    # Original catalog items should still follow
    assert any(item["name"] == "Generic Museum" for item in prioritized[1:])


def test_research_focus_combines_with_preferences(monkeypatch):
    """Focus hints during rerun should merge with stored preferred lists."""
    capture = {}

    def fake_get_attractions(self, state, priority_names=None):
        capture["attractions"] = list(priority_names or [])
        return []

    def fake_get_dining(self, state, attractions=None, priority_names=None):
        capture["dining"] = list(priority_names or [])
        return []

    monkeypatch.setattr(ResearchAgent, "_get_attractions", fake_get_attractions)
    monkeypatch.setattr(ResearchAgent, "_get_dining", fake_get_dining)
    monkeypatch.setattr(ResearchAgent, "_get_weather", lambda self, state: [])
    monkeypatch.setattr(ResearchAgent, "_get_hotels", lambda self, state: [])
    monkeypatch.setattr(ResearchAgent, "_get_flights", lambda self, state: [])
    monkeypatch.setattr(ResearchAgent, "_get_car_rentals", lambda self, state: [])
    monkeypatch.setattr(ResearchAgent, "_get_fuel_prices", lambda self, state: [])
    monkeypatch.setattr(ResearchAgent, "_get_distances", lambda self, attractions: [])

    agent = ResearchAgent()
    state = {
        "destination_city": "Tokyo",
        "start_date": "2025-12-01",
        "travel_days": 4,
        "cuisine_pref": "ramen",
        "preferred_attractions": ["teamLab Planets"],
        "preferred_restaurants": ["Ichiran"],
    }

    agent.research(state, focus={"attractions": ["Tokyo Tower"], "dining": ["Sushi Saito"]})

    assert capture["attractions"] == ["teamLab Planets", "Tokyo Tower"]
    assert capture["dining"] == ["Ichiran", "Sushi Saito"]
