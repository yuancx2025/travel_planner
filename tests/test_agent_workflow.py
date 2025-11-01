"""Lightweight agent workflow tests with mocked tool calls."""

from __future__ import annotations

from datetime import datetime
from collections import Counter
from typing import Dict

import pytest

from agents.research_agent import ResearchAgent
from tools import weather, distance_matrix, attractions


def test_research_agent_runs_all_enabled_tools(monkeypatch):
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
    monkeypatch.setattr(ResearchAgent, "_get_weather", lambda self, state: ["weather"])
    monkeypatch.setattr(ResearchAgent, "_get_attractions", lambda self, state: [])

    agent = ResearchAgent()
    state = {"start_date": "2025-11-20", "travel_days": 3}

    assert agent.research(state) == {}


def test_weather_get_weather_normalizes(monkeypatch, fake_response):
    monkeypatch.setattr(weather, "GOOGLE_MAPS_API_KEY", "fake")

    def _fake_request(method: str, url: str, **kw):  # pragma: no cover - exercised via call
        if "geocode" in url:
            return fake_response({
                "status": "OK",
                "results": [
                    {"geometry": {"location": {"lat": 35.0, "lng": -78.9}}}
                ],
            })
        return fake_response({
            "daily": {
                "time": [datetime.now().strftime("%Y-%m-%d")],
                "temperature_2m_max": [68.0],
                "temperature_2m_min": [50.0],
                "precipitation_sum": [0.5],
                "weather_code": [0],
            }
        })

    monkeypatch.setattr(weather, "_request", _fake_request)

    start_date = datetime.now().strftime("%Y-%m-%d")
    forecast = weather.get_weather("Durham", start_date, 1, units="imperial")

    assert forecast[0]["temp_high"] == "68 °F"
    assert forecast[0]["temp_low"] == "50 °F"
    assert forecast[0]["precipitation"].endswith("in")
    assert forecast[0]["summary"] == "Clear sky"


def test_distance_matrix_resolves_place_ids(monkeypatch, fake_response):
    monkeypatch.setattr(distance_matrix, "GOOGLE_MAPS_API_KEY", "fake")

    def _fake_request(method: str, url: str, **kw):  # pragma: no cover - exercised via call
        if "places" in url:
            query = kw["json"]["textQuery"]
            return fake_response({"places": [{"id": f"places/{query}-id"}]})
        return fake_response([
            {
                "originIndex": 0,
                "destinationIndex": 0,
                "distanceMeters": 1600,
                "duration": "600s",
                "status": "OK",
            }
        ])

    monkeypatch.setattr(distance_matrix, "_request", _fake_request)

    results = distance_matrix.get_distance_matrix(["Durham"], ["Raleigh"])

    assert results[0]["distance_m"] == 1600
    assert results[0]["duration_s"] == 600
    assert results[0]["status"] == "OK"


def test_attractions_search_returns_normalized(monkeypatch, fake_response):
    monkeypatch.setattr(attractions, "GOOGLE_MAPS_API_KEY", "fake")

    def _fake_request(method: str, url: str, **kw):  # pragma: no cover - exercised via call
        return fake_response({
            "places": [
                {
                    "id": "place-1",
                    "displayName": {"text": "History Museum"},
                    "shortFormattedAddress": "123 Main St",
                    "location": {"latitude": 35.0, "longitude": -78.9},
                    "primaryType": "museum",
                    "rating": 4.7,
                    "userRatingCount": 210,
                }
            ]
        })

    monkeypatch.setattr(attractions, "_request", _fake_request)

    results = attractions.search_attractions("museums in Durham", limit=1)

    assert results[0]["id"] == "place-1"
    assert results[0]["name"] == "History Museum"
    assert results[0]["coord"] == {"lat": 35.0, "lng": -78.9}
    assert results[0]["source"] == "google"
