# tools/flight.py
from __future__ import annotations
import os, time, random
import httpx
from typing import Any, Dict, List, Optional

AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
TP_TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN")
BASE = "http://api.aviationstack.com/v1"
TP_BASE = "https://api.travelpayouts.com/v2"

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


def _fetch_price_offer(dep_iata: str, arr_iata: str, limit: int) -> Optional[Dict[str, Any]]:
    if not TP_TOKEN:
        return None
    params = {
        "origin": dep_iata,
        "destination": arr_iata,
        "token": TP_TOKEN,
        "currency": "usd",
        "limit": str(limit),
        "page": "1",
    }
    try:
        resp = _request("GET", f"{TP_BASE}/prices/latest", params=params, timeout=25)
    except httpx.HTTPStatusError:
        return None
    data = resp.json()
    if not data.get("success", False):
        return None

    offers_raw = data.get("data") or []
    offers: List[Dict[str, Any]] = []
    if isinstance(offers_raw, list):
        offers = offers_raw
    elif isinstance(offers_raw, dict):
        for val in offers_raw.values():
            if isinstance(val, list):
                offers.extend([item for item in val if isinstance(item, dict)])
            elif isinstance(val, dict):
                offers.append(val)

    if not offers:
        return None

    cheapest = min(
        (offer for offer in offers if offer.get("value") is not None),
        key=lambda offer: offer.get("value", float("inf")),
        default=None,
    )
    if not cheapest:
        return None

    amount = cheapest.get("value")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = None

    if amount is None:
        return None

    return {
        "currency": (data.get("currency") or "USD").upper(),
        "amount": amount,
        "airline": cheapest.get("airline"),
        "depart_date": cheapest.get("depart_date"),
        "return_date": cheapest.get("return_date"),
        "raw": cheapest,
    }

def search_flights_by_route(dep_iata: str, arr_iata: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Provider: Aviationstack /v1/flights
    Returns normalized flight objects (real-time/historical mixed per provider behavior).
    Environment: AVIATIONSTACK_KEY (required), TRAVELPAYOUTS_TOKEN (optional for fare data)
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

    price_offer = _fetch_price_offer(dep_iata, arr_iata, limit)
    if price_offer:
        price_block = {
            "currency": price_offer["currency"],
            "amount": price_offer["amount"],
            "per": "ticket",
            "raw": price_offer["raw"],
        }
        for flight in out:
            flight.setdefault("airline", price_offer.get("airline"))
            flight["price"] = price_block.copy()
            if price_offer.get("depart_date") and "dep_time_scheduled" not in flight:
                flight["depart_date"] = price_offer["depart_date"]
            if price_offer.get("return_date"):
                flight["return_date"] = price_offer["return_date"]
    return out
