# tools/attractions.py
from __future__ import annotations
import os
import time
import random
import httpx
from typing import Any, Dict, List, Optional

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
BASE = "https://places.googleapis.com/v1"

# --- tiny retry helper ---
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

def search_attractions(query: str, lat: Optional[float]=None, lng: Optional[float]=None, radius_m: int=30000, limit: int=10) -> List[Dict[str, Any]]:
    """
    Provider: Google Places API (Text Search v1).
    Returns a list of normalized POIs.
    Environment: GOOGLE_MAPS_API_KEY
    """
    assert GOOGLE_MAPS_API_KEY, "Missing GOOGLE_MAPS_API_KEY"
    headers = {
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        # Request only the fields we use (field mask is required for v1)
        # Docs: https://developers.google.com/maps/documentation/places/web-service/choose-fields
        "X-Goog-FieldMask": ",".join([
            "places.id",
            "places.displayName",
            "places.shortFormattedAddress",
            "places.location",
            "places.primaryType",
            "places.rating",
            "places.userRatingCount",
            "places.internationalPhoneNumber",
            "places.websiteUri",
            "places.businessStatus",
            "places.currentOpeningHours.weekdayDescriptions",
        ]),
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {"textQuery": query}
    # Ask the API to limit results server-side (v1 supports up to 20)
    payload["maxResultCount"] = min(limit, 20)
    if lat is not None and lng is not None:
        payload["locationBias"] = {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}
        }  # Location *bias* (not a hard bound). :contentReference[oaicite:1]{index=1}

    r = _request("POST", f"{BASE}/places:searchText", headers=headers, json=payload)
    data = r.json()
    out: List[Dict[str, Any]] = []
    for p in data.get("places", [])[:limit]:
        loc = p.get("location") or {}
        out.append({
            "id": p.get("id"),
            "source": "google",
            "name": (p.get("displayName") or {}).get("text"),
            "category": p.get("primaryType"),
            "address": p.get("shortFormattedAddress"),
            "coord": {"lat": loc.get("latitude"), "lng": loc.get("longitude")},
            "rating": p.get("rating"),
            "review_count": p.get("userRatingCount"),
            "phone": p.get("internationalPhoneNumber"),
            "url": p.get("websiteUri"),
            "status": p.get("businessStatus"),
            "hours": (p.get("currentOpeningHours") or {}).get("weekdayDescriptions"),
            "raw": p,  # keep raw for audit
        })
    return out