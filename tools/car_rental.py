# tools/car_rental.py
"""
Car Rental tool via RapidAPI (Booking.com Demand API proxy).

Provider: booking-comXX.p.rapidapi.com
Endpoint: auto-discovered among common variants (e.g., /car/available-car, /car/avaliable-car)

Usage:
    from tools.car_rental import search_car_rentals
    cars = search_car_rentals(
        pickup_lat=37.6152, pickup_lon=-122.3899,
        pickup_date="2025-11-03", pickup_time="10:00",
        dropoff_lat=37.6152, dropoff_lon=-122.3899,
        dropoff_date="2025-11-05", dropoff_time="10:00",
        currency_code="USD", driver_age=30, language_code="en-us",
        pickup_loc_name="San Francisco International Airport",
        dropoff_loc_name="San Francisco International Airport",
        top_n=10
    )
    # returns list of { id, source, supplier, vehicle: {...}, price: {...}, pickup:{...}, dropoff:{...}, raw }
"""

from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import httpx

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY") or os.getenv("RAPID_API_KEY")

HOST_ENV = os.getenv("RAPIDAPI_BOOKING_CAR_HOST")
PATH_ENV = os.getenv("RAPIDAPI_BOOKING_CAR_PATH")
DEFAULT_HOST_CANDIDATES = [
    "booking-com18.p.rapidapi.com",
    "booking-com15.p.rapidapi.com"
]
DEFAULT_PATH_CANDIDATES = [
    "/car/available-car",
    "/car/avaliable-car",
    "/car/available",
    "/car/avaliable",
]
TIMEOUT_S = 15
RETRIES = 3  # retry policy for rate-limits
PAGE_SIZE = 20  # assume provider returns ~20 items per page; adjust if needed

class CarRentalError(Exception):
    """Exception type for car-rental tool failures."""
    pass

# --- helpers ---
def _iso_date(s: str) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except Exception as e:
        raise CarRentalError("pickup_date/dropoff_date must be YYYY-MM-DD") from e

def _hhmmss(s: str) -> str:
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

def _validate_lat_lng(lat: Any, lng: Any) -> Tuple[float, float]:
    try:
        lat_f = float(lat); lng_f = float(lng)
    except Exception:
        raise CarRentalError("lat/lng must be numeric")
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        raise CarRentalError("lat ∈ [-90,90], lng ∈ [-180,180]")
    return lat_f, lng_f

def _price_num(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None

# --- core service ---
class CarRentalService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or RAPIDAPI_KEY
        if not self.api_key or len(self.api_key) < 20:
            raise CarRentalError("Missing or invalid RAPIDAPI_KEY in environment or constructor")

        host_candidates = [HOST_ENV] + DEFAULT_HOST_CANDIDATES if HOST_ENV else DEFAULT_HOST_CANDIDATES[:]
        path_candidates = [PATH_ENV] + DEFAULT_PATH_CANDIDATES if PATH_ENV else DEFAULT_PATH_CANDIDATES[:]
        # deduplicate while preserving order
        self._host_candidates: List[str] = [h for i, h in enumerate(host_candidates) if h and h not in host_candidates[:i]]
        self._path_candidates: List[str] = [p for i, p in enumerate(path_candidates) if p and p not in path_candidates[:i]]

        self.headers = {"X-RapidAPI-Key": self.api_key}
        self._resolved_host: Optional[str] = HOST_ENV
        self._resolved_path: Optional[str] = PATH_ENV
        if self._resolved_host:
            self.headers["X-RapidAPI-Host"] = self._resolved_host

    def find_available_cars(
        self,
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
    ) -> List[Dict[str, Any]]:
        p_lat, p_lng = _validate_lat_lng(pickup_lat, pickup_lon)
        d_lat, d_lng = _validate_lat_lng(dropoff_lat, dropoff_lon)
        p_date = _iso_date(pickup_date)
        d_date = _iso_date(dropoff_date)
        p_time = _hhmmss(pickup_time)
        d_time = _hhmmss(dropoff_time)

        try:
            pickup_dt = datetime.fromisoformat(f"{p_date}T{p_time}")
            dropoff_dt = datetime.fromisoformat(f"{d_date}T{d_time}")
            if dropoff_dt <= pickup_dt:
                raise CarRentalError("dropoff must be after pickup")
            dur_hours = (dropoff_dt - pickup_dt).total_seconds() / 3600.0
            dur_days = dur_hours / 24.0
        except ValueError as e:
            raise CarRentalError("Invalid pickup/dropoff datetime") from e

        params_base = {
            "pickup_latitude": p_lat,
            "pickup_longtitude": p_lng,    # note provider typo
            "pickup_date": p_date,
            "pickup_time": p_time,
            "dropoff_latitude": d_lat,
            "dropoff_longtitude": d_lng,   # note provider typo
            "drop_date": d_date,           # provider key
            "drop_time": d_time,
            "currency_code": currency_code,
        }
        if driver_age is not None:
            params_base["driver_age"] = int(driver_age)
        if language_code:
            params_base["languagecode"] = language_code
        if pickup_loc_name:
            params_base["pickup_location"] = pickup_loc_name
        if dropoff_loc_name:
            params_base["dropoff_location"] = dropoff_loc_name

        results: List[Dict[str, Any]] = []
        # pagination loop
        page = 1
        self._ensure_endpoint(params_base)
        while len(results) < top_n:
            params = {**params_base, "page": page, "limit": PAGE_SIZE}
            if not self._resolved_host or not self._resolved_path:
                raise CarRentalError("RapidAPI car rental endpoint could not be resolved")
            url = f"https://{self._resolved_host}{self._resolved_path}"
            self.headers["X-RapidAPI-Host"] = self._resolved_host
            response = self._http_get_json(url, params=params)
            page_items = self._extract_results(response)
            if not page_items:
                break
            results.extend(page_items)
            if len(page_items) < PAGE_SIZE:
                break
            page += 1

        # normalize + sort + slice
        normalized = self._normalize_results(results, duration_hours=dur_hours, duration_days=dur_days)
        normalized.sort(key=lambda x: (x.get("price", {}).get("amount") is None, x.get("price", {}).get("amount", float("inf"))))
        return normalized[:top_n]

    def _ensure_endpoint(self, params_base: Dict[str, Any]) -> None:
        if self._resolved_host and self._resolved_path:
            return
        probe_params = {**params_base, "page": 1, "limit": 1}
        last_err: Optional[Exception] = None
        for host in self._host_candidates:
            self.headers["X-RapidAPI-Host"] = host
            for path in self._path_candidates:
                url = f"https://{host}{path}"
                try:
                    self._http_get_json(url, params=probe_params)
                    self._resolved_host = host
                    self._resolved_path = path
                    return
                except CarRentalError as e:
                    msg = str(e)
                    if "404" in msg and ("does not exist" in msg or "Not Found" in msg):
                        last_err = e
                        continue
                    last_err = e
                    if "HTTP 401" in msg or "HTTP 403" in msg:
                        raise
                    # Other errors (e.g., 400) might be due to params; keep searching but remember last error
                    continue
        if last_err:
            raise last_err
        raise CarRentalError("Unable to determine RapidAPI car rental endpoint")

    def _http_get_json(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        last_err = None
        backoff = 1.0
        for attempt in range(1 + RETRIES):
            try:
                with httpx.Client(timeout=TIMEOUT_S) as client:
                    resp = client.get(url, headers=self.headers, params=params)
                    if resp.status_code in (400, 401, 403, 404):
                        raise CarRentalError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    if resp.status_code == 429 or resp.status_code >= 500:
                        if attempt < RETRIES:
                            time.sleep(backoff)
                            backoff *= 2
                            continue
                        else:
                            raise CarRentalError(f"HTTP {resp.status_code} after retries: {resp.text[:200]}")
                    resp.raise_for_status()
                    return resp.json()
            except Exception as e:
                last_err = e
        raise CarRentalError(f"HTTP error calling {url} after {RETRIES + 1} attempts: {last_err}")

    @staticmethod
    def _extract_results(api_resp: Any) -> List[Dict[str, Any]]:
        # Flatten provider variant A/B
        data = api_resp.get("data") or api_resp
        if isinstance(data, dict) and isinstance(data.get("search_results"), list):
            return data["search_results"]
        if isinstance(data, list):
            return data
        # fallback: other key
        return []

    @staticmethod
    def _normalize_results(
        items: List[Dict[str, Any]],
        *,
        duration_hours: Optional[float] = None,
        duration_days: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in items:
            try:
                pricing = item.get("pricing_info") or {}
                amount = _price_num(pricing.get("drive_away_price") or item.get("price") or 0.0)
                currency = pricing.get("currency") or item.get("currency") or "USD"
                supplier = (item.get("supplier_info") or {}).get("name") or item.get("supplier") or "unknown"
                vehicle_info = item.get("vehicle_info") or item.get("vehicle") or {}
                route = item.get("route_info") or item
                pickup = route.get("pickup") or {}
                dropoff = route.get("dropoff") or {}

                out.append({
                    "id": item.get("offer_id") or item.get("id"),
                    "source": "booking-rapidapi",
                    "supplier": supplier,
                    "vehicle": {
                        "name": vehicle_info.get("v_name") or vehicle_info.get("name") or vehicle_info.get("vehicle_name") or "N/A",
                        "group": vehicle_info.get("group") or vehicle_info.get("type") or "N/A",
                        "doors": vehicle_info.get("doors"),
                        "seats": vehicle_info.get("seats"),
                        "transmission": vehicle_info.get("transmission"),
                        "air_conditioning": vehicle_info.get("air_conditioning"),
                        "image_url": vehicle_info.get("image_url"),
                    },
                    "pickup": {
                        "name": pickup.get("name") or pickup.get("location_name") or "N/A",
                        "lat": pickup.get("latitude"),
                        "lng": pickup.get("longitude"),
                        "datetime": pickup.get("datetime"),
                    },
                    "dropoff": {
                        "name": dropoff.get("name") or dropoff.get("location_name") or "N/A",
                        "lat": dropoff.get("latitude"),
                        "lng": dropoff.get("longitude"),
                        "datetime": dropoff.get("datetime"),
                    },
                    "price": {
                        "amount": amount,
                        "currency": currency,
                        "duration_hours": duration_hours,
                        "duration_days": duration_days,
                    },
                    "raw": item,
                })
            except Exception:
                # Skip invalid entries silently
                continue
        return out

# --- convenience function ---
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

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Car Rental via RapidAPI (Booking.com proxy)")
    parser.add_argument("--pickup-lat", type=float, required=True)
    parser.add_argument("--pickup-lon", type=float, required=True)
    parser.add_argument("--pickup-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--pickup-time", type=str, required=True, help="HH:MM or HH:MM:SS")
    parser.add_argument("--dropoff-lat", type=float, required=True)
    parser.add_argument("--dropoff-lon", type=float, required=True)
    parser.add_argument("--dropoff-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--dropoff-time", type=str, required=True, help="HH:MM or HH:MM:SS")
    parser.add_argument("--currency", type=str, default="USD")
    parser.add_argument("--driver-age", type=int, default=None)
    parser.add_argument("--lang", type=str, default="en-us")
    parser.add_argument("--pickup-name", type=str, default=None)
    parser.add_argument("--dropoff-name", type=str, default=None)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    rows = search_car_rentals(
        pickup_lat=args.pickup_lat, pickup_lon=args.pickup_lon,
        pickup_date=args.pickup_date, pickup_time=args.pickup_time,
        dropoff_lat=args.dropoff_lat, dropoff_lon=args.dropoff_lon,
        dropoff_date=args.dropoff_date, dropoff_time=args.dropoff_time,
        currency_code=args.currency,
        driver_age=args.driver_age,
        language_code=args.lang,
        pickup_loc_name=args.pickup_name,
        dropoff_loc_name=args.dropoff_name,
        top_n=args.top_n,
    )
    print(json.dumps(rows, indent=2))
