"""Tests for weather tool."""

from __future__ import annotations

from datetime import datetime

from tools import weather


def test_weather_get_weather_normalizes(monkeypatch, fake_response):
    """Test weather API returns normalized forecast data."""
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
