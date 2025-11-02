"""Tests for ResearchAgent."""

from __future__ import annotations

from collections import Counter
from typing import Dict

from agents.research_agent import ResearchAgent


def test_research_agent_runs_all_enabled_tools(monkeypatch):
    """Test that ResearchAgent calls all enabled tools when state includes all required fields."""
    calls = []

    monkeypatch.setattr(ResearchAgent, "_get_weather", lambda self, state: calls.append("weather") or ["w"])
    monkeypatch.setattr(ResearchAgent, "_get_attractions", lambda self, state: calls.append("attractions") or [
        {"coord": {"lat": 35.0, "lng": -78.9}}
    ])
    monkeypatch.setattr(ResearchAgent, "_get_dining", lambda self, state, attractions=None: calls.append("dining") or ["d"])
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
    monkeypatch.setattr(ResearchAgent, "_get_attractions", lambda self, state: [
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

    assert agent.research(state) == {}
