"""Unit tests for `tools.dining` without real API calls."""

from __future__ import annotations

from typing import Any, Dict

from tools import dining


def _sample_place(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "id": "place-123",
        "displayName": {"text": "Ramen Spot"},
        "formattedAddress": "123 Noodle St, Durham, NC",
        "location": {"latitude": 35.0, "longitude": -78.9},
        "rating": 4.5,
        "userRatingCount": 120,
        "priceLevel": "PRICE_LEVEL_MODERATE",
    }
    payload.update(overrides)
    return payload


def test_search_restaurants_normalizes_results(monkeypatch, fake_response):
    payload = {"places": [_sample_place()]}
    captured_request: Dict[str, Any] = {}

    def _fake_request(method: str, url: str, **kw: Any):  # pragma: no cover - exercised via call
        captured_request.update(kw.get("json", {}))
        return fake_response(payload)

    monkeypatch.setattr(dining, "_request", _fake_request)

    results = dining.search_restaurants("sushi", lat=38.9, lng=-77.04, radius_m=1500, limit=5)

    assert captured_request["locationBias"]["circle"]["radius"] == 1500
    assert captured_request["pageSize"] == 5

    assert len(results) == 1
    result = results[0]
    assert result["id"] == "place-123"
    assert result["source"] == "google"
    assert result["name"] == "Ramen Spot"
    assert result["coord"] == {"lat": 35.0, "lng": -78.9}
    assert result["raw"]["priceLevel"] == "PRICE_LEVEL_MODERATE"


def test_search_restaurants_rewrites_location_query(monkeypatch, fake_response):
    payload = {"places": []}
    captured_text_query = {}

    def _fake_request(method: str, url: str, **kw: Any):  # pragma: no cover - exercised via call
        captured_text_query["value"] = kw["json"]["textQuery"]
        return fake_response(payload)

    monkeypatch.setattr(dining, "_request", _fake_request)

    dining.search_restaurants("Durham, NC")

    assert captured_text_query["value"].lower().startswith("restaurants in durham, nc")
