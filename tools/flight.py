# tools/flight.py
from __future__ import annotations
import os, time, random
import httpx
from typing import Any, Dict, List, Optional

AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
BASE = "http://api.aviationstack.com/v1"

def _request(method: str, url: str, **kw) -> httpx.Response:
    retries, backoff = 3, 0.8
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

def search_flights_by_route(dep_iata: str, arr_iata: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Provider: Aviationstack /v1/flights
    Returns normalized flight objects (real-time/historical mixed per provider behavior).
    Environment: AVIATIONSTACK_KEY
    """
    assert AVIATIONSTACK_KEY, "Missing AVIATIONSTACK_KEY"
    params = {"access_key": AVIATIONSTACK_KEY, "dep_iata": dep_iata, "arr_iata": arr_iata, "limit": limit}
    r = _request("GET", f"{BASE}/flights", params=params)
    js = r.json()
    out: List[Dict[str, Any]] = []
    for f in js.get("data", []):
        airline = (f.get("airline") or {}).get("name")
        flight_num = (f.get("flight") or {}).get("iata") or f.get("flight", {}).get("number")
        dep = f.get("departure") or {}
        arr = f.get("arrival") or {}
        out.append({
            "id": f"{airline or ''} {flight_num or ''}".strip() or f.get("icao24") or f.get("flight", {}).get("iata"),
            "source": "aviationstack",
            "airline": airline,
            "flight_number": flight_num,
            "dep_airport": dep.get("iata"),
            "arr_airport": arr.get("iata"),
            "dep_time_scheduled": dep.get("scheduled"),
            "arr_time_scheduled": arr.get("scheduled"),
            "status": f.get("flight_status"),
            "raw": f,
        })
    return out
