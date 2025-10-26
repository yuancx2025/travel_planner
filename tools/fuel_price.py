# tools/fuel_price.py
"""Simplified fuel price estimates for US locations."""
from __future__ import annotations
import os, httpx
from typing import Dict, Any

GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

class FuelPriceError(Exception):
    pass

def get_fuel_prices(location: str) -> Dict[str, Any]:
    """
    Get estimated fuel prices for a US location.
    Args:
        location: City or state (e.g., "San Francisco", "CA")
    Returns:
        {"location": str, "state": str, "regular": float, "midgrade": float, 
         "premium": float, "diesel": float, "currency": "USD", "unit": "per gallon"}
    """
    if not GOOGLE_API_KEY:
        raise FuelPriceError("Missing GOOGLE_MAPS_API_KEY")
    
    # Geocode to get state
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    with httpx.Client(timeout=10) as client:
        r = client.get(url, params={"address": location, "key": GOOGLE_API_KEY})
        r.raise_for_status()
        data = r.json()
    
    if data.get("status") != "OK":
        raise FuelPriceError(f"Geocoding failed for '{location}'")
    
    # Extract state code
    state_code = "US"
    for comp in data["results"][0].get("address_components", []):
        if "administrative_area_level_1" in comp.get("types", []):
            state_code = comp.get("short_name", "US")
            break
    
    # State-based pricing (Oct 2025 estimates)
    base = 3.053  # AAA national average for REGULAR on 2025-10-26
    adjustments = {
        "CA": 1.54, "HI": 1.43, "WA": 1.29, "OR": 0.89, "NV": 0.75,
        "AK": 0.77, "NY": 0.06, "CT": -0.02, "IL": 0.19, "PA": 0.18,
        "TX": -0.44, "OK": -0.44, "MS": -0.46, "LA": -0.45, "SC": -0.32,
    }
    regular = round(base + adjustments.get(state_code, 0.0), 2)
    
    return {
        "location": location,
        "state": state_code,
        "regular": regular,
        "midgrade": round(regular + 0.30, 2),
        "premium": round(regular + 0.60, 2),
        "diesel": round(regular + 0.40, 2),
        "currency": "USD",
        "unit": "per gallon",
        "source": "estimate",
    }

def get_state_gas_prices(state_code: str) -> Dict[str, Any]:
    """Legacy function for backward compatibility."""
    return get_fuel_prices(state_code)
