"""Unit tests for `tools.hotels` using mocked Google Places API (Text Search + Details)."""

from __future__ import annotations

import os, sys, pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]  # travel_planner/
sys.path.insert(0, str(PROJECT_ROOT))

from types import SimpleNamespace
from tools import hotels


def _json_resp(payload: dict):
    """Return a lightweight object with a .json() method like requests.Response."""
    return SimpleNamespace(json=lambda: payload)


def _make_requests_get_mock():
    """
    Factory that returns a requests.get replacement which:
      - For Text Search:
          * query contains 'Atlantis' -> ZERO_RESULTS
          * otherwise -> one hotel result
      - For Place Details:
          * returns details for place_id 'P1'
    """

    def _mock_requests_get(url, params=None, timeout=20):
        params = params or {}
        if "textsearch" in url:
            query = params.get("query", "")
            if "Atlantis" in query:
                return _json_resp({"status": "ZERO_RESULTS", "results": []})
            # Success path with one search result
            return _json_resp(
                {
                    "status": "OK",
                    "results": [
                        {
                            "place_id": "P1",
                            "name": "Downtown Inn",
                            "formatted_address": "123 Main St",
                            "rating": 4.3,
                            "price_level": 3,
                        }
                    ],
                }
            )
        if "details" in url:
            # Enrich the result; could override name/address/rating if desired
            place_id = params.get("place_id")
            if place_id == "P1":
                return _json_resp(
                    {
                        "status": "OK",
                        "result": {
                            "place_id": "P1",
                            "name": "Downtown Inn",  # same as text search
                            "formatted_address": "123 Main St",
                            "rating": 4.3,
                            "price_level": 3,
                            "website": "https://example.com",
                            "international_phone_number": "+1 555-555-5555",
                        },
                    }
                )
            return _json_resp({"status": "OK", "result": {}})
        # Fallback to a benign OK
        return _json_resp({"status": "OK", "results": []})

    return _mock_requests_get


def test_search_hotels_returns_normalized_results(monkeypatch):
    # Patch requests.get inside tools.hotels to our mock
    monkeypatch.setattr(
        hotels, "requests", SimpleNamespace(get=_make_requests_get_mock())
    )

    results = hotels.search_hotels_by_city(
        "Durham", "2025-11-01", "2025-11-03", adults=2, limit=1
    )

    assert len(results) == 1
    first = results[0]
    assert first["hotel_id"] == "P1"
    assert first["name"] == "Downtown Inn"
    assert first["address"] == "123 Main St"
    # Google Places doesn't provide room prices; expect None
    assert first["price"] is None
    assert first["currency"] is None
    # Rating is numeric from Places
    assert first["rating"] == 4.3
    # Optional extra we expose
    assert first.get("price_level") == 3
    assert first["source"] == "google_places"
    # Raw payload should include text_search (and details due to enrichment)
    assert "text_search" in first["raw"]


def test_search_hotels_unknown_city_returns_empty(monkeypatch):
    # Patch requests.get so that 'Atlantis' returns ZERO_RESULTS
    monkeypatch.setattr(
        hotels, "requests", SimpleNamespace(get=_make_requests_get_mock())
    )

    results = hotels.search_hotels_by_city("Atlantis", "2025-11-01", "2025-11-03")
    assert results == []
