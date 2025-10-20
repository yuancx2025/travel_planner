# agent/budget_manager.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import math
import random

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

# --- Import ONLY your tool entrypoints (no other local files) ---
# Expect these tools to return lists of dicts with a "price" sub-dict when applicable
from tools.flight import search_flights_by_route
from tools.hotels import search_hotels
from tools.car_rental import search_car_rentals
from tools.dining import search_dining
from tools.fuel_price import get_state_gas_prices


# =========================
# Models & Contracts (USD)
# =========================

class MoneyUSD(BaseModel):
    currency: str = Field(default="USD", pattern="USD")
    amount: float
    includes_tax: bool = False
    per: str = Field(default="unit")  # ticket | room | vehicle | meal | gallon | trip | day | unit
    quantity: float = 1.0
    ttl_s: int = 600

class BudgetLine(BaseModel):
    category: str  # "flight" | "hotel" | "car" | "fuel" | "dining"
    label: str
    money_usd: float
    qty: float
    details: Dict[str, Any] = Field(default_factory=dict)

class BudgetSummary(BaseModel):
    optimistic_usd: float
    expected_usd: float
    pessimistic_usd: float
    lines: List[BudgetLine]
    assumptions: Dict[str, Any]

class Itinerary(BaseModel):
    # Flight
    dep_iata: str
    arr_iata: str
    depart_date: Optional[str] = None     # "YYYY-MM-DD" - informative only
    return_date: Optional[str] = None     # optional round trip
    pax: int = 1

    # Lodging (US city text)
    city: str
    checkin: str                          # "YYYY-MM-DD"
    checkout: str                         # "YYYY-MM-DD"

    # Dining model
    diners_per_day: int = 2
    meals_per_person_per_day: int = 2
    dining_price_tier: str = "$$"         # $, $$, $$$, $$$$

    # Car rental (optional)
    pickup_iata: Optional[str] = None
    dropoff_iata: Optional[str] = None
    car_start_iso: Optional[str] = None   # "YYYY-MM-DDTHH:MM:SSZ"
    car_end_iso: Optional[str] = None

    # Fuel model (optional)
    fuel_state: Optional[str] = None      # e.g., "VA"
    expected_miles: Optional[float] = None
    vehicle_mpg: Optional[float] = 28.0

    # Controls
    seed: Optional[int] = None
    limit: int = 10                       # clamp within function

    # Optional explicit flight price estimate if your flight tool lacks prices
    flight_price_estimate_usd: Optional[float] = None

    @field_validator("limit")
    @classmethod
    def _clamp_limit(cls, v: int) -> int:
        return max(1, min(50, v))


# =========================
# Helpers (no external deps)
# =========================

def _days_between(start_ymd: str, end_ymd: str) -> int:
    ci = datetime.fromisoformat(start_ymd)
    co = datetime.fromisoformat(end_ymd)
    return max((co - ci).days, 1)

def _pick_cheapest(items: List[dict], seed: Optional[int] = None) -> Optional[dict]:
    """Deterministic-ish cheapest picker with stable tiebreaks."""
    if not items:
        return None
    def amt(x: dict) -> float:
        p = x.get("price") or x.get("total_price") or {}
        a = p.get("amount")
        return float(a) if isinstance(a, (int, float)) else math.inf
    items_sorted = sorted(items, key=lambda x: (amt(x), str(x.get("id",""))))
    if seed is not None:
        random.Random(seed).shuffle(items_sorted[:3])  # tiny shuffle window for variety
    return items_sorted[0]

def _usd_amount(price_dict: Dict[str, Any]) -> float:
    """Assumes USD; returns 0.0 if malformed."""
    if not price_dict:
        return 0.0
    ccy = (price_dict.get("currency") or "USD").upper()
    if ccy != "USD":
        # US-only scope; if a provider returns non-USD unexpectedly, treat as unsupported (0.0)
        return 0.0
    amt = price_dict.get("amount")
    try:
        return float(amt)
    except Exception:
        return 0.0

def _hotel_nights(checkin: str, checkout: str) -> int:
    return _days_between(checkin, checkout)

def _heuristic_roundtrip_band(total: float) -> tuple[float, float, float]:
    """Return (optimistic, expected, pessimistic) with light slippage for taxes/fees."""
    return (round(total * 0.90, 2), round(total, 2), round(total * 1.15, 2))

def _dining_midpoint_usd(tier: str) -> float:
    # Very simple US heuristics; tune per city later if needed
    table = {"$": 12.0, "$$": 25.0, "$$$": 50.0, "$$$$": 90.0}
    return table.get(tier, 25.0)

def _infer_flight_price_usd(
    dep_iata: str, arr_iata: str, pax: int, explicit_estimate: Optional[float], seed: Optional[int]
) -> tuple[float, Dict[str, Any]]:
    """
    If your flight tool doesn't return prices, apply a simple heuristic:
    - base each-way fare buckets (USD): short=150, medium=220, long=320, ultra=450
    - we don't compute real distance here; we bucket by city-pair popularity proxy (randomized mildly by seed)
    For production, swap to a fare API or pass explicit estimates from your planner.
    """
    if explicit_estimate is not None:
        return explicit_estimate * pax, {"mode": "explicit", "per_ticket_usd": explicit_estimate}

    # Seeded pseudo-bucket (stable per pair)
    key = f"{dep_iata}-{arr_iata}"
    rnd = random.Random(hash(key) ^ (seed or 0))
    bucket = rnd.choice(["short", "medium", "long", "ultra"])
    per = {"short": 150.0, "medium": 220.0, "long": 320.0, "ultra": 450.0}[bucket]
    return per * pax, {"mode": "heuristic_bucket", "bucket": bucket, "per_ticket_usd": per}


# =========================
# Core estimator
# =========================

def estimate_budget(itin: Itinerary) -> BudgetSummary:
    seed = itin.seed
    lines: List[BudgetLine] = []
    total = 0.0
    assumptions: Dict[str, Any] = {
        "currency": "USD",
        "fuel_unit": "gallon",
        "dining_tier": itin.dining_price_tier
    }

    # --- Flights (one-way or round) ---
    # Try to use provider prices if present; otherwise fall back to heuristic / explicit estimate.
    flight_total = 0.0

    # Outbound
    flight_out_list = search_flights_by_route(itin.dep_iata, itin.arr_iata, limit=min(itin.limit, 10))
    best_out = _pick_cheapest(flight_out_list, seed)
    per_ticket_out = None
    if best_out and isinstance(best_out.get("price"), dict):
        per_ticket_out = _usd_amount(best_out["price"])
    if per_ticket_out is None or per_ticket_out == 0.0:
        # fallback
        est, meta = _infer_flight_price_usd(itin.dep_iata, itin.arr_iata, itin.pax, itin.flight_price_estimate_usd, seed)
        flight_total += est
        lines.append(BudgetLine(
            category="flight",
            label=f'{itin.dep_iata}→{itin.arr_iata} {itin.depart_date or ""}'.strip(),
            money_usd=round(est, 2),
            qty=itin.pax,
            details={"pricing": meta, "provider_price_present": bool(best_out and best_out.get("price"))}
        ))
    else:
        subtotal = per_ticket_out * itin.pax
        flight_total += subtotal
        lines.append(BudgetLine(
            category="flight",
            label=f'{itin.dep_iata}→{itin.arr_iata} {itin.depart_date or ""}'.strip(),
            money_usd=round(subtotal, 2),
            qty=itin.pax,
            details={"provider": best_out.get("source"), "id": best_out.get("id")}
        ))

    # Return (optional)
    if itin.return_date:
        flight_ret_list = search_flights_by_route(itin.arr_iata, itin.dep_iata, limit=min(itin.limit, 10))
        best_ret = _pick_cheapest(flight_ret_list, seed)
        per_ticket_ret = None
        if best_ret and isinstance(best_ret.get("price"), dict):
            per_ticket_ret = _usd_amount(best_ret["price"])
        if per_ticket_ret is None or per_ticket_ret == 0.0:
            est, meta = _infer_flight_price_usd(itin.arr_iata, itin.dep_iata, itin.pax, itin.flight_price_estimate_usd, seed)
            flight_total += est
            lines.append(BudgetLine(
                category="flight",
                label=f'{itin.arr_iata}→{itin.dep_iata} {itin.return_date}',
                money_usd=round(est, 2),
                qty=itin.pax,
                details={"pricing": meta, "provider_price_present": bool(best_ret and best_ret.get("price"))}
            ))
        else:
            subtotal = per_ticket_ret * itin.pax
            flight_total += subtotal
            lines.append(BudgetLine(
                category="flight",
                label=f'{itin.arr_iata}→{itin.dep_iata} {itin.return_date}',
                money_usd=round(subtotal, 2),
                qty=itin.pax,
                details={"provider": best_ret.get("source"), "id": best_ret.get("id")}
            ))

    total += flight_total

    # --- Hotel (cheapest acceptable) ---
    nights = _hotel_nights(itin.checkin, itin.checkout)
    hotels = search_hotels(itin.city, itin.checkin, itin.checkout, guests=itin.pax)
    best_h = _pick_cheapest(hotels, seed)
    hotel_total = 0.0
    if best_h:
        per_night = _usd_amount(best_h.get("price", {}))
        hotel_total = per_night * nights
        lines.append(BudgetLine(
            category="hotel",
            label=f'{itin.city} ({nights} nights)',
            money_usd=round(hotel_total, 2),
            qty=nights,
            details={"provider": best_h.get("source","booking"), "stars": best_h.get("stars")}
        ))
    total += hotel_total

    # --- Car rental (optional) ---
    car_total = 0.0
    if itin.car_start_iso and itin.car_end_iso:
        pickup = itin.pickup_iata or itin.dep_iata
        cars = search_car_rentals(pickup, itin.car_start_iso, itin.car_end_iso, itin.dropoff_iata)
        best_car = _pick_cheapest(cars, seed)
        if best_car:
            car_total = _usd_amount(best_car.get("price", {}))
            lines.append(BudgetLine(
                category="car",
                label=f'{pickup} ({itin.car_start_iso}→{itin.car_end_iso})',
                money_usd=round(car_total, 2),
                qty=1,
                details={
                    "provider": best_car.get("source","booking"),
                    "free_cancellation": best_car.get("free_cancellation")
                }
            ))
    total += car_total

    # --- Fuel (optional; uses CollectAPI state price + miles/mpg) ---
    fuel_total = 0.0
    if itin.fuel_state and itin.expected_miles and itin.vehicle_mpg:
        state_prices = get_state_gas_prices(itin.fuel_state)
        # Try common keys in your wrapper's result
        gas_entry = (
            state_prices.get("gasoline")
            or state_prices.get("regular")
            or state_prices.get("state", {}).get("gasoline")
            or {}
        )
        per_gallon = _usd_amount(gas_entry if isinstance(gas_entry, dict) else {})
        gallons = float(itin.expected_miles) / float(itin.vehicle_mpg)
        fuel_total = per_gallon * gallons
        lines.append(BudgetLine(
            category="fuel",
            label=f'Fuel in {itin.fuel_state} (~{max(1,int(gallons))} gal)',
            money_usd=round(fuel_total, 2),
            qty=gallons,
            details={"per_gallon_usd": round(per_gallon, 3), "mpg": itin.vehicle_mpg}
        ))
    total += fuel_total

    # --- Dining (modelled per tier) ---
    dining_total = 0.0
    if itin.diners_per_day > 0 and itin.meals_per_person_per_day > 0:
        days = max(_days_between(itin.checkin, itin.checkout), 1)
        meals = itin.diners_per_day * itin.meals_per_person_per_day * days
        per_meal = _dining_midpoint_usd(itin.dining_price_tier)
        dining_total = per_meal * meals
        lines.append(BudgetLine(
            category="dining",
            label=f'{meals} meals ({itin.dining_price_tier})',
            money_usd=round(dining_total, 2),
            qty=meals,
            details={"model": "tier_midpoint_v1", "per_meal_usd": per_meal}
        ))
    total += dining_total

    # --- Uncertainty band (simple; US taxes/fees slippage) ---
    opt, exp, pes = _heuristic_roundtrip_band(total)

    return BudgetSummary(
        optimistic_usd=opt,
        expected_usd=exp,
        pessimistic_usd=pes,
        lines=lines,
        assumptions=assumptions
    )


# =========================
# FastAPI surface (deploy)
# =========================

app = FastAPI(title="Budget Manager Agent (US-only, USD)", version="v1")

class BudgetRequest(BaseModel):
    itinerary: Itinerary

@app.post("/budget/estimate", response_model=BudgetSummary)
def budget_estimate(req: BudgetRequest):
    try:
        return estimate_budget(req.itinerary)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
