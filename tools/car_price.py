# tools/car_price.py
"""Combined fuel prices and car rental rates tool using Gemini + Google Search grounding."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

class CarAndFuelPrices(BaseModel):
    """Combined car rental and fuel price response."""
    location: str
    state: str = Field(..., description="2-letter US state code")
    
    # Fuel prices (USD/gallon)
    regular: float = Field(..., ge=0, description="Regular gas price per gallon")
    midgrade: float = Field(..., ge=0, description="Midgrade gas price per gallon")
    premium: float = Field(..., ge=0, description="Premium gas price per gallon")
    diesel: float = Field(..., ge=0, description="Diesel price per gallon")
    
    # Car rental daily rates (USD/day)
    economy_car_daily: Optional[float] = Field(None, ge=0, description="Economy car rental per day")
    compact_car_daily: Optional[float] = Field(None, ge=0, description="Compact car rental per day")
    midsize_car_daily: Optional[float] = Field(None, ge=0, description="Midsize car rental per day")
    suv_daily: Optional[float] = Field(None, ge=0, description="SUV rental per day")
    
    currency: str = "USD"
    fuel_unit: str = "per gallon"
    rental_unit: str = "per day"
    source: str = "google_search"
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if len(v) != 2 or not v.isupper():
            return "US"  # fallback for unknown locations
        return v

class CarPriceError(Exception):
    """Exception for car/fuel price lookup failures."""
    pass

# Legacy alias for backward compatibility
FuelPriceError = CarPriceError

model = GoogleModel("gemini-2.0-flash-exp")

agent = Agent(
    model=model,
    output_type=CarAndFuelPrices,
    model_settings={
        "tools": [{"google_search": {}}]  # Enable Google Search grounding
    },
    system_prompt=(
        "You are a travel cost assistant. Use Google Search to find CURRENT pricing for:\n"
        "1. Average gas/fuel prices (regular, midgrade, premium, diesel) in USD per gallon\n"
        "2. Average car rental daily rates for different vehicle classes (economy, compact, midsize, SUV) in USD per day\n\n"
        "Search for typical daily car rental rates from major providers (Enterprise, Hertz, Budget, Avis) "
        "at the requested US location. Extract the 2-letter state code. "
        "Return realistic market rates based on current search results."
    ),
)

@lru_cache(maxsize=32)
def _cached_query(location: str, hour_bucket: str) -> CarAndFuelPrices:
    """Cache results for 1 hour (keyed by hour bucket)."""
    result = agent.run_sync(
        f"What are the current average gas prices AND typical daily car rental rates in {location}, USA? "
        f"Include: (1) regular, midgrade, premium, and diesel fuel prices per gallon in USD, and "
        f"(2) daily rental rates for economy, compact, midsize, and SUV vehicles in USD per day."
    )
    return result.output

def get_car_and_fuel_prices(location: str) -> dict:
    """
    Get current fuel prices AND car rental daily rates using Gemini + Google Search (cached 1 hour).
    Args:
        location: US city or state (e.g., "San Francisco", "CA")
    Returns:
        dict with fuel prices and car rental daily rates
    """
    if not GOOGLE_API_KEY:
        raise CarPriceError("Missing GOOGLE_API_KEY or GEMINI_API_KEY")
    
    # Cache key includes hour to expire every 60 min
    hour_bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    
    try:
        data = _cached_query(location.strip().title(), hour_bucket)
        return data.model_dump()
    except Exception as e:
        raise CarPriceError(f"Failed to get car/fuel prices: {e}")

def get_fuel_prices(location: str) -> dict:
    """
    Legacy function: Get fuel prices only (backward compatibility).
    For new code, use get_car_and_fuel_prices() to get both fuel and rental rates.
    
    Args:
        location: US city or state (e.g., "San Francisco", "CA")
    Returns:
        dict with fuel prices (filters out car rental data)
    """
    full_data = get_car_and_fuel_prices(location)
    # Filter out car rental fields (ending in _daily and rental_unit)
    return {
        k: v for k, v in full_data.items()
        if not k.endswith("_daily") and k != "rental_unit"
    }

def get_state_gas_prices(state_code: str) -> dict:
    """Legacy function (backward compatibility)."""
    return get_fuel_prices(state_code)