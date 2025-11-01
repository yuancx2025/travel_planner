# tools/dining.py
"""Restaurant search using Google Places API (New) v1 - Text Search."""
from __future__ import annotations
import os
import time
import random
from typing import List, Dict, Any, Optional
import httpx

GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
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

def search_restaurants(
    query: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_m: int = 3000,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search for restaurants using Google Places API (New) v1 Text Search.
    
    Args:
        query: Natural language query (e.g., "italian restaurants in San Francisco" 
               or "sushi near Shibuya Station")
        lat, lng: Optional location bias center (if provided, adds circle bias)
        radius_m: Search radius in meters (default 3000) - only used if lat/lng provided
        limit: Max results (1-20, default 10)
    
    Returns:
        List of normalized restaurant dicts with keys:
        - id, source, name, rating, review_count, address, coord, price_level, raw
    
    Docs: https://developers.google.com/maps/documentation/places/web-service/search-text
    """
    if not GOOGLE_API_KEY:
        raise ValueError(
            "Missing GOOGLE_MAPS_API_KEY."
        )
    
    headers = {
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        # Request only needed fields (field mask is required for v1)
        "X-Goog-FieldMask": ",".join([
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.rating",
            "places.userRatingCount",
            "places.priceLevel",
            "places.types",
        ]),
        "Content-Type": "application/json",
    }
    
    # If caller passed only a location-like string without category and no lat/lng,
    # make it a categorical query so Text Search returns restaurants in that area.
    if lat is None and lng is None:
        q_lower = query.lower()
        has_category = any(k in q_lower for k in (
            "restaurant", "restaurants", "cafe", "food", "diner", "bistro", "bar",
            "pizza", "sushi", "ramen", "burger", "vegan", "italian", "thai",
            "mexican", "indian", "chinese", "korean", "bbq", "steak", "seafood"
        ))
        if not has_category:
            query = f"restaurants in {query}"

    payload: Dict[str, Any] = {
        "textQuery": query,
        "includedType": "restaurant",  # v1: use includedType instead of legacy type
        # pageSize is the current parameter; maxResultCount is deprecated.
        "pageSize": min(limit, 20),
        # Keep results strictly to the requested type to avoid localities, etc.
        "strictTypeFiltering": True,
        "rankPreference": "RELEVANCE",
    }
    
    # Optional: add location bias if lat/lng provided
    if lat is not None and lng is not None:
        payload["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m
            }
        }
    
    try:
        r = _request("POST", f"{BASE}/places:searchText", headers=headers, json=payload)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            detail = e.response.json() if e.response.text else {}
            raise RuntimeError(
                f"403 Forbidden from Places API. Common causes:\n"
                f"Response: {detail}"
            ) from e
        raise
    
    data = r.json()
    out: List[Dict[str, Any]] = []
    
    for p in data.get("places", []):
        loc = p.get("location") or {}
        out.append({
            "id": p.get("id"),
            "source": "google",
            "name": (p.get("displayName") or {}).get("text"),
            "rating": p.get("rating"),
            "review_count": p.get("userRatingCount"),
            "address": p.get("formattedAddress"),
            "coord": {
                "lat": loc.get("latitude"),
                "lng": loc.get("longitude")
            },
            "price_level": p.get("priceLevel"),  # v1 returns string: "PRICE_LEVEL_INEXPENSIVE", "PRICE_LEVEL_MODERATE", etc.
            "raw": p,  # preserve raw for audit
        })
    
    return out