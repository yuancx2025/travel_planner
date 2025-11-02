from __future__ import annotations

import os
import random
import time
from typing import Any, Dict, List, Tuple, Union  # <- add Union

import httpx

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

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

def _waypoint_from_input(item: Union[Tuple[float, float], str]) -> Dict[str, Any]:
    """
    Convert a (lat,lng) tuple or a place name/address string into a Distance Matrix waypoint.
    - Tuples -> waypoint.location.latLng
    - Strings -> resolve with Places Text Search and use waypoint.placeId (preferred by Routes)
    """
    if isinstance(item, tuple):
        lat, lng = item
        return {"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lng}}}}
    # Resolve string via Places Text Search (pageSize=1)
    assert GOOGLE_MAPS_API_KEY, "Missing GOOGLE_MAPS_API_KEY"
    headers = {
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "places.id",  # we just need the Place ID
        "Content-Type": "application/json",
    }
    payload = {"textQuery": str(item), "pageSize": 1}
    r = _request("POST", PLACES_SEARCH_URL, headers=headers, json=payload)
    data = r.json()
    places = data.get("places") or []

    # If first attempt fails, try adding ", USA" for disambiguation (common US travel case)
    if not places:
        payload["textQuery"] = f"{item}, USA"
        r = _request("POST", PLACES_SEARCH_URL, headers=headers, json=payload)
        data = r.json()
        places = data.get("places") or []

    if not places:
        raise ValueError(
            f"Could not resolve place: '{item}'. "
            f"Try being more specific (e.g., 'Durham, NC' or 'Chapel Hill, North Carolina')"
        )

    pid = places[0].get("id", "")
    # Places v1 returns resource name like 'places/ChIJ...'; Routes Waypoint.placeId expects 'ChIJ...'
    if pid.startswith("places/"):
        pid = pid.split("/", 1)[1]
    if not pid:
        raise ValueError(f"Resolved place missing id: '{item}'")
    return {"waypoint": {"placeId": pid}}

def get_distance_matrix(
    origins: List[Union[Tuple[float, float], str]],
    destinations: List[Union[Tuple[float, float], str]],
    mode: str = "DRIVE"
) -> List[Dict[str, Any]]:
    """
    Provider: Google Routes API (Distance Matrix v2).
    Returns distance/duration for each origin-destination pair.
    Environment: GOOGLE_MAPS_API_KEY
    Args:
        origins: list of (lat, lng) tuples OR place names/addresses (strings)
        destinations: list of (lat, lng) tuples OR place names/addresses (strings)
        mode: DRIVE | WALK | BICYCLE | TRANSIT
    """
    assert GOOGLE_MAPS_API_KEY, "Missing GOOGLE_MAPS_API_KEY"
    headers = {
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "originIndex,destinationIndex,distanceMeters,duration,status",
        "Content-Type": "application/json",
    }
    payload = {
        "origins": [_waypoint_from_input(o) for o in origins],
        "destinations": [_waypoint_from_input(d) for d in destinations],
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
