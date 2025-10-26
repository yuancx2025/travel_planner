from __future__ import annotations
import os, time, random
import httpx
from typing import Any, Dict, List, Tuple

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
BASE = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

# --- tiny retry helper (duplicated from attractions.py for isolation) ---
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

def get_distance_matrix(
    origins: List[Tuple[float, float]],
    destinations: List[Tuple[float, float]],
    mode: str = "DRIVE"
) -> List[Dict[str, Any]]:
    """
    Provider: Google Routes API (Distance Matrix v2).
    Returns distance/duration for each origin-destination pair.
    Environment: GOOGLE_MAPS_API_KEY
    Args:
        origins: [(lat, lng), ...] up to 25 waypoints
        destinations: [(lat, lng), ...] up to 25 waypoints
        mode: DRIVE | WALK | BICYCLE | TRANSIT
    """
    assert GOOGLE_MAPS_API_KEY, "Missing GOOGLE_MAPS_API_KEY"
    headers = {
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "originIndex,destinationIndex,distanceMeters,duration,status",
        "Content-Type": "application/json",
    }
    payload = {
        "origins": [{"waypoint": {"location": {"latLng": {"latitude": o[0], "longitude": o[1]}}}} for o in origins],
        "destinations": [{"waypoint": {"location": {"latLng": {"latitude": d[0], "longitude": d[1]}}}} for d in destinations],
        "travelMode": mode,
    }
    r = _request("POST", BASE, headers=headers, json=payload)
    data = r.json()
    out: List[Dict[str, Any]] = []
    for elem in data:
        distance_m = elem.get("distanceMeters", 0)
        duration_s = int(elem.get("duration", "0s").rstrip("s"))
        out.append({
            "origin_idx": elem.get("originIndex"),
            "dest_idx": elem.get("destinationIndex"),
            "distance_m": distance_m,
            "duration_s": duration_s,
            "status": elem.get("status"),
        })
    return out