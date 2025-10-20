# tools/hotels.py
from __future__ import annotations
import os, time, random
import httpx
from typing import Any, Dict, List, Optional

BK_AFFILIATE_ID = os.environ.get("BK_DEMAND_AFFILIATE_ID")
BK_TOKEN = os.environ.get("BK_DEMAND_TOKEN")
BASE = "https://demandapi.booking.com/3.1"

def _request(method: str, url: str, **kw) -> httpx.Response:
    retries, backoff = 3, 0.7
    last_err = None
    for i in range(retries):
        try:
            with httpx.Client(timeout=kw.pop("timeout", 30)) as c:
                r = c.request(method, url, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                return r
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_err = e
            if i < retries - 1:
                time.sleep(backoff * (2**i) + random.random()*0.3)
            else:
                raise
    raise last_err  # type: ignore

def search_hotels(
    query: str, checkin: str, checkout: str, guests: int = 2, rooms: int = 1, limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Provider: Booking.com Demand API (Accommodations collection).
    Returns normalized hotels with price when available.
    Environment: BK_DEMAND_AFFILIATE_ID, BK_DEMAND_TOKEN
    Notes: You must be a Managed Affiliate; calls are POST+JSON. :contentReference[oaicite:4]{index=4}
    """
    assert BK_AFFILIATE_ID and BK_TOKEN, "Missing BK_DEMAND_AFFILIATE_ID or BK_DEMAND_TOKEN"
    headers = {"Content-Type": "application/json"}
    auth = (BK_AFFILIATE_ID, BK_TOKEN)  # Auth per Demand guide. :contentReference[oaicite:5]{index=5}

    # The exact schema varies by product; this payload follows Booking's "accommodations search" pattern.
    payload: Dict[str, Any] = {
        "method": "accommodations.search",
        "params": {
            "query": query,
            "checkin": checkin,
            "checkout": checkout,
            "guests": guests,
            "rooms": rooms,
            "limit": limit
        }
    }

    r = _request("POST", f"{BASE}/accommodations", json=payload, auth=auth, headers=headers)
    js = r.json()
    out: List[Dict[str, Any]] = []
    for h in js.get("result", []):
        out.append({
            "id": str(h.get("hotel_id") or h.get("id")),
            "source": "booking",
            "name": h.get("name"),
            "address": h.get("address"),
            "city": h.get("city"),
            "country": h.get("country"),
            "stars": h.get("class"),
            "rating": h.get("review_score"),
            "review_count": h.get("review_nr"),
            "price": {
                "currency": h.get("currency", "USD"),
                "amount": h.get("price"),
                "min_amount": h.get("min_total_price"),
                "max_amount": h.get("max_total_price"),
            },
            "url": h.get("url"),
            "raw": h,
        })
    return out
