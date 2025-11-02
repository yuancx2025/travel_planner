# agents/itinerary_agent.py
"""ItineraryAgent: Builds detailed day-by-day itineraries enriched with routing.

This version orchestrates an LLM-assisted scheduling workflow with four stages:

1. Pre-processing – normalize user preferences and attractions into structured
   scheduling primitives.
2. Prompt engineering – provide the LLM with an explicit schema, examples and
   constraints so the generated plan is machine readable.
3. Post-processing – validate and auto-correct the LLM output before trusting it.
4. Enrichment – augment the validated schedule with live routing and Street View
   previews for each stop.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from prompts import load_prompt_template
from tools import routes, streetview


@dataclass
class _Activity:
    """Normalized activity representation shared across planning stages."""

    id: str
    name: str
    address: str
    coord: Optional[Dict[str, Any]]
    category: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    duration_hours: float
    ideal_window: str
    area_bucket: Optional[str]
    hours: Dict[str, Dict[str, Optional[str]]]
    source: str
    raw: Dict[str, Any]


@dataclass
class _MealOption:
    id: str
    name: str
    address: str
    coord: Optional[Dict[str, Any]]
    price_level: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    source: str


class ItineraryAgent:
    """Construct a structured itinerary and supporting planning context."""

    def __init__(
        self,
        *,
        default_blocks_per_day: int = 3,
        model_name: str = "gemini-2.0-flash",
        temperature: float = 0.2,
        llm: Optional[ChatGoogleGenerativeAI] = None,
    ) -> None:
        self.default_blocks_per_day = max(1, default_blocks_per_day)
        self.model_name = model_name
        self.temperature = temperature
        self._llm: Optional[ChatGoogleGenerativeAI] = llm
        self._llm_disabled = False
        self._llm_error: Optional[str] = None
        self._prompt_template = load_prompt_template("itinerary", "itinerary.md")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        plan_result = await asyncio.to_thread(
            self._plan_day_blocks,
            preferences,
            attractions,
            research,
        )

        day_blocks, meta = plan_result
        travel_mode = str(preferences.get("travel_mode", "DRIVE")).upper() or "DRIVE"

        await asyncio.gather(
            *(self._enrich_day_with_route_and_views(day, travel_mode) for day in day_blocks)
        )

        itinerary: Dict[str, Any] = {"days": day_blocks}
        if meta:
            itinerary["meta"] = meta
        if self._llm_error and itinerary.setdefault("meta", {}).get("llm_error") is None:
            itinerary.setdefault("meta", {})["llm_error"] = self._llm_error
        return itinerary

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
                price = rest.get("price_level") or "Unknown"
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

    # ------------------------------------------------------------------
    # LLM-driven scheduling pipeline
    # ------------------------------------------------------------------

    def _plan_day_blocks(
        self,
        preferences: Dict[str, Any],
        attractions: List[Dict[str, Any]],
        research: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        preprocessed = self._preprocess_inputs(preferences, attractions, research)
        meta: Dict[str, Any] = {
            "strategy": "fallback",
            "travel_days": preprocessed["travel_days"],
            "total_candidates": len(preprocessed["activities"]),
            "warnings": [],
        }

        if preprocessed["activities"]:
            schedule_result = self._generate_llm_schedule(preferences, research, preprocessed)
        else:
            schedule_result = None

        if schedule_result:
            day_blocks, warnings = self._materialize_schedule(schedule_result, preprocessed)
            if day_blocks:
                meta["strategy"] = "llm"
                if warnings:
                    meta.setdefault("warnings", []).extend(warnings)
                if schedule_result.get("unplaced"):
                    meta["unplaced"] = schedule_result["unplaced"]
                return day_blocks, meta
            meta.setdefault("warnings", []).append(
                "LLM produced an itinerary but validation failed; using fallback schedule."
            )

        fallback_blocks = self._chunk_attractions(preferences, attractions)
        meta.setdefault("warnings", []).append("Fallback time-blocking heuristic used.")
        return fallback_blocks, meta

    def _generate_llm_schedule(
        self,
        preferences: Dict[str, Any],
        research: Dict[str, Any],
        preprocessed: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        model = self._ensure_llm()
        if model is None:
            return None

        system_msg = SystemMessage(content=self._prompt_template.format())
        user_msg = HumanMessage(content=self._render_llm_payload(preferences, research, preprocessed))

        try:
            response = model.invoke([system_msg, user_msg])
        except Exception as exc:
            self._llm_error = str(exc)
            return None

        content = getattr(response, "content", "")
        if isinstance(content, list):
            content = "".join(str(part) for part in content)

        parsed = self._parse_llm_json(content)
        if not parsed:
            self._llm_error = "LLM response was not valid JSON."
            return None

        self._llm_error = None
        return parsed

    def _materialize_schedule(
        self,
        schedule: Dict[str, Any],
        preprocessed: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        travel_days = preprocessed["travel_days"]
        catalog: Dict[str, _Activity] = preprocessed["catalog"]
        meals: Dict[str, _MealOption] = preprocessed["meals_catalog"]
        warnings: List[str] = []

        raw_days = schedule.get("days")
        if not isinstance(raw_days, Iterable):
            return ([], ["Schedule missing 'days' array."])

        normalized_days: List[Dict[str, Any]] = []
        for idx, entry in enumerate(raw_days, 1):
            if not isinstance(entry, dict):
                warnings.append(f"Day {idx} entry is not an object.")
                continue

            blocks = entry.get("blocks") or []
            stops: List[Dict[str, Any]] = []
            meals_for_day: List[Dict[str, Any]] = []
            last_end = self._parse_time_to_minutes(entry.get("day_start", "09:00")) or 9 * 60

            for block in blocks:
                if not isinstance(block, dict):
                    warnings.append(f"Day {idx} block ignored because it is not an object.")
                    continue

                normalized_block = self._normalize_block(block, catalog, meals, last_end)
                if not normalized_block:
                    warnings.append(
                        f"Day {idx} block '{block.get('activity_name', 'unknown')}' could not be mapped."
                    )
                    continue

                if normalized_block["type"] == "meal":
                    meals_for_day.append(normalized_block)
                    last_end = normalized_block.get("_end_minutes", last_end)
                    continue

                last_end = normalized_block.get("_end_minutes", last_end)
                normalized_block.pop("_end_minutes", None)
                stops.append(normalized_block)

            normalized_days.append(
                {
                    "day": entry.get("day", len(normalized_days) + 1),
                    "theme": entry.get("theme"),
                    "summary": entry.get("summary") or entry.get("notes"),
                    "stops": stops,
                    "meals": [
                        {key: value for key, value in meal.items() if not key.startswith("_")}
                        for meal in meals_for_day
                    ],
                    "notes": entry.get("notes"),
                    "day_start": entry.get("day_start"),
                    "day_end": entry.get("day_end"),
                }
            )

        if not normalized_days:
            return ([], ["Schedule did not contain any usable days."])

        normalized_days.sort(key=lambda d: d.get("day", 0))

        if len(normalized_days) < travel_days:
            warnings.append(
                f"LLM returned {len(normalized_days)} days but {travel_days} were requested."
            )

        for day_idx, day in enumerate(normalized_days, 1):
            day["day"] = day_idx

        return normalized_days, warnings

    # ------------------------------------------------------------------
    # Pre-processing helpers
    # ------------------------------------------------------------------

    def _preprocess_inputs(
        self,
        preferences: Dict[str, Any],
        attractions: List[Dict[str, Any]],
        research: Dict[str, Any],
    ) -> Dict[str, Any]:
        travel_days = max(1, self._safe_int(preferences.get("travel_days"), len(attractions) or 1))
        activities: List[_Activity] = []
        catalog: Dict[str, _Activity] = {}
        seen_ids: set[str] = set()

        for idx, attraction in enumerate(attractions):
            activity = self._normalize_attraction(attraction, idx, seen_ids)
            if not activity:
                continue
            activities.append(activity)
            catalog[activity.id] = activity
            seen_ids.add(activity.id)

        meal_options, meal_catalog = self._prepare_meal_options(research)

        return {
            "travel_days": travel_days,
            "activities": activities,
            "catalog": catalog,
            "meal_options": meal_options,
            "meals_catalog": meal_catalog,
            "preferences_summary": self._preferences_summary(preferences),
            "weather_summary": self._weather_summary(research),
            "day_constraints": {
                "day_start": "09:00",
                "day_end": "21:30",
                "blocks_per_day": self.default_blocks_per_day,
            },
        }

    def _normalize_attraction(
        self,
        attraction: Dict[str, Any],
        index: int,
        seen_ids: set[str],
    ) -> Optional[_Activity]:
        name = (attraction.get("name") or "").strip()
        if not name:
            return None

        base_id = self._slugify(attraction.get("id") or name or f"attraction-{index}")
        candidate_id = base_id or f"attraction-{index}"
        suffix = 1
        while candidate_id in seen_ids:
            suffix += 1
            candidate_id = f"{base_id}-{suffix}"

        coord = attraction.get("coord") if isinstance(attraction.get("coord"), dict) else None
        category = attraction.get("category")
        hours = self._parse_hours(attraction.get("hours"))

        duration = self._estimate_duration(category)
        ideal_window = self._derive_ideal_window(hours, category)
        area_bucket = self._area_bucket(coord)

        return _Activity(
            id=candidate_id,
            name=name,
            address=(attraction.get("address") or "").strip(),
            coord=coord,
            category=category,
            rating=self._to_float(attraction.get("rating"), default=None),
            review_count=self._safe_int(attraction.get("review_count"), 0),
            duration_hours=duration,
            ideal_window=ideal_window,
            area_bucket=area_bucket,
            hours=hours,
            source=str(attraction.get("source") or "google"),
            raw=attraction,
        )

    def _prepare_meal_options(
        self, research: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, _MealOption]]:
        meal_options: List[Dict[str, Any]] = []
        catalog: Dict[str, _MealOption] = {}
        dining = research.get("dining") or []

        for idx, restaurant in enumerate(dining[:8]):
            name = (restaurant.get("name") or "").strip()
            if not name:
                continue
            base_id = self._slugify(restaurant.get("id") or name or f"meal-{idx}") or f"meal-{idx}"
            meal_id = base_id
            counter = 1
            while meal_id in catalog:
                counter += 1
                meal_id = f"{base_id}-{counter}"

            option = _MealOption(
                id=meal_id,
                name=name,
                address=(restaurant.get("address") or "").strip(),
                coord=restaurant.get("coord") if isinstance(restaurant.get("coord"), dict) else None,
                price_level=restaurant.get("price_level"),
                rating=self._to_float(restaurant.get("rating"), default=None),
                review_count=self._safe_int(restaurant.get("review_count"), 0),
                source=str(restaurant.get("source") or "google"),
            )

            catalog[meal_id] = option
            meal_options.append(
                {
                    "id": option.id,
                    "name": option.name,
                    "address": option.address,
                    "price_level": option.price_level,
                    "rating": option.rating,
                    "review_count": option.review_count,
                }
            )

        return meal_options, catalog

    def _preferences_summary(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "destination": preferences.get("destination_city"),
            "travel_days": self._safe_int(preferences.get("travel_days"), 3),
            "start_date": preferences.get("start_date"),
            "num_people": self._safe_int(preferences.get("num_people"), 2),
            "kids": preferences.get("kids"),
            "activity_pref": preferences.get("activity_pref"),
            "cuisine_pref": preferences.get("cuisine_pref"),
            "travel_mode": preferences.get("travel_mode", "DRIVE"),
            "need_car_rental": preferences.get("need_car_rental"),
            "budget_usd": preferences.get("budget_usd"),
        }

    def _weather_summary(self, research: Dict[str, Any]) -> List[Dict[str, Any]]:
        summary = []
        for day in (research.get("weather") or [])[:5]:
            if not isinstance(day, dict):
                continue
            summary.append(
                {
                    "date": day.get("date"),
                    "temp_low": day.get("temp_low"),
                    "temp_high": day.get("temp_high"),
                    "summary": day.get("summary"),
                    "precipitation": day.get("precipitation"),
                }
            )
        return summary

    # ------------------------------------------------------------------
    # Prompt and parsing helpers
    # ------------------------------------------------------------------

    def _render_llm_payload(
        self,
        preferences: Dict[str, Any],
        research: Dict[str, Any],
        preprocessed: Dict[str, Any],
    ) -> str:
        payload = {
            "preferences": preprocessed["preferences_summary"],
            "travel_days": preprocessed["travel_days"],
            "day_constraints": preprocessed["day_constraints"],
            "activities": [
                {
                    "id": act.id,
                    "name": act.name,
                    "category": act.category,
                    "duration_hours": act.duration_hours,
                    "ideal_window": act.ideal_window,
                    "area_bucket": act.area_bucket,
                    "rating": act.rating,
                    "review_count": act.review_count,
                    "address": act.address,
                    "hours": act.hours,
                }
                for act in preprocessed["activities"]
            ],
            "meal_options": preprocessed["meal_options"],
            "weather": preprocessed["weather_summary"],
            "additional_notes": research.get("distances"),
        }
        return json.dumps(payload, indent=2)

    def _parse_llm_json(self, text: str) -> Optional[Dict[str, Any]]:
        candidates = []
        fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
        if fenced:
            candidates.extend(fenced)
        else:
            candidates.append(text)

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return None

    # ------------------------------------------------------------------
    # Block normalization + validation
    # ------------------------------------------------------------------

    def _normalize_block(
        self,
        block: Dict[str, Any],
        catalog: Dict[str, _Activity],
        meals: Dict[str, _MealOption],
        default_start: int,
    ) -> Optional[Dict[str, Any]]:
        block_type = str(block.get("type") or "activity").lower()
        start_minutes = self._parse_time_to_minutes(block.get("start_time")) or default_start
        end_minutes = self._parse_time_to_minutes(block.get("end_time"))

        duration_hours = self._to_float(block.get("duration_hours"), default=0.0)
        if not end_minutes and duration_hours > 0:
            end_minutes = start_minutes + int(duration_hours * 60)

        activity_id = block.get("activity_id")
        activity_name = block.get("activity_name")

        if block_type == "meal":
            meal = None
            if isinstance(activity_id, str) and activity_id in meals:
                meal = meals[activity_id]
            elif isinstance(activity_name, str):
                meal = next((m for m in meals.values() if m.name.lower() == activity_name.lower()), None)

            if not meal:
                return None

            computed_end = end_minutes or (start_minutes + int(max(duration_hours, 1.0) * 60))
            if computed_end <= start_minutes:
                computed_end = start_minutes + 60

            result: Dict[str, Any] = {
                "type": "meal",
                "activity_id": meal.id,
                "name": meal.name,
                "start_time": self._format_minutes(start_minutes),
                "duration_hours": round((computed_end - start_minutes) / 60, 2),
                "address": meal.address,
                "coord": meal.coord,
                "source": meal.source,
                "notes": block.get("notes"),
                "price_level": meal.price_level,
                "rating": meal.rating,
            }
            result["_end_minutes"] = computed_end
            return result

        if block_type in {"flex", "buffer", "travel"}:
            if not end_minutes:
                end_minutes = start_minutes + int(max(duration_hours, 1.0) * 60)
            if end_minutes <= start_minutes:
                end_minutes = start_minutes + 60
            label = activity_name or ("Travel time" if block_type == "travel" else "Flex time")
            result = {
                "type": block_type,
                "activity_id": activity_id,
                "name": label,
                "start_time": self._format_minutes(start_minutes),
                "duration_hours": round((end_minutes - start_minutes) / 60, 2),
                "coord": None,
                "source": "llm",
                "notes": block.get("notes") or block.get("summary"),
            }
            result["_end_minutes"] = end_minutes
            return result

        activity = None
        if isinstance(activity_id, str) and activity_id in catalog:
            activity = catalog[activity_id]
        elif isinstance(activity_name, str):
            lowered = activity_name.lower()
            activity = next((item for item in catalog.values() if item.name.lower() == lowered), None)

        if not activity:
            return None

        if not end_minutes:
            end_minutes = start_minutes + int(activity.duration_hours * 60)

        if end_minutes <= start_minutes:
            end_minutes = start_minutes + int(max(activity.duration_hours, 1.0) * 60)

        stop = {
            "type": "activity",
            "activity_id": activity.id,
            "name": activity.name,
            "address": activity.address,
            "start_time": self._format_minutes(start_minutes),
            "duration_hours": round((end_minutes - start_minutes) / 60, 2),
            "coord": activity.coord,
            "source": activity.source,
            "notes": block.get("notes") or block.get("summary"),
            "category": activity.category,
            "rating": activity.rating,
            "review_count": activity.review_count,
        }
        stop["_end_minutes"] = end_minutes
        return stop

    # ------------------------------------------------------------------
    # Enrichment helpers (unchanged from previous version)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _ensure_llm(self) -> Optional[ChatGoogleGenerativeAI]:
        if self._llm_disabled:
            return None
        if self._llm is None:
            try:
                self._llm = ChatGoogleGenerativeAI(model=self.model_name, temperature=self.temperature)
            except Exception as exc:
                self._llm_error = str(exc)
                self._llm_disabled = True
                return None
        return self._llm

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
            chunk = attractions[idx * per_day : (idx + 1) * per_day]
            stops: List[Dict[str, Any]] = []
            for pos, attraction in enumerate(chunk):
                coord = attraction.get("coord") or {}
                stop = {
                    "type": "activity",
                    "name": attraction.get("name", "Attraction"),
                    "address": attraction.get("address", "N/A"),
                    "start_time": f"{start_hour + pos * block_hours:02d}:00",
                    "duration_hours": block_hours,
                    "coord": coord if isinstance(coord, dict) else None,
                    "source": attraction.get("source", "google"),
                }
                stops.append(stop)
            blocks.append(
                {
                    "day": idx + 1,
                    "stops": stops,
                    "route": None,
                    "notes": "Automatically chunked due to unavailable LLM plan.",
                }
            )

        return blocks

    def _coord_tuple(self, coord: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
        if not coord:
            return None
        try:
            return float(coord["lat"]), float(coord["lng"])
        except (KeyError, TypeError, ValueError):
            return None

    def _parse_hours(self, hours: Optional[Iterable[str]]) -> Dict[str, Dict[str, Optional[str]]]:
        parsed: Dict[str, Dict[str, Optional[str]]] = {}
        if not hours:
            return parsed

        pattern = re.compile(r"^(?P<day>[A-Za-z]+):\s*(?P<rest>.+)$")
        time_pattern = re.compile(
            r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[AaPp][Mm])?"
        )

        for entry in hours:
            if not isinstance(entry, str):
                continue
            match = pattern.match(entry.strip())
            if not match:
                continue
            day = match.group("day").lower()
            rest = match.group("rest")
            if "closed" in rest.lower():
                parsed[day] = {"open": None, "close": None}
                continue

            times = time_pattern.findall(rest)
            if len(times) < 2:
                continue

            open_minutes = self._time_tuple_to_minutes(times[0])
            close_minutes = self._time_tuple_to_minutes(times[-1])
            parsed[day] = {
                "open": self._format_minutes(open_minutes) if open_minutes is not None else None,
                "close": self._format_minutes(close_minutes) if close_minutes is not None else None,
            }

        return parsed

    def _time_tuple_to_minutes(self, match: Tuple[str, str, str]) -> Optional[int]:
        if not match:
            return None
        hour_str, minute_str, ampm = match
        hour = int(hour_str)
        minute = int(minute_str or 0)
        if ampm:
            ampm = ampm.lower()
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
        return hour * 60 + minute

    def _estimate_duration(self, category: Optional[str]) -> float:
        if not category:
            return 2.0
        category_lower = category.lower()
        if any(keyword in category_lower for keyword in ("museum", "gallery")):
            return 2.5
        if any(keyword in category_lower for keyword in ("park", "garden", "trail")):
            return 2.0
        if any(keyword in category_lower for keyword in ("tour", "sight", "viewpoint", "tower")):
            return 1.5
        if any(keyword in category_lower for keyword in ("shopping", "market")):
            return 1.5
        if "theme_park" in category_lower or "zoo" in category_lower:
            return 3.5
        return 2.0

    def _derive_ideal_window(
        self,
        hours: Dict[str, Dict[str, Optional[str]]],
        category: Optional[str],
    ) -> str:
        closes = [self._parse_time_to_minutes(entry.get("close")) for entry in hours.values() if entry.get("close")]
        average_close = sum(closes) / len(closes) if closes else None
        if average_close and average_close <= 16 * 60:
            return "morning"
        if average_close and average_close >= 20 * 60:
            return "evening"

        if category:
            category_lower = category.lower()
            if "observatory" in category_lower or "viewpoint" in category_lower:
                return "sunset"
            if "night" in category_lower or "bar" in category_lower:
                return "evening"
        return "afternoon"

    def _area_bucket(self, coord: Optional[Dict[str, Any]]) -> Optional[str]:
        if not coord:
            return None
        try:
            lat = float(coord["lat"])
            lng = float(coord["lng"])
        except (KeyError, TypeError, ValueError):
            return None
        return f"{round(lat, 2)}_{round(lng, 2)}"

    def _parse_time_to_minutes(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            minutes = int(value)
            return max(0, min(minutes, 24 * 60))
        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value:
            return None

        pattern = re.compile(r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[AaPp][Mm])?$")
        match = pattern.match(value)
        if not match:
            return None

        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        ampm = match.group("ampm")
        if ampm:
            ampm = ampm.lower()
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0

        hour = max(0, min(hour, 23))
        minute = max(0, min(minute, 59))
        return hour * 60 + minute

    def _format_minutes(self, minutes: Optional[int]) -> str:
        if minutes is None:
            return "00:00"
        minutes = max(0, min(minutes, 24 * 60))
        hour = minutes // 60
        minute = minutes % 60
        return f"{hour:02d}:{minute:02d}"

    def _slugify(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        return text.strip("-")

    def _safe_int(self, value: Any, fallback: int) -> int:
        try:
            return max(int(value), 0) or fallback
        except (TypeError, ValueError):
            return fallback

    def _to_float(self, value: Any, default: Optional[float] = None) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


__all__ = ["ItineraryAgent"]

