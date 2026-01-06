# hotels.py
"""Hotel search using Gemini + Google Search."""
from __future__ import annotations
import os
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.gemini import GeminiModel

import config

# Google Search via Gemini
GOOGLE_API_KEY = config.get_google_api_key()

class HotelPrice(BaseModel):
    """Hotel price information from Google Search."""
    hotel_name: str
    address: str
    price_per_night: float = Field(..., ge=0, description="Price per night in USD")
    currency: str = "USD"
    check_in: str
    check_out: str
    rating: Optional[float] = Field(None, ge=0, le=5)
    source: str = "google_search"
    booking_url: Optional[str] = None

class HotelSearchResult(BaseModel):
    """Multiple hotel prices."""
    hotels: List[HotelPrice]
    location: str

# Lazy initialization for Gemini agent
_hotel_agent = None

def _get_hotel_agent():
    """Lazy agent initialization for hotel search."""
    global _hotel_agent
    if _hotel_agent is None:
        if not GOOGLE_API_KEY:
            raise ValueError("Missing GOOGLE_API_KEY")
        
        if "GEMINI_API_KEY" not in os.environ:
            os.environ["GEMINI_API_KEY"] = GOOGLE_API_KEY
        
        model = GeminiModel(config.CAR_PRICE_MODEL_NAME)
        _hotel_agent = Agent(
            model=model,
            output_type=HotelSearchResult,
            model_settings={
                "tools": [{"google_search": {}}]
            },
            system_prompt=(
                "You are a hotel price research assistant. Use Google Search to find CURRENT hotel prices.\n"
                "Search for hotels in the specified location for the given check-in and check-out dates.\n"
                "Look for prices from major booking sites (Booking.com, Expedia, Hotels.com, Google Hotels).\n"
                "Return realistic market rates. Include hotel name, address, price per night, rating, and booking URL if available.\n"
                "Return at least 5 hotels if possible."
            ),
        )
    return _hotel_agent

def search_hotels_by_city(city_code, check_in, check_out, adults=2, limit=10):
    """
    Search for hotels using Google Search via Gemini.
    
    Args:
        city_code (str): City name (e.g., 'Durham', 'New York', 'Paris') or airport code
        check_in (str): Check-in date YYYY-MM-DD
        check_out (str): Check-out date YYYY-MM-DD
        adults (int): Number of adults (default: 2) - used in search query
        limit (int): Max number of hotels to fetch (default: 10)
    
    Returns:
        list of dict: [{hotel_id, name, address, price, currency, rating, source, booking_url}, ...]
    """
    try:
        agent = _get_hotel_agent()
        result = agent.run_sync(
            f"Find current hotel prices in {city_code} for check-in {check_in} and check-out {check_out} "
            f"for {adults} adults. Search for at least {limit} hotels with prices from major booking sites. "
            f"Return hotel name, address, price per night in USD, rating, and booking URL."
        )
        
        hotels = result.output.hotels[:limit]
        return [
            {
                "hotel_id": None,
                "name": h.hotel_name,
                "address": h.address,
                "price": h.price_per_night,
                "currency": h.currency,
                "rating": h.rating,
                "source": "google_search",
                "booking_url": h.booking_url,
            }
            for h in hotels
        ]
    except Exception as e:
        print(f"❌ Google Search hotel lookup failed: {e}")
        return []
