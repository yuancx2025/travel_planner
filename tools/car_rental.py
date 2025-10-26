# tools/car_rental.py
"""
Car Rental tool via RapidAPI (Booking.com Demand API proxy).

Provider: booking-com-api5.p.rapidapi.com
Endpoint: /car/avaliable-car  (provider's spelling)

Usage:
  from tools.car_rental import search_car_rentals
  cars = search_car_rentals(
      pickup_lat=37.6152, pickup_lon=-122.3899,   # SFO
      pickup_date="2025-11-03", pickup_time="10:00",
      dropoff_lat=37.6152, dropoff_lon=-122.3899, # same location
      dropoff_date="2025-11-05", dropoff_time="10:00",
      currency_code="USD", driver_age=30, language_code="en-us",
      pickup_loc_name="San Francisco International Airport",
      dropoff_loc_name="San Francisco International Airport",
      top_n=10
  )
  # cars -> list of {car_model, car_group, price, currency, image_url, pickup_location_name, supplier_name}
"""

from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import httpx

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY") or os.getenv("RAPID_API_KEY")

HOST = "booking-com-api5.p.rapidapi.com"
PATH = "/car/avaliable-car"  # provider spelling
TIMEOUT_S = 15
RETRIES = 2

class CarRentalError(Exception):
    pass

# -------------- Small helpers --------------

def _iso_date(s: str) -> str:
    # Expect YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except Exception as e:
        raise CarRentalError("pickup_date/dropoff_date must be YYYY-MM-DD") from e

def _hhmmss(s: str) -> str:
    # Accept HH:MM or HH:MM:SS → normalize to HH:MM:SS
    parts = s.strip().split(":")
    if len(parts) == 2:
        hh, mm = parts
        ss = "00"
    elif len(parts) == 3:
        hh, mm, ss = parts
    else:
        raise CarRentalError("pickup_time/dropoff_time must be HH:MM or HH:MM:SS")
    hh_i = int(hh); mm_i = int(mm); ss_i = int(ss)
    if not (0 <= hh_i <= 23 and 0 <= mm_i <= 59 and 0 <= ss_i <= 59):
        raise CarRentalError("Invalid time value")
    return f"{hh_i:02d}:{mm_i:02d}:{ss_i:02d}"

def _validate_lat_lng(lat: float, lng: float) -> Tuple[float,float]:
    try:
        lat = float(lat); lng = float(lng)
    except Exception:
        raise CarRentalError("lat/lng must be numeric")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise CarRentalError("lat ∈ [-90,90], lng ∈ [-180,180]")
    return lat, lng

def _price_num(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None

# -------------- Core Service --------------

class CarRentalService:
    """
    Agent-friendly wrapper for the RapidAPI Booking.com car endpoint.
    - Validates inputs
    - Calls API with provider's expected parameter names
    - Normalizes and sorts results by price (ascending)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or RAPIDAPI_KEY
        if not self.api_key or len(self.api_key) < 25:
            raise CarRentalError("Missing or invalid RAPIDAPI_KEY in environment or constructor")

        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": HOST,
        }

    def find_available_cars(
        self,
        *,
        pickup_lat: float, pickup_lon: float,
        pickup_date: str, pickup_time: str,   # "YYYY-MM-DD", "HH:MM" or "HH:MM:SS"
        dropoff_lat: float, dropoff_lon: float,
        dropoff_date: str, dropoff_time: str,
        currency_code: str = "USD",
        driver_age: Optional[int] = None,
        language_code: Optional[str] = "en-us",
        pickup_loc_name: Optional[str] = None,
        dropoff_loc_name: Optional[str] = None,
        top_n: int = 10,
    ) -> List[Dict[str, Any]]:
        # ---- validate / normalize ----
        p_lat, p_lng = _validate_lat_lng(pickup_lat, pickup_lon)
        d_lat, d_lng = _validate_lat_lng(dropoff_lat, dropoff_lon)
        p_date = _iso_date(pickup_date)
        d_date = _iso_date(dropoff_date)
        p_time = _hhmmss(pickup_time)
        d_time = _hhmmss(dropoff_time)
        if not currency_code:
            currency_code = "USD"

        # ---- provider expects these exact spellings ----
        params = {
            "pickup_latitude": p_lat,
            "pickup_longtitude": p_lng,  # provider typo
            "pickup_date": p_date,
            "pickup_time": p_time,
            "dropoff_latitude": d_lat,
            "dropoff_longtitude": d_lng,  # provider typo
            "drop_date": d_date,          # provider key
            "drop_time": d_time,          # provider key
            "currency_code": currency_code,
        }
        if driver_age is not None:  params["driver_age"] = int(driver_age)
        if language_code:           params["languagecode"] = language_code
        if pickup_loc_name:         params["pickup_location"] = pickup_loc_name
        if dropoff_loc_name:        params["dropoff_location"] = dropoff_loc_name

        url = f"https://{HOST}{PATH}"
        data = self._http_get_json(url, params)
        cars = self._normalize_results(data)
        cars.sort(key=lambda x: (x.get("price") is None, x.get("price", 9e18)))  # None → end
        return cars[: max(1, min(top_n, 50))]

    # ------------ internals ------------

    def _http_get_json(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        last_err = None
        for _ in range(1 + RETRIES):
            try:
                with httpx.Client(timeout=TIMEOUT_S) as client:
                    resp = client.get(url, headers=self.headers, params=params)
                    resp.raise_for_status()
                    return resp.json()
            except Exception as e:
                last_err = e
                time.sleep(0.4)
        raise CarRentalError(f"HTTP error calling RapidAPI: {last_err}")

    @staticmethod
    def _normalize_results(api_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Expected shape: {"data": {"search_results": [ ... ]}}
        results = (
            api_resp.get("data", {}).get("search_results", [])
            if isinstance(api_resp, dict) else []
        )
        if not isinstance(results, list):
            return []

        out: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                pricing = item.get("pricing_info", {}) or {}
                vehicle = item.get("vehicle_info", {}) or {}
                supplier = item.get("supplier_info", {}) or {}
                route    = item.get("route_info", {}) or {}
                pickup   = route.get("pickup", {}) or {}

                price = _price_num(pricing.get("drive_away_price"))
                out.append({
                    "car_model": vehicle.get("v_name") or vehicle.get("name") or "N/A",
                    "car_group": vehicle.get("group") or "N/A",
                    "price": price,
                    "currency": pricing.get("currency") or "USD",
                    "image_url": vehicle.get("image_url"),
                    "pickup_location_name": pickup.get("name") or "N/A",
                    "supplier_name": supplier.get("name") or "N/A",
                })
            except Exception:
                # Skip malformed items; we never raise on a single bad row
                continue
        return out

# -------------- Convenience function (for agents) --------------

def search_car_rentals(
    *,
    pickup_lat: float, pickup_lon: float,
    pickup_date: str, pickup_time: str,
    dropoff_lat: float, dropoff_lon: float,
    dropoff_date: str, dropoff_time: str,
    currency_code: str = "USD",
    driver_age: Optional[int] = None,
    language_code: Optional[str] = "en-us",
    pickup_loc_name: Optional[str] = None,
    dropoff_loc_name: Optional[str] = None,
    top_n: int = 10,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Flat wrapper your agents can call directly (keeps call-sites tidy).
    """
    svc = CarRentalService(api_key=api_key)
    return svc.find_available_cars(
        pickup_lat=pickup_lat, pickup_lon=pickup_lon,
        pickup_date=pickup_date, pickup_time=pickup_time,
        dropoff_lat=dropoff_lat, dropoff_lon=dropoff_lon,
        dropoff_date=dropoff_date, dropoff_time=dropoff_time,
        currency_code=currency_code, driver_age=driver_age,
        language_code=language_code, pickup_loc_name=pickup_loc_name,
        dropoff_loc_name=dropoff_loc_name, top_n=top_n
    )

# -------------- CLI (manual smoke test) --------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Car Rental via RapidAPI (Booking.com proxy)")
    p.add_argument("--pickup-lat", type=float, required=True)
    p.add_argument("--pickup-lon", type=float, required=True)
    p.add_argument("--pickup-date", type=str, required=True, help="YYYY-MM-DD")
    p.add_argument("--pickup-time", type=str, required=True, help="HH:MM or HH:MM:SS")
    p.add_argument("--dropoff-lat", type=float, required=True)
    p.add_argument("--dropoff-lon", type=float, required=True)
    p.add_argument("--dropoff-date", type=str, required=True, help="YYYY-MM-DD")
    p.add_argument("--dropoff-time", type=str, required=True, help="HH:MM or HH:MM:SS")
    p.add_argument("--currency", type=str, default="USD")
    p.add_argument("--driver-age", type=int, default=None)
    p.add_argument("--lang", type=str, default="en-us")
    p.add_argument("--pickup-name", type=str, default=None)
    p.add_argument("--dropoff-name", type=str, default=None)
    p.add_argument("--top-n", type=int, default=10)
    args = p.parse_args()

    try:
        rows = search_car_rentals(
            pickup_lat=args.pickup_lat, pickup_lon=args.pickup_lon,
            pickup_date=args.pickup_date, pickup_time=args.pickup_time,
            dropoff_lat=args.dropoff_lat, dropoff_lon=args.dropoff_lon,
            dropoff_date=args.dropoff_date, dropoff_time=args.dropoff_time,
            currency_code=args.currency, driver_age=args.driver_age,
            language_code=args.lang, pickup_loc_name=args.pickup_name,
            dropoff_loc_name=args.dropoff_name, top_n=args.top_n
        )
        print(json.dumps(rows, indent=2))
    except Exception as e:
        print(f"[car-rental error] {e}")
        raise
