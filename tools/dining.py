# tools/dining.py
from __future__ import annotations
import os, time, random
import httpx
from typing import Any, Dict, List

YELP_API_KEY = os.environ.get("YELP_API_KEY")
BASE = "https://api.yelp.com/v3"

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

def search_dining(term: str, lat: float, lng: float, radius_m: int = 3000, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Provider: Yelp Fusion Business Search.
    Returns normalized restaurant POIs.
    Environment: YELP_API_KEY
    """
    assert YELP_API_KEY, "Missing YELP_API_KEY"
    headers = {"Authorization": f"Bearer {YELP_API_KEY}"}
    params = {"term": term, "latitude": lat, "longitude": lng, "radius": radius_m, "limit": limit}
    r = _request("GET", f"{BASE}/businesses/search", headers=headers, params=params)
    js = r.json()
    out: List[Dict[str, Any]] = []
    for b in js.get("businesses", []):
        coords = b.get("coordinates") or {}
        loc = b.get("location") or {}
        out.append({
            "id": b.get("id"),
            "source": "yelp",
            "name": b.get("name"),
            "category": "restaurant",
            "address": ", ".join([x for x in [loc.get("address1"), loc.get("city"), loc.get("state"), loc.get("zip_code")] if x]),
            "coord": {"lat": coords.get("latitude"), "lng": coords.get("longitude")},
            "rating": b.get("rating"),
            "review_count": b.get("review_count"),
            "phone": b.get("display_phone"),
            "url": b.get("url"),
            "price_tier": b.get("price"),  # $, $$, ...
            "is_closed": b.get("is_closed"),
            "raw": b,
        })
    return out
