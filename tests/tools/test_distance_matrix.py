"""Tests for distance_matrix tool."""

from __future__ import annotations

from tools import distance_matrix


def test_distance_matrix_resolves_place_ids(monkeypatch, fake_response):
    """Test distance matrix API resolves place IDs and returns distances."""
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
