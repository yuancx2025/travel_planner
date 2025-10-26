# tools/weather.py
"""
Weather tool (Open-Meteo; no API key required).

- Forecast (<= ~16 days ahead) via: https://api.open-meteo.com/v1/forecast
- Historical average (beyond horizon) via: https://archive-api.open-meteo.com/v1/archive
- Output (list[dict] per day):
  {
    "date": "YYYY-MM-DD",
    "max_temp": "20 °C",
    "min_temp": "10 °C",
    "precipitation": "10 mm",
    "wind_speed": "10 km/h",
    "precipitation_probability": "10%",  # forecast only
    "uv_index": "8"                       # forecast only
  }

Usage:
  from tools.weather import get_weather
  data = get_weather(40.7128, -74.0060, "2025-11-01", 7, units="metric")
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional

import requests

# ------------------ Constants & Config ------------------

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

DEFAULT_CACHE_FILE = os.getenv("WEATHER_CACHE_FILE", "weather_cache.json")
FORECAST_TTL_S = 6 * 3600          # 6 hours
HISTORICAL_TTL_S = 30 * 24 * 3600  # 30 days
REQUEST_TIMEOUT = 12               # seconds
RETRY_ATTEMPTS = 2                 # simple retry

# Open-Meteo handles unit conversion for us
@dataclass(frozen=True)
class UnitCfg:
    temp_unit: str
    wind_unit: str
    precip_unit: str
    temp_sfx: str
    wind_sfx: str
    precip_sfx: str

UNITS: Dict[str, UnitCfg] = {
    "metric":   UnitCfg("celsius",    "kmh", "mm",   "°C", "km/h", "mm"),
    "imperial": UnitCfg("fahrenheit", "mph", "inch", "°F", "mph",  "in"),
}

# ------------------ Errors & Small Utils ------------------

class WeatherError(Exception):
    pass

def _iso(d: datetime | date) -> str:
    return (d if isinstance(d, date) else d.date()).strftime("%Y-%m-%d")

def _parse_date(s: str) -> datetime:
    try: return datetime.strptime(s, "%Y-%m-%d")
    except Exception: raise WeatherError("start_date must be YYYY-MM-DD")

def _check_lat_lng(lat: float, lng: float) -> None:
    try: lat, lng = float(lat), float(lng)
    except Exception: raise WeatherError("lat/lng must be numeric")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise WeatherError("lat ∈ [-90,90], lng ∈ [-180,180]")

def _duration(n: int) -> int:
    if not isinstance(n, int) or n <= 0: raise WeatherError("duration must be a positive integer")
    return min(n, 30)

def _safe_num(seq: List[Any], i: int, default: float = 0.0) -> float:
    try: return float(seq[i])
    except Exception: return default

def _get_units(units: str) -> UnitCfg:
    units = (units or "metric").lower()
    if units not in UNITS: raise WeatherError("units must be 'metric' or 'imperial'")
    return UNITS[units]

def _http_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    last = None
    for _ in range(1 + RETRY_ATTEMPTS):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e; time.sleep(0.3)
    raise WeatherError(f"HTTP error calling Open-Meteo: {last}")

# ------------------ Tiny File Cache ------------------

class FileCache:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path): return
        try:
            raw = json.load(open(self.path, "r"))
            now = time.time()
            self.data = {
                k: v for k, v in raw.items()
                if isinstance(v, dict) and v.get("expires_at", 0) > now
            }
        except Exception:
            self.data = {}

    def _save(self):
        try: json.dump(self.data, open(self.path, "w"))
        except Exception: pass  # cache failures shouldn’t break tool

    def get(self, key: str) -> Optional[Any]:
        v = self.data.get(key)
        if not v or v["expires_at"] <= time.time():
            self.data.pop(key, None); self._save(); return None
        return v["value"]

    def set(self, key: str, value: Any, ttl_s: int):
        self.data[key] = {"value": value, "expires_at": time.time() + ttl_s}
        self._save()

# ------------------ Core Service ------------------

class WeatherService:
    """Agent-friendly wrapper around Open-Meteo forecast + archive endpoints."""
    def __init__(self, cache_file: str = DEFAULT_CACHE_FILE):
        self.cache = FileCache(cache_file)

    def get_weather(
        self, lat: float, lng: float, start_date: str, duration: int, units: str = "metric"
    ) -> List[Dict[str, Any]]:
        _check_lat_lng(lat, lng)
        start = _parse_date(start_date)
        duration = _duration(duration)
        end = start + timedelta(days=duration - 1)
        cfg = _get_units(units)

        # Forecast horizon ≈ 15 days from "now"
        if end <= datetime.now() + timedelta(days=15):
            return self._forecast(lat, lng, start, end, cfg)
        return self._historical_average(lat, lng, start, end, cfg)

    # -------- Forecast --------
    def _forecast(self, lat: float, lng: float, start: datetime, end: datetime, cfg: UnitCfg):
        key = f"f:{lat:.4f}:{lng:.4f}:{_iso(start)}:{_iso(end)}:{cfg.temp_unit}"
        if (cached := self.cache.get(key)): return cached

        params = dict(
            latitude=lat, longitude=lng,
            start_date=_iso(start), end_date=_iso(end),
            daily=",".join([
                "temperature_2m_max","temperature_2m_min","precipitation_sum",
                "wind_speed_10m_max","precipitation_probability_mean","uv_index_max"
            ]),
            timezone="auto",
            temperature_unit=cfg.temp_unit,
            wind_speed_unit=cfg.wind_unit,
            precipitation_unit=cfg.precip_unit,
        )
        data = _http_json(FORECAST_URL, params)
        out = self._fmt_forecast(data, cfg)
        self.cache.set(key, out, FORECAST_TTL_S)
        return out

    # -------- Historical Average --------
    def _historical_average(self, lat: float, lng: float, start: datetime, end: datetime, cfg: UnitCfg):
        key = f"h:{lat:.4f}:{lng:.4f}:{_iso(start)}:{_iso(end)}:{cfg.temp_unit}"
        if (cached := self.cache.get(key)): return cached

        today = datetime.now().date()
        blobs: List[Dict[str, Any]] = []
        for yr in range(1, 5):  # last 4 years
            s, e = (start - timedelta(days=365*yr)).date(), (end - timedelta(days=365*yr)).date()
            if e >= today:  # archive API can’t return future
                continue
            params = dict(
                latitude=lat, longitude=lng,
                start_date=s.strftime("%Y-%m-%d"), end_date=e.strftime("%Y-%m-%d"),
                daily=",".join(["temperature_2m_max","temperature_2m_min","precipitation_sum","wind_speed_10m_max"]),
                timezone="auto",
                temperature_unit=cfg.temp_unit,
                wind_speed_unit=cfg.wind_unit,
                precipitation_unit=cfg.precip_unit,
            )
            try: blobs.append(_http_json(ARCHIVE_URL, params))
            except WeatherError: continue  # soft fail per year

        if not blobs: raise WeatherError("Insufficient historical data for averaging.")
        out = self._avg_archives(blobs, cfg)
        self.cache.set(key, out, HISTORICAL_TTL_S)
        return out

    # -------- Formatters --------
    @staticmethod
    def _fmt_forecast(data: Dict[str, Any], cfg: UnitCfg) -> List[Dict[str, Any]]:
        d = data.get("daily", {})
        times  = d.get("time", [])
        tmax   = d.get("temperature_2m_max", [])
        tmin   = d.get("temperature_2m_min", [])
        precip = d.get("precipitation_sum", [])
        wind   = d.get("wind_speed_10m_max", [])
        pprob  = d.get("precipitation_probability_mean", [])
        uvi    = d.get("uv_index_max", [])

        return [
            {
                "date": times[i],
                "max_temp": f"{_safe_num(tmax, i):g} {cfg.temp_sfx}",
                "min_temp": f"{_safe_num(tmin, i):g} {cfg.temp_sfx}",
                "precipitation": f"{_safe_num(precip, i):g} {cfg.precip_sfx}",
                "wind_speed": f"{_safe_num(wind, i):g} {cfg.wind_sfx}" if i < len(wind) else None,
                "precipitation_probability": f"{_safe_num(pprob, i):g}%" if i < len(pprob) else None,
                "uv_index": f"{_safe_num(uvi, i):g}" if i < len(uvi) else None,
            }
            for i in range(len(times))
        ]

    @staticmethod
    def _avg_archives(blobs: List[Dict[str, Any]], cfg: UnitCfg) -> List[Dict[str, Any]]:
        # sum per date
        totals: Dict[str, Dict[str, float]] = {}
        counts: Dict[str, int] = {}
        for b in blobs:
            d = b.get("daily", {})
            times  = d.get("time", [])
            tmax   = d.get("temperature_2m_max", [])
            tmin   = d.get("temperature_2m_min", [])
            precip = d.get("precipitation_sum", [])
            wind   = d.get("wind_speed_10m_max", [])
            for i, day in enumerate(times):
                t = totals.setdefault(day, {"tmax":0.0,"tmin":0.0,"prec":0.0,"wind":0.0})
                t["tmax"] += _safe_num(tmax, i)
                t["tmin"] += _safe_num(tmin, i)
                t["prec"] += _safe_num(precip, i)
                if i < len(wind): t["wind"] += _safe_num(wind, i)
                counts[day] = counts.get(day, 0) + 1

        # average & format; prob/uv not available historically
        return [
            {
                "date": day,
                "max_temp": f"{totals[day]['tmax']/counts[day]:.1f} {cfg.temp_sfx}",
                "min_temp": f"{totals[day]['tmin']/counts[day]:.1f} {cfg.temp_sfx}",
                "precipitation": f"{totals[day]['prec']/counts[day]:.1f} {cfg.precip_sfx}",
                "wind_speed": f"{totals[day]['wind']/counts[day]:.1f} {cfg.wind_sfx}",
                "precipitation_probability": None,
                "uv_index": None,
            }
            for day in sorted(totals.keys())
        ]

# ------------------ Simple function wrapper ------------------

def get_weather(
    lat: float,
    lng: float,
    start_date: str,
    duration: int,
    units: str = "metric",
) -> List[Dict[str, Any]]:
    """Convenience function for agents."""
    return WeatherService().get_weather(lat, lng, start_date, duration, units)

# ------------------ CLI ------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Weather tool (Open-Meteo)")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--start", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--units", type=str, default="metric", choices=list(UNITS.keys()))
    args = parser.parse_args()
    try:
        print(json.dumps(
            get_weather(args.lat, args.lng, args.start, args.days, args.units),
            indent=2
        ))
    except Exception as e:
        print(f"[weather error] {e}")
        raise
