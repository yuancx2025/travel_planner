# agents/research_agent.py
"""ResearchAgent: Tool coordinator for travel research."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.attractions import search_attractions
from tools.car_price import get_car_and_fuel_prices
from tools.dining import search_restaurants
from tools.distance_matrix import get_distance_matrix
from tools.flight import search_flights
from tools.hotels import CITY_TO_IATA, search_hotels_by_city
from tools.weather import get_weather


class ResearchAgent:
    """Stateless agent that executes tool calls based on user preferences."""

    def __init__(self):
        self._validate_env()

    def _validate_env(self):
        """Check required API keys."""
        missing = []
        if not os.getenv("GOOGLE_MAPS_API_KEY"):
            missing.append("GOOGLE_MAPS_API_KEY")
        if not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            missing.append("GOOGLE_API_KEY or GEMINI_API_KEY (for attractions, dining, fuel prices)")
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

        async def run_flights():
            return await run(self._get_flights, state)

        attractions_task = asyncio.create_task(run_attractions())
        weather_task = asyncio.create_task(run_weather())
        hotels_task = asyncio.create_task(run_hotels())
        flights_task = asyncio.create_task(run_flights())

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
            "flights": flights_task,
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

        flights_result = task_outputs["flights"]
        if isinstance(flights_result, Exception):
            results["flights"] = [{"error": f"Flight fetch failed: {flights_result}"}]
        elif isinstance(flights_result, list) and flights_result:
            results["flights"] = flights_result

        distances_result = task_outputs["distances"]
        if isinstance(distances_result, Exception):
            results["distances"] = [{"error": f"Distance calc failed: {distances_result}"}]
        elif distances_result:
            results["distances"] = distances_result

        need_car = state.get("need_car_rental")
        if isinstance(need_car, str):
            need_car = need_car.strip().lower() in {"yes", "y", "true", "1"}
        if need_car:
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

    def _get_flights(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get flight offers between home and destination airports."""
        try:
            origin = state.get("home_airport") or state.get("origin_airport")
            if isinstance(origin, str):
                origin = origin.strip().upper()

            if not origin:
                origin_city = state.get("origin_city")
                if origin_city:
                    origin = CITY_TO_IATA.get(origin_city.strip().lower())

            destination = state.get("destination_airport")
            if isinstance(destination, str):
                destination = destination.strip().upper()

            if not destination:
                dest_city = state.get("destination_city")
                if dest_city:
                    destination = CITY_TO_IATA.get(dest_city.strip().lower())

            if not origin or not destination:
                return []

            departure, return_date, _ = self._trip_window(state)
            adults = self._safe_int(state.get("num_people"), 1)

            offers = search_flights(
                origin,
                destination,
                departure,
                return_date=return_date,
                adults=adults,
                max_results=5,
            )
            return offers or []
        except Exception as e:
            return [{"error": f"Flight search failed: {e}"}]

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


# # ==================== SMOKE TEST ====================
# if __name__ == "__main__":
#     """
#     Smoke test for ResearchAgent with mock user preferences.
#     Tests all API integrations: weather, attractions, dining, hotels, car rentals, fuel prices, distances.
    
#     Usage:
#         cd /Users/yuanwenbo/Desktop/590_project/agents
#         python research_agent.py
    
#     Customize the mock_user_preferences below to test different scenarios.
#     """
#     import json
#     import sys
#     from pathlib import Path
    
#     # Add parent directory to path so we can import tools
#     sys.path.insert(0, str(Path(__file__).parent.parent))
    
#     print("=" * 80)
#     print("🔍 ResearchAgent Smoke Test")
#     print("=" * 80)
    
#     # Mock user preferences (customize these to test different scenarios)
#     mock_user_preferences = {
#         "name": "Test User",
#         "destination_city": "Orlando",  # Change this to test different cities
#         "travel_days": 3,
#         "start_date": "2025-11-15",  # YYYY-MM-DD or "not decided"
#         "budget_usd": 1000,
#         "num_people": 2,
#         "kids": "no",
#         "activity_pref": "outdoor",  # "outdoor" or "indoor"
#         "need_car_rental": "yes",  # "yes" or "no"
#         "hotel_room_pref": "1 king",
#         "cuisine_pref": "seafood",  # e.g., "ramen", "seafood", "vegan"
#         "origin_city": "Durham",
#         "temp_unit": "celsius",  # "fahrenheit" or "celsius"
#         "home_airport": "RDU",
#         "destination_airport": "MCO",
#     }
    
#     print("\n📋 Testing with user preferences:")
#     print(json.dumps(mock_user_preferences, indent=2))
#     print("\n" + "=" * 80)
    
#     # Initialize the agent
#     print("\n🚀 Initializing ResearchAgent...")
#     try:
#         agent = ResearchAgent()
#         print("✅ Agent initialized successfully")
#     except Exception as e:
#         print(f"❌ Failed to initialize agent: {e}")
#         sys.exit(1)
    
#     # Run research
#     print("\n🔎 Running research (this may take 10-30 seconds)...")
#     print("   - Fetching weather forecast")
#     print("   - Finding attractions")
#     print("   - Searching restaurants")
#     print("   - Looking up hotels")
#     print("   - Checking flight offers")
#     print("   - Getting car rental & fuel prices")
#     print("   - Calculating distances between attractions")
    
#     try:
#         results = agent.research(mock_user_preferences)
#         print("\n✅ Research completed successfully!")
#     except Exception as e:
#         print(f"\n❌ Research failed: {e}")
#         import traceback
#         traceback.print_exc()
#         sys.exit(1)
    
#     # Display results summary
#     print("\n" + "=" * 80)
#     print("📊 RESULTS SUMMARY")
#     print("=" * 80)
    
#     # Weather
#     if "weather" in results:
#         weather = results["weather"]
#         if isinstance(weather, list) and weather:
#             if "error" in weather[0]:
#                 print(f"\n❌ Weather: {weather[0]['error']}")
#             else:
#                 print(f"\n☀️  Weather: {len(weather)} day(s) forecast retrieved")
#                 for day in weather[:3]:  # Show first 3 days
#                     date = day.get("date", "N/A")
#                     temp = day.get("temp_high", "N/A")
#                     conditions = day.get("conditions", "N/A")
#                     print(f"   - {date}: {temp}°, {conditions}")
#         else:
#             print("\n⚠️  Weather: No data")
    
#     # Attractions
#     if "attractions" in results:
#         attractions = results["attractions"]
#         if isinstance(attractions, list) and attractions:
#             if "error" in attractions[0]:
#                 print(f"\n❌ Attractions: {attractions[0]['error']}")
#             else:
#                 print(f"\n🎡 Attractions: {len(attractions)} found")
#                 for attr in attractions[:10]:  # Show first 10
#                     name = attr.get("name", "N/A")
#                     rating = attr.get("rating", "N/A")
#                     print(f"   - {name} (Rating: {rating}⭐)")
#         else:
#             print("\n⚠️  Attractions: No data")
    
#     # Dining
#     if "dining" in results:
#         dining = results["dining"]
#         if isinstance(dining, list) and dining:
#             if "error" in dining[0]:
#                 print(f"\n❌ Dining: {dining[0]['error']}")
#             else:
#                 print(f"\n🍽️  Dining: {len(dining)} restaurants found")
#                 for rest in dining[:10]:  # Show first 10
#                     name = rest.get("name", "N/A")
#                     rating = rest.get("rating", "N/A")
#                     print(f"   - {name} (Rating: {rating}⭐)")
#         else:
#             print("\n⚠️  Dining: No data")
    
#     # Hotels
#     if "hotels" in results:
#         hotels = results["hotels"]
#         if isinstance(hotels, list) and hotels:
#             if "error" in hotels[0]:
#                 print(f"\n❌ Hotels: {hotels[0]['error']}")
#             else:
#                 print(f"\n🏨 Hotels: {len(hotels)} found")
#                 for hotel in hotels[:5]:  # Show first 5
#                     name = hotel.get("name", "N/A")
#                     price = hotel.get("price")
#                     currency = hotel.get("currency") or "USD"
#                     if price:
#                         print(f"   - {name} ({currency} {price}/night)")
#                     else:
#                         print(f"   - {name} (rate unavailable)")
#         else:
#             print("\n⚠️  Hotels: No data")

#     # Flights
#     if "flights" in results:
#         flights = results["flights"]
#         if isinstance(flights, list) and flights:
#             if "error" in flights[0]:
#                 print(f"\n❌ Flights: {flights[0]['error']}")
#             else:
#                 print(f"\n✈️  Flights: {len(flights)} offers found")
#                 for offer in flights[:3]:  # Show first 3
#                     carrier = offer.get("carrier", "N/A")
#                     price = offer.get("price")
#                     currency = offer.get("currency") or "USD"
#                     duration = offer.get("duration", "N/A")
#                     if price:
#                         print(f"   - {carrier} {currency} {price} ({duration})")
#                     else:
#                         print(f"   - {carrier} (price unavailable, {duration})")
#         else:
#             print("\n⚠️  Flights: No data")
    
#     # Car Rentals & Fuel Prices
#     if "car_rentals" in results:
#         car_rentals = results["car_rentals"]
#         if isinstance(car_rentals, list) and car_rentals:
#             if "error" in car_rentals[0]:
#                 print(f"\n❌ Car Rentals: {car_rentals[0]['error']}")
#             else:
#                 rental = car_rentals[0]
#                 print(f"\n🚗 Car Rentals & Fuel Prices:")
#                 print(f"   Location: {rental.get('location', 'N/A')}, {rental.get('state', 'N/A')}")
#                 if rental.get("economy_car_daily"):
#                     print(f"   - Economy: ${rental.get('economy_car_daily')}/day")
#                 if rental.get("compact_car_daily"):
#                     print(f"   - Compact: ${rental.get('compact_car_daily')}/day")
#                 if rental.get("midsize_car_daily"):
#                     print(f"   - Midsize: ${rental.get('midsize_car_daily')}/day")
#                 if rental.get("regular"):
#                     print(f"   - Regular gas: ${rental.get('regular')}/gallon")
#                 if rental.get("premium"):
#                     print(f"   - Premium gas: ${rental.get('premium')}/gallon")
#         else:
#             print("\n⚠️  Car Rentals: No data")
    
#     if "fuel_prices" in results:
#         fuel = results["fuel_prices"]
#         if "error" not in fuel:
#             print(f"\n⛽ Fuel Prices (separate):")
#             print(f"   - Regular: ${fuel.get('regular', 'N/A')}/gallon")
#             print(f"   - Premium: ${fuel.get('premium', 'N/A')}/gallon")
#             print(f"   - Diesel: ${fuel.get('diesel', 'N/A')}/gallon")
    
#     # Distances
#     if "distances" in results:
#         distances = results["distances"]
#         if isinstance(distances, list) and distances:
#             if "error" in distances[0]:
#                 print(f"\n❌ Distances: {distances[0]['error']}")
#             else:
#                 print(f"\n📏 Distances: {len(distances)} route segments calculated")
#                 for dist in distances[:3]:  # Show first 3
#                     origin = dist.get("origin_name", "N/A")
#                     dest = dist.get("dest_name", "N/A")
#                     km = dist.get("distance_m", 0) / 1000
#                     mins = dist.get("duration_s", 0) / 60
#                     print(f"   - {origin} → {dest}: {km:.1f}km, {mins:.0f}min")
#         else:
#             print("\n⚠️  Distances: No data")
    
#     # Full JSON output option
#     print("\n" + "=" * 80)
#     print("💾 Save full results to JSON? (y/n): ", end="")
#     try:
#         response = input().strip().lower()
#         if response == "y":
#             output_file = Path(__file__).parent.parent / "research_results.json"
#             output_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))
#             print(f"✅ Results saved to: {output_file}")
#     except (KeyboardInterrupt, EOFError):
#         print("\nSkipped.")
    
#     print("\n" + "=" * 80)
#     print("✅ Smoke test complete!")
#     print("=" * 80)

