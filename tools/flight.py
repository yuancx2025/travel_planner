# tools/flight.py
"""Flight search using Gemini + Google Search."""
from __future__ import annotations
import os
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.gemini import GeminiModel

import config

# Google Search via Gemini
GOOGLE_API_KEY = config.get_google_api_key()

class FlightPrice(BaseModel):
    """Flight price information from Google Search."""
    airline: str
    price: float = Field(..., ge=0, description="Total price in USD")
    currency: str = "USD"
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    duration: Optional[str] = None
    stops: Optional[int] = Field(None, ge=0)
    booking_url: Optional[str] = None

class FlightSearchResult(BaseModel):
    """Multiple flight prices."""
    flights: List[FlightPrice]

# Lazy initialization for Gemini agent
_flight_agent = None

def _get_flight_agent():
    """Lazy agent initialization for flight search."""
    global _flight_agent
    if _flight_agent is None:
        if not GOOGLE_API_KEY:
            raise ValueError("Missing GOOGLE_API_KEY")
        
        if "GEMINI_API_KEY" not in os.environ:
            os.environ["GEMINI_API_KEY"] = GOOGLE_API_KEY
        
        model = GeminiModel(config.CAR_PRICE_MODEL_NAME)
        _flight_agent = Agent(
            model=model,
            output_type=FlightSearchResult,
            model_settings={
                "tools": [{"google_search": {}}]
            },
            system_prompt=(
                "You are a flight price research assistant. Use Google Search to find CURRENT flight prices.\n"
                "Search Google Flights, Skyscanner, Kayak, and other flight comparison sites.\n"
                "Return realistic market rates with airline, price, duration, stops, and booking URL.\n"
                "Return at least 5 flight options if possible."
            ),
        )
    return _flight_agent

def search_flights(
    origin,
    destination,
    departure_date,
    return_date=None,
    adults=1,
    max_results=5,
    currency="USD",
):
    """
    Search for flights using Google Search via Gemini.

    Args:
        origin (str): Airport code or city name (e.g., 'JFK', 'New York')
        destination (str): Airport code or city name (e.g., 'LHR', 'London')
        departure_date (str): YYYY-MM-DD
        return_date (str): Optional, for round-trip
        adults (int): Number of adult passengers
        max_results (int): Max number of results to display
        currency (str): Currency for prices

    Returns:
        list of dict: Flight offers with airline, price, duration, route, and booking URL
    """
    try:
        agent = _get_flight_agent()
        query = f"Find current flight prices from {origin} to {destination} on {departure_date}"
        if return_date:
            query += f" returning on {return_date}"
        query += f" for {adults} adult(s). Search Google Flights and flight comparison sites. "
        query += f"Return at least {max_results} options with airline, price in {currency}, duration, stops, and booking URL."
        
        result = agent.run_sync(query)
        flights = result.output.flights[:max_results]
        
        return [
            {
                "carrier": f.airline,
                "price": f.price,
                "currency": f.currency,
                "duration": f.duration,
                "origin": f.origin,
                "destination": f.destination,
                "departure_date": f.departure_date,
                "return_date": f.return_date,
                "stops": f.stops,
                "booking_url": f.booking_url,
                "source": "google_search",
            }
            for f in flights
        ]
    except Exception as e:
        print(f"❌ Google Search flight lookup failed: {e}")
        return []
