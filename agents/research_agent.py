# agents/research_agent.py
"""ResearchAgent: Tool coordinator for travel research."""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from tools.weather import get_weather
from tools.attractions import search_attractions
from tools.dining import search_restaurants
from tools.car_rental import search_car_rentals
from tools.hotels import search_hotels_by_city
from tools.distance_matrix import get_distance_matrix
from tools.fuel_price import get_fuel_prices


class ResearchAgent:
    """Stateless agent that executes tool calls based on user preferences."""

    def __init__(self):
        self._validate_env()

    def _validate_env(self):
        """Check required API keys."""
        missing = []
        if not os.getenv("GOOGLE_MAPS_API_KEY"):
            missing.append("GOOGLE_MAPS_API_KEY")
        if not os.getenv("RAPIDAPI_KEY"):
            missing.append("RAPIDAPI_KEY (for car rentals)")
        if not os.getenv("AMADEUS_API_KEY") or not os.getenv("AMADEUS_API_SECRET"):
            missing.append("AMADEUS_API_KEY/SECRET (for hotels)")
        
        if missing:
            print(f"⚠️  Warning: Missing API keys: {', '.join(missing)}")

    def research(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all research tasks based on user state."""
        results: Dict[str, Any] = {}
        
        # 1. Weather
        if state.get("destination_city") and state.get("start_date") and state.get("travel_days"):
            results["weather"] = self._get_weather(state)
        
        # 2. Attractions
        if state.get("destination_city"):
            results["attractions"] = self._get_attractions(state)
        
        # 3. Dining
        if state.get("destination_city") and state.get("cuisine_pref"):
            results["dining"] = self._get_dining(state)
        
        # 4. Hotels
        if state.get("destination_city") and state.get("start_date"):
            results["hotels"] = self._get_hotels(state)
        
        # 5. Car rentals
        if state.get("need_car_rental") in ("yes", "Yes", True):
            results["car_rentals"] = self._get_car_rentals(state)
        
        # 6. Fuel prices
        if state.get("need_car_rental") in ("yes", "Yes", True) and state.get("destination_city"):
            results["fuel_prices"] = self._get_fuel_prices(state)
        
        # 7. Distances
        if results.get("attractions"):
            results["distances"] = self._get_distances(results["attractions"])
        
        return results

    # ==================== HELPERS ====================

    def _geocode_city(self, city: str) -> Optional[Dict[str, float]]:
        """Get lat/lng for a city."""
        try:
            attractions = search_attractions(city, limit=1)
            if attractions and attractions[0].get("coord"):
                return attractions[0]["coord"]
        except Exception:
            pass
        return None

    def _normalize_date(self, date_str: str) -> str:
        """Normalize date to YYYY-MM-DD."""
        if date_str == "not decided":
            return (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        return date_str
    def _get_weather(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get weather forecast."""
        try:
            return get_weather(
                city=state["destination_city"],
                start_date=self._normalize_date(state["start_date"]),
                duration=int(state.get("travel_days", 3)),
                units=state.get("temp_unit", "fahrenheit")
            )
        except Exception as e:
            return [{"error": f"Weather fetch failed: {e}"}]

    def _get_attractions(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get attractions."""
        try:
            return search_attractions(
                city=state["destination_city"],
                keyword=state.get("attraction_pref", ""),
                limit=8
            )
        except Exception as e:
            return [{"error": f"Attractions fetch failed: {e}"}]

    def _get_dining(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get restaurants."""
        try:
            coords = self._geocode_city(state["destination_city"])
            if not coords:
                return [{"error": "Could not geocode destination"}]
            return search_restaurants(
                lat=coords["lat"],
                lng=coords["lng"],
                radius=5000,
                keyword=state.get("cuisine_pref", "")
            )
        except Exception as e:
            return [{"error": f"Dining fetch failed: {e}"}]

    def _get_hotels(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get hotels."""
        try:
            checkin = self._normalize_date(state["start_date"])
            checkout = (
                datetime.strptime(checkin, "%Y-%m-%d")
                + timedelta(days=int(state.get("travel_days", 3)))
            ).strftime("%Y-%m-%d")
            
            return search_hotels_by_city(
                city_name=state["destination_city"],
                checkin_date=checkin,
                checkout_date=checkout,
                adults=int(state.get("travelers", 1)),
                currency=state.get("currency", "USD"),
                limit=5
            )
        except Exception as e:
            return [{"error": f"Hotels fetch failed: {e}"}]

    def _get_car_rentals(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get car rentals (geocode city to lat/lng)."""
        try:
            coords = self._geocode_city(state["destination_city"])
            if not coords:
                return [{"error": "Could not geocode destination for car rental"}]
            
            checkin = self._normalize_date(state["start_date"])
            checkout = (
                datetime.strptime(checkin, "%Y-%m-%d")
                + timedelta(days=int(state.get("travel_days", 3)))
            ).strftime("%Y-%m-%d")
            
            return search_car_rentals(
                pickup_lat=coords["lat"],
                pickup_lon=coords["lng"],
                pickup_date=checkin,
                pickup_time="10:00",
                dropoff_lat=coords["lat"],
                dropoff_lon=coords["lng"],
                dropoff_date=checkout,
                dropoff_time="10:00",
                currency=state.get("currency", "USD"),
                limit=5
            )
        except Exception as e:
            return [{"error": f"Car rental fetch failed: {e}"}]

    def _get_fuel_prices(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Get fuel price estimates."""
        try:
            return get_fuel_prices(state["destination_city"])
        except Exception as e:
            return {"error": f"Fuel price fetch failed: {e}"}

    def _get_distances(self, attractions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get distances between attractions."""
        coords = [a["coord"] for a in attractions if a.get("coord")][:5]
        if len(coords) < 2:
            return []
        
        origins = [f"{c['lat']},{c['lng']}" for c in coords]
        destinations = origins.copy()
        
        try:
            return get_distance_matrix(origins, destinations, mode="DRIVE")
        except Exception as e:
            return [{"error": f"Distance calc failed: {e}"}]

