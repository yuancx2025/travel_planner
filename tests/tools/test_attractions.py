"""Tests for attractions tool."""

from __future__ import annotations

from tools import attractions


def test_attractions_search_returns_normalized(monkeypatch, fake_response):
    """Test attractions API returns normalized results with required fields."""
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
