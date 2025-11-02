# tools/weather_v2.py
"""
Minimal weather tool for agent integration.
Provider: Open-Meteo (forecast only, ≤15 days ahead).
Geocoding: Google Geocoding API (city → lat/lng).
"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# --- tiny retry helper (matches attractions.py) ---
def _request(method: str, url: str, **kw) -> httpx.Response:
    retries, backoff = 3, 0.6
    last_err = None
    for i in range(retries):
        try:
            with httpx.Client(timeout=kw.pop("timeout", 20)) as c:
                r = c.request(method, url, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                return r
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_err = e
            if i < retries - 1:
                time.sleep(backoff * (2**i) + random.random()*0.2)
            else:
                raise
    raise last_err  # type: ignore

def _geocode(city: str) -> tuple[float, float]:
    """Convert city name to (lat, lng) via Google Geocoding API."""
    assert GOOGLE_MAPS_API_KEY, "Missing GOOGLE_MAPS_API_KEY"
    params = {"address": city, "key": GOOGLE_MAPS_API_KEY}
    r = _request("GET", GEOCODE_URL, params=params)
    data = r.json()

    # If first attempt fails, try adding country/world to help disambiguation
    if data.get("status") != "OK" or not data.get("results"):
        # Try with world context
        params = {"address": f"{city}, World", "key": GOOGLE_MAPS_API_KEY}
        r = _request("GET", GEOCODE_URL, params=params)
        data = r.json()

        if data.get("status") != "OK" or not data.get("results"):
            raise ValueError(f"Geocoding failed for '{city}'. Status: {data.get('status')}. Try being more specific (e.g., 'Tokyo, Japan')")

    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]

def get_weather(
    city: str,
    start_date: str,
    duration: int,
    units: str = "metric"
) -> List[Dict[str, Any]]:
    """
    Provider: Open-Meteo (forecast only, ≤15 days ahead).
    Args:
        city: City name (e.g., "New York", "London")
        start_date: YYYY-MM-DD
        duration: Number of days (1-15)
        units: "metric" (°C, mm) or "imperial" (°F, inch)
    Returns:
        [{"date": "2025-11-01", "temp_high": "20 °C", "temp_low": "10 °C",
          "precipitation": "5 mm", "summary": "Partly cloudy"}, ...]
    """
    # Geocode city
    lat, lng = _geocode(city)

    # Parse dates
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("start_date must be YYYY-MM-DD")

    duration = max(1, min(duration, 15))  # clamp to [1, 15]
    end = start + timedelta(days=duration - 1)

    # Check forecast horizon
    if end > datetime.now() + timedelta(days=15):
        raise ValueError("Weather forecast only available for next 15 days")

    # Unit config
    temp_unit = "celsius" if units == "metric" else "fahrenheit"
    precip_unit = "mm" if units == "metric" else "inch"
    temp_sfx = "°C" if units == "metric" else "°F"
    precip_sfx = "mm" if units == "metric" else "in"

    # Call Open-Meteo
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
        "timezone": "auto",
        "temperature_unit": temp_unit,
        "precipitation_unit": precip_unit,
    }
    r = _request("GET", FORECAST_URL, params=params)
    data = r.json()

    # Normalize output
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    codes = daily.get("weather_code", [])

    _WMO_SUMMARY = {
        0: "Clear sky", 1: "Partly cloudy", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Foggy",
        **{c: "Drizzle" for c in (51, 53, 55, 56, 57)},
        **{c: "Rain" for c in (61, 63, 65, 66, 67)},
        **{c: "Snow" for c in (71, 73, 75, 77)},
        **{c: "Rain showers" for c in (80, 81, 82)},
        **{c: "Snow showers" for c in (85, 86)},
        **{c: "Thunderstorm" for c in (95, 96, 99)},
    }

    # WMO weather code → simple summary
    out: List[Dict[str, Any]] = []
    for i in range(len(dates)):
        out.append({
            "date": dates[i],
            "temp_high": f"{tmax[i]:.0f} {temp_sfx}" if i < len(tmax) else None,
            "temp_low": f"{tmin[i]:.0f} {temp_sfx}" if i < len(tmin) else None,
            "precipitation": f"{precip[i]:.1f} {precip_sfx}" if i < len(precip) else f"0 {precip_sfx}",
            "summary": _WMO_SUMMARY.get(int(codes[i]), "Unknown") if i < len(codes) else "Unknown",
        })
    return out
