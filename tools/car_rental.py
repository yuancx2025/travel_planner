# tools/car_rental.py
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

def search_car_rentals(
    pickup_airport_iata: str,
    start_iso: str,
    end_iso: str,
    dropoff_airport_iata: Optional[str] = None,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """
    Provider: Booking.com Demand API /cars
    Returns a list of normalized car offers.
    Environment: BK_DEMAND_AFFILIATE_ID, BK_DEMAND_TOKEN
    """
    assert BK_AFFILIATE_ID and BK_TOKEN, "Missing BK_DEMAND_AFFILIATE_ID or BK_DEMAND_TOKEN"
    headers = {"Content-Type": "application/json"}
    auth = (BK_AFFILIATE_ID, BK_TOKEN)

    legacy_payload: Dict[str, Any] = {
        "method": "cars.search",
        "params": {
            "pickup": {"airport": pickup_airport_iata},
            "dropoff": {"airport": dropoff_airport_iata or pickup_airport_iata},
            "start": start_iso,
            "end": end_iso,
            "limit": limit,
        },
    }
    modern_payload: Dict[str, Any] = {
        "pickup": {"airport": pickup_airport_iata},
        "dropoff": {"airport": dropoff_airport_iata or pickup_airport_iata},
        "start": start_iso,
        "end": end_iso,
        "limit": limit,
    }

    request_options = [
        (f"{BASE}/cars/search", modern_payload),
        (f"{BASE}/cars", legacy_payload),
    ]
    last_err = None
    for idx, (url, body) in enumerate(request_options):
        try:
            r = _request("POST", url, json=body, auth=auth, headers=headers)
            break
        except httpx.HTTPStatusError as exc:
            last_err = exc
            status = getattr(exc.response, "status_code", None)
            if idx < len(request_options) - 1 and status in {400, 404, 422}:
                continue
            raise
    else:
        raise last_err  # type: ignore[misc]

    js = r.json()
    out: List[Dict[str, Any]] = []
    for o in js.get("result", []):
        veh = o.get("vehicle") or {}
        sup = o.get("supplier") or {}
        out.append({
            "id": o.get("offer_id") or o.get("id"),
            "source": "booking",
            "supplier": sup.get("name"),
            "vehicle": {
                "class": veh.get("type"),
                "doors": veh.get("doors"),
                "seats": veh.get("seats"),
                "transmission": veh.get("transmission"),
                "air_conditioning": veh.get("air_conditioning"),
            },
            "pickup": (o.get("pickup") or {}).get("name"),
            "dropoff": (o.get("dropoff") or {}).get("name"),
            "price": {
                "currency": o.get("currency", "USD"),
                "amount": o.get("price"),
            },
            "free_cancellation": o.get("free_cancellation"),
            "raw": o,
        })
    return out
