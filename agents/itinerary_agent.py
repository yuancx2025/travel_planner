# agents/itinerary_agent.py
"""
ItineraryAgent: Builds detailed day-by-day itineraries enriched with routing and visuals.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any, Dict, List, Optional, Tuple

from tools import routes, streetview


class ItineraryAgent:
    """Construct a structured itinerary and supporting planning context."""

    def __init__(self, *, default_blocks_per_day: int = 3) -> None:
        self.default_blocks_per_day = max(1, default_blocks_per_day)

    def build_itinerary(
        self,
        preferences: Dict[str, Any],
        attractions: List[Dict[str, Any]],
        research: Dict[str, Any],
    ) -> Dict[str, Any]:
        coroutine = self._build_itinerary_async(preferences, attractions, research)
        try:
            return asyncio.run(coroutine)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            previous_loop: Optional[asyncio.AbstractEventLoop]
            try:
                previous_loop = None
                try:
                    previous_loop = asyncio.get_event_loop()
                except RuntimeError:
                    previous_loop = None
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coroutine)
            finally:
                asyncio.set_event_loop(previous_loop)
                loop.close()

    async def _build_itinerary_async(
        self,
        preferences: Dict[str, Any],
        attractions: List[Dict[str, Any]],
        research: Dict[str, Any],
    ) -> Dict[str, Any]:
        day_blocks = self._chunk_attractions(preferences, attractions)
        travel_mode = str(preferences.get("travel_mode", "DRIVE")).upper() or "DRIVE"

        await asyncio.gather(
            *(self._enrich_day_with_route_and_views(day, travel_mode) for day in day_blocks)
        )

        return {
            "days": day_blocks,
        }

    def build_planning_context(
        self,
        user_state: Dict[str, Any],
        research_results: Dict[str, Any],
        itinerary: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        selected_attractions: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        lines = ["=== USER PREFERENCES ==="]
        lines.append(f"Name: {user_state.get('name', 'N/A')}")
        lines.append(f"Destination: {user_state.get('destination_city', 'N/A')}")
        lines.append(f"Duration: {user_state.get('travel_days', 'N/A')} days")
        lines.append(f"Start Date: {user_state.get('start_date', 'N/A')}")
        lines.append(f"Budget: ${user_state.get('budget_usd', 'N/A')} USD")
        lines.append(f"Travelers: {user_state.get('num_people', 'N/A')} people")
        lines.append(f"Kids: {user_state.get('kids', 'N/A')}")
        lines.append(f"Activity Preference: {user_state.get('activity_pref', 'N/A')}")
        lines.append(f"Cuisine Preference: {user_state.get('cuisine_pref', 'N/A')}")
        lines.append(f"Car Rental: {user_state.get('need_car_rental', 'N/A')}")
        lines.append("")

        if selected_attractions:
            lines.append("=== USER-APPROVED ATTRACTIONS ===")
            for idx, attr in enumerate(selected_attractions, 1):
                lines.append(f"{idx}. {attr.get('name', 'Attraction')} - {attr.get('address', 'N/A')}")
            lines.append("")

        if itinerary and itinerary.get("days"):
            lines.append("=== ITINERARY OUTLINE ===")
            for day in itinerary["days"]:
                stops = day.get("stops", [])
                summary = ", ".join(stop.get("name", "Attraction") for stop in stops) or "Flex time / explore"
                lines.append(f"Day {day['day']}: {summary}")
                route = day.get("route")
                if route and route.get("distance_m"):
                    km = route["distance_m"] / 1000
                    mins = (route.get("duration_s", 0) or 0) / 60
                    lines.append(f"  • Route: {km:.1f} km, {mins:.0f} min ({route.get('mode', 'DRIVE')})")
                for stop in stops:
                    sv = stop.get("streetview_url")
                    if sv:
                        lines.append(f"  • Street View preview: {stop['name']}: {sv}")
            if budget:
                lines.append(
                    "Budget range (USD): "
                    f"${budget['low']} – ${budget['high']} (expected ${budget['expected']})"
                )
            lines.append("")

        if research_results.get("weather"):
            lines.append("=== WEATHER FORECAST ===")
            for day in research_results["weather"][:5]:
                lines.append(
                    f"{day['date']}: {day['temp_low']} to {day['temp_high']}, "
                    f"{day['summary']}, Precipitation: {day['precipitation']}"
                )
            lines.append("")

        if research_results.get("attractions"):
            lines.append("=== TOP ATTRACTIONS ===")
            for i, attr in enumerate(research_results["attractions"][:8], 1):
                rating = f"{attr.get('rating', 'N/A')}⭐" if attr.get("rating") else "No rating"
                lines.append(
                    f"{i}. {attr['name']} ({rating}, {attr.get('review_count', 0)} reviews) - "
                    f"{attr.get('address', 'N/A')}"
                )
            lines.append("")

        if research_results.get("dining"):
            lines.append("=== RESTAURANT RECOMMENDATIONS ===")
            for i, rest in enumerate(research_results["dining"][:6], 1):
                rating = f"{rest.get('rating', 'N/A')}⭐" if rest.get("rating") else "No rating"
                price = "$" * rest.get("price_level", 2)
                lines.append(
                    f"{i}. {rest['name']} ({rating}, {price}) - {rest.get('address', 'N/A')}"
                )
            lines.append("")

        if research_results.get("hotels"):
            lines.append("=== HOTEL OPTIONS ===")
            for i, hotel in enumerate(research_results["hotels"][:5], 1):
                lines.append(
                    f"{i}. {hotel.get('name', 'N/A')} - ${hotel.get('price', 'N/A')} {hotel.get('currency', 'USD')} - "
                    f"Rating: {hotel.get('rating', 'N/A')}"
                )
            lines.append("")

        if research_results.get("car_rentals"):
            lines.append("=== CAR RENTAL OPTIONS ===")
            for i, car in enumerate(research_results["car_rentals"][:5], 1):
                veh = car.get("vehicle", {})
                price = car.get("price", {})
                lines.append(
                    f"{i}. {car.get('supplier', 'N/A')} - {veh.get('class', 'N/A')} "
                    f"({veh.get('seats', 'N/A')} seats, {veh.get('transmission', 'N/A')}) - "
                    f"${price.get('amount', 'N/A')} {price.get('currency', 'USD')}"
                )
            lines.append("")

        if research_results.get("fuel_prices"):
            fp = research_results["fuel_prices"]
            lines.append("=== FUEL PRICES ===")
            lines.append(f"Location: {fp.get('location', 'N/A')} ({fp.get('state', 'N/A')})")
            lines.append(f"Regular: ${fp.get('regular', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Midgrade: ${fp.get('midgrade', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Premium: ${fp.get('premium', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Diesel: ${fp.get('diesel', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Source: {fp.get('source', 'N/A')}")
            lines.append("")

            # Display car rental daily rates if available
            rental_rates = []
            if fp.get('economy_car_daily'):
                rental_rates.append(f"Economy: ${fp['economy_car_daily']}/day")
            if fp.get('compact_car_daily'):
                rental_rates.append(f"Compact: ${fp['compact_car_daily']}/day")
            if fp.get('midsize_car_daily'):
                rental_rates.append(f"Midsize: ${fp['midsize_car_daily']}/day")
            if fp.get('suv_daily'):
                rental_rates.append(f"SUV: ${fp['suv_daily']}/day")

            if rental_rates:
                lines.append("=== CAR RENTAL DAILY RATES ===")
                lines.extend(rental_rates)
                lines.append("")

        if research_results.get("distances"):
            lines.append("=== DISTANCES BETWEEN TOP ATTRACTIONS ===")
            for dist in research_results["distances"][:5]:
                km = dist.get("distance_m", 0) / 1000
                mins = dist.get("duration_s", 0) / 60
                lines.append(
                    f"{dist.get('origin_name', 'Origin')} → {dist.get('dest_name', 'Dest')}: "
                    f"{km:.1f} km, {mins:.0f} min drive"
                )
            lines.append("")

        return "\n".join(lines)

    def _chunk_attractions(
        self,
        preferences: Dict[str, Any],
        attractions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        total_days = max(1, self._safe_int(preferences.get("travel_days"), len(attractions) or 1))
        per_day = max(1, math.ceil(max(1, len(attractions)) / total_days))
        blocks: List[Dict[str, Any]] = []
        start_hour = 9
        block_hours = max(2, int(12 / self.default_blocks_per_day))

        for idx in range(total_days):
            chunk = attractions[idx * per_day:(idx + 1) * per_day]
            stops: List[Dict[str, Any]] = []
            for pos, attraction in enumerate(chunk):
                coord = attraction.get("coord") or {}
                stop = {
                    "name": attraction.get("name", "Attraction"),
                    "address": attraction.get("address", "N/A"),
                    "start_time": f"{start_hour + pos * block_hours:02d}:00",
                    "duration_hours": block_hours,
                    "coord": coord if isinstance(coord, dict) else None,
                    "source": attraction.get("source", "google"),
                }
                stops.append(stop)
            blocks.append({
                "day": idx + 1,
                "stops": stops,
                "route": None,
            })

        return blocks

    async def _enrich_day_with_route_and_views(self, day: Dict[str, Any], travel_mode: str) -> None:
        coords = [self._coord_tuple(stop.get("coord")) for stop in day.get("stops", [])]
        coords = [c for c in coords if c]

        if len(coords) >= 2:
            origin = coords[0]
            destination = coords[-1]
            waypoints = coords[1:-1]
            try:
                result = await routes.compute_route(
                    origin,
                    waypoints,
                    destination,
                    travel_mode=travel_mode,
                    optimize_waypoint_order=False,
                )
                day["route"] = {
                    "distance_m": result.get("distance_m"),
                    "duration_s": result.get("duration_s"),
                    "polyline": result.get("polyline"),
                    "legs": result.get("legs", []),
                    "mode": travel_mode,
                }
            except Exception as exc:
                day["route_error"] = str(exc)

        await self._attach_streetview_urls(day)

    async def _attach_streetview_urls(self, day: Dict[str, Any]) -> None:
        stops = day.get("stops", [])
        tasks: List[asyncio.Task] = []
        indices: List[int] = []
        for idx, stop in enumerate(stops):
            coord = self._coord_tuple(stop.get("coord"))
            if not coord:
                continue
            indices.append(idx)
            tasks.append(
                asyncio.create_task(
                    streetview.best_streetview_url_if_available(
                        coord[0],
                        coord[1],
                        radius_m=75,
                        source="outdoor",
                    )
                )
            )

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for idx, result in zip(indices, results):
            if isinstance(result, Exception) or result is None:
                continue
            stops[idx]["streetview_url"] = result

    def _coord_tuple(self, coord: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
        if not coord:
            return None
        try:
            return float(coord["lat"]), float(coord["lng"])
        except (KeyError, TypeError, ValueError):
            return None

    def _safe_int(self, value: Any, fallback: int) -> int:
        try:
            return max(int(value), 0) or fallback
        except (TypeError, ValueError):
            return fallback
