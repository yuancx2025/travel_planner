# agents/research_agent.py
"""ResearchAgent: Tool coordinator for travel research."""
from __future__ import annotations
import os
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from tools.weather import get_weather
from tools.attractions import search_attractions
from tools.dining import search_restaurants
from tools.hotels import search_hotels_by_city
from tools.distance_matrix import get_distance_matrix
from tools.car_price import get_car_and_fuel_prices


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

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(status, int) and status in {429, 500, 502, 503, 504}:
            return True

        text = str(exc).lower()
        retry_tokens = (
            " 429",
            " 500",
            " 502",
            " 503",
            " 504",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
        )
        return any(token in text for token in retry_tokens)

    def _concurrency_limit(self) -> int:
        try:
            return max(1, int(os.getenv("RESEARCH_MAX_CONCURRENCY", "5")))
        except ValueError:
            return 5

    async def _call_with_retries(self, func, *args, **kwargs):
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(self._is_retryable_error),
            wait=wait_exponential(min=0.5, max=6),
            stop=stop_after_attempt(3),
            reraise=True,
        ):
            with attempt:
                return await asyncio.to_thread(func, *args, **kwargs)

    def research(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all research tasks based on user state."""
        destination = (state.get("destination_city") or "").strip()
        if not destination:
            return {}

        clean_state = dict(state)
        clean_state["destination_city"] = destination

        try:
            return asyncio.run(self._research_async(clean_state))
        except RuntimeError as exc:
            message = str(exc)
            if "asyncio.run" in message and "event loop" in message:
                raise RuntimeError(
                    "ResearchAgent.research() cannot be called from an active event loop. "
                    "Use await research_async(...) instead."
                ) from exc
            raise

    async def research_async(self, state: Dict[str, Any]) -> Dict[str, Any]:
        destination = (state.get("destination_city") or "").strip()
        if not destination:
            return {}

        clean_state = dict(state)
        clean_state["destination_city"] = destination

        return await self._research_async(clean_state)

    async def _research_async(self, state: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        semaphore = asyncio.Semaphore(self._concurrency_limit())

        async def run(func, *args, **kwargs):
            async with semaphore:
                return await self._call_with_retries(func, *args, **kwargs)

        async def run_weather():
            if state.get("start_date") and state.get("travel_days"):
                return await run(self._get_weather, state)
            return None

        async def run_attractions():
            return await run(self._get_attractions, state)

        async def run_hotels():
            if state.get("start_date"):
                return await run(self._get_hotels, state)
            return None

        attractions_task = asyncio.create_task(run_attractions())
        weather_task = asyncio.create_task(run_weather())
        hotels_task = asyncio.create_task(run_hotels())

        async def run_dining():
            if not state.get("cuisine_pref"):
                return None
            try:
                attractions_result = await attractions_task
            except Exception:
                return None
            if not attractions_result:
                return None
            return await run(self._get_dining, state, attractions_result)

        async def run_distances():
            try:
                attractions_result = await attractions_task
            except Exception:
                return None
            if not attractions_result:
                return None
            return await run(self._get_distances, attractions_result)

        dining_task = asyncio.create_task(run_dining())
        distances_task = asyncio.create_task(run_distances())

        task_map = {
            "weather": weather_task,
            "attractions": attractions_task,
            "dining": dining_task,
            "hotels": hotels_task,
            "distances": distances_task,
        }

        task_results = await asyncio.gather(*task_map.values(), return_exceptions=True)
        task_outputs = dict(zip(task_map.keys(), task_results))

        weather_result = task_outputs["weather"]
        if isinstance(weather_result, Exception):
            results["weather"] = [{"error": f"Weather fetch failed: {weather_result}"}]
        elif weather_result is not None:
            results["weather"] = weather_result

        attractions_result = task_outputs["attractions"]
        if isinstance(attractions_result, Exception):
            results["attractions"] = [{"error": f"Attractions fetch failed: {attractions_result}"}]
            attractions_result = []
        else:
            results["attractions"] = attractions_result or []

        dining_result = task_outputs["dining"]
        if isinstance(dining_result, Exception):
            results["dining"] = [{"error": f"Dining fetch failed: {dining_result}"}]
        elif dining_result:
            results["dining"] = dining_result

        hotels_result = task_outputs["hotels"]
        if isinstance(hotels_result, Exception):
            results["hotels"] = [{"error": f"Hotels fetch failed: {hotels_result}"}]
        elif hotels_result:
            results["hotels"] = hotels_result

        distances_result = task_outputs["distances"]
        if isinstance(distances_result, Exception):
            results["distances"] = [{"error": f"Distance calc failed: {distances_result}"}]
        elif distances_result:
            results["distances"] = distances_result

        if state.get("need_car_rental") in ("yes", "Yes", True):
            cars = await self._call_with_retries(self._get_car_rentals, state)
            if cars:
                results["car_rentals"] = cars

            fuel = await self._call_with_retries(self._get_fuel_prices, state)
            if fuel:
                results["fuel_prices"] = fuel

        return results

    # ==================== HELPERS ====================

    def _geocode_city(self, city: str) -> Optional[Dict[str, float]]:
        """Get lat/lng for a city."""
        query = f"{city} attractions"
        try:
            attractions = search_attractions(query, limit=1)
            if attractions and attractions[0].get("coord"):
                return attractions[0]["coord"]
        except Exception:
            pass
        return None

    def _normalize_date(self, date_str: Optional[str]) -> str:
        """Normalize date to YYYY-MM-DD."""
        if not date_str or date_str == "not decided":
            return (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        return date_str

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return max(1, int(float(value)))
        except Exception:
            return default

    def _trip_window(self, state: Dict[str, Any]) -> Tuple[str, str, int]:
        checkin = self._normalize_date(state.get("start_date"))
        duration = self._safe_int(state.get("travel_days"), 3)
        checkout = (
            datetime.strptime(checkin, "%Y-%m-%d")
            + timedelta(days=duration)
        ).strftime("%Y-%m-%d")
        return checkin, checkout, duration

    def _get_weather(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get weather forecast."""
        try:
            units = str(state.get("temp_unit", "imperial")).lower()
            units = "metric" if units.startswith("c") else "imperial"
            return get_weather(
                city=state["destination_city"],
                start_date=self._normalize_date(state["start_date"]),
                duration=self._safe_int(state.get("travel_days"), 3),
                units=units
            )
        except Exception as e:
            return [{"error": f"Weather fetch failed: {e}"}]

    def _get_attractions(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get attractions."""
        try:
            coords = self._geocode_city(state["destination_city"])
            query_parts = [state["destination_city"]]
            if state.get("activity_pref"):
                query_parts.append(f"{state['activity_pref']} activities")
            query_parts.append("attractions")
            query = " ".join(part for part in query_parts if part).strip()

            search_kwargs: Dict[str, Any] = {"limit": 10}
            if coords:
                search_kwargs.update({
                    "lat": coords["lat"],
                    "lng": coords["lng"],
                    "radius_m": 20000,
                })
            return search_attractions(query or state["destination_city"], **search_kwargs)
        except Exception as e:
            return [{"error": f"Attractions fetch failed: {e}"}]

    def _get_dining(self, state: Dict[str, Any], attractions: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Get restaurants."""
        try:
            coords = self._geocode_city(state["destination_city"])
            if not coords and attractions:
                for item in attractions:
                    if item.get("coord"):
                        coords = item["coord"]
                        break
            if not coords:
                return [{"error": "Could not geocode destination"}]

            cuisine = state.get("cuisine_pref", "restaurants")
            query = f"{cuisine} in {state['destination_city']}"
            return search_restaurants(
                query=query,
                lat=coords["lat"],
                lng=coords["lng"],
                radius_m=5000,
                limit=10
            )
        except Exception as e:
            return [{"error": f"Dining fetch failed: {e}"}]

    def _get_hotels(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get hotels."""
        try:
            checkin, checkout, _ = self._trip_window(state)
            adults = self._safe_int(state.get("num_people") or state.get("travelers"), 2)

            return search_hotels_by_city(
                state["destination_city"],
                checkin,
                checkout,
                adults=adults,
                limit=5
            )
        except Exception as e:
            return [{"error": f"Hotels fetch failed: {e}"}]

    def _get_car_rentals(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get car rentals and fuel prices for destination city."""
        try:
            destination = state["destination_city"]
            result = get_car_and_fuel_prices(location=destination)
            # Wrap in list to match expected return type
            return [result]
        except Exception as e:
            return [{"error": f"Car rental fetch failed: {e}"}]

    def _get_fuel_prices(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Get fuel prices AND car rental daily rates in a single Gemini query."""
        try:
            return get_car_and_fuel_prices(state["destination_city"])
        except Exception as e:
            return {"error": f"Fuel/rental price fetch failed: {e}"}

    def _get_distances(self, attractions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get distances between attractions."""
        nodes: List[Tuple[str, Dict[str, float]]] = []
        for attr in attractions:
            coord = attr.get("coord")
            if coord and coord.get("lat") is not None and coord.get("lng") is not None:
                nodes.append((attr.get("name", "Attraction"), coord))
            if len(nodes) == 5:
                break

        if len(nodes) < 2:
            return []

        origins = [(node[1]["lat"], node[1]["lng"]) for node in nodes]
        try:
            matrix = get_distance_matrix(origins, origins, mode="DRIVE")
            enriched: List[Dict[str, Any]] = []
            for item in matrix:
                oi = item.get("origin_idx")
                di = item.get("dest_idx")
                if oi is None or di is None or oi == di:
                    continue
                origin_name = nodes[int(oi)][0]
                dest_name = nodes[int(di)][0]
                enriched.append({
                    **item,
                    "origin_name": origin_name,
                    "dest_name": dest_name,
                })
            return enriched
        except Exception as e:
            return [{"error": f"Distance calc failed: {e}"}]

