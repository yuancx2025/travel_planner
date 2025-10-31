# tools/fuel_price.py
"""Fuel price tool using Gemini + Google Search grounding."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from functools import lru_cache
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
class FuelPrices(BaseModel):
    """Fuel price response (USD/gallon)."""
    location: str
    state: str = Field(..., description="2-letter US state code")
    regular: float = Field(..., ge=0)
    midgrade: float = Field(..., ge=0)
    premium: float = Field(..., ge=0)
    diesel: float = Field(..., ge=0)
    currency: str = "USD"
    unit: str = "per gallon"
    source: str = "google_search"
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if len(v) != 2 or not v.isupper():
            return "US"  # fallback for unknown locations
        return v

class FuelPriceError(Exception):
    pass

model = GoogleModel("gemini-2.0-flash-exp")

agent = Agent(
    model=model,
    output_type=FuelPrices,
    model_settings={
        "tools": [{"google_search": {}}]  # Enable Google Search grounding
    },
    system_prompt=(
        "You are a fuel price assistant. Use Google Search to find CURRENT average gas prices "
        "for the requested US location. Return prices in USD per gallon. "
        "Provide regular, midgrade, premium, and diesel prices. "
        "Extract the 2-letter state code from the location."
    ),
)

@lru_cache(maxsize=32)
def _cached_query(location: str, hour_bucket: str) -> FuelPrices:
    """Cache results for 1 hour (keyed by hour bucket)."""
    result = agent.run_sync(
        f"What are the current average gas prices in {location}, USA? "
        f"Include regular, midgrade, premium, and diesel prices per gallon in USD."
    )
    return result.output

def get_fuel_prices(location: str) -> dict:
    """
    Get current fuel prices using Gemini + Google Search (cached 1 hour).
    Args:
        location: US city or state (e.g., "San Francisco", "CA")
    Returns:
        dict with fuel prices
    """
    if not GOOGLE_API_KEY:
        raise FuelPriceError("Missing GOOGLE_API_KEY or GEMINI_API_KEY")
    
    # Cache key includes hour to expire every 60 min
    hour_bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    
    try:
        data = _cached_query(location.strip().title(), hour_bucket)
        return data.model_dump()
    except Exception as e:
        raise FuelPriceError(f"Failed to get fuel prices: {e}")

def get_state_gas_prices(state_code: str) -> dict:
    """Legacy function (backward compatibility)."""
    return get_fuel_prices(state_code)