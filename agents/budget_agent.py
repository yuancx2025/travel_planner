from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

from tools import distance_matrix


class BudgetAgent:
    """Estimate trip budget components, including fuel derived from distance matrix."""

    def __init__(
        self,
        *,
        default_hotel_rate: float = 180.0,
        dining_per_person: float = 35.0,
        activity_per_stop: float = 40.0,
        fuel_efficiency_mpg: float = 26.0,
    ) -> None:
        self.default_hotel_rate = default_hotel_rate
        self.dining_per_person = dining_per_person
        self.activity_per_stop = activity_per_stop
        self.fuel_efficiency_mpg = max(fuel_efficiency_mpg, 1.0)

    def compute_budget(
        self,
        preferences: Dict[str, Any],
        research: Dict[str, Any],
        itinerary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        days = max(1, self._safe_int(preferences.get("travel_days"), 1))
        travellers = max(1, self._safe_int(preferences.get("num_people"), 2))

        hotel_prices = [self._price_to_float(item.get("price")) for item in (research.get("hotels") or [])[:3]]
        hotel_rate = next((price for price in hotel_prices if price), self.default_hotel_rate)
        hotel_total = hotel_rate * days

        meals_per_day = max(2, min(3, travellers))
        dining_total = self.dining_per_person * travellers * meals_per_day * days

        total_stops = sum(len(day.get("stops", [])) for day in (itinerary or {}).get("days", []))
        if not total_stops and research.get("attractions"):
            total_stops = len(research["attractions"])
        activity_total = self.activity_per_stop * max(1, total_stops)

        car_needed = str(preferences.get("need_car_rental", "no")).lower() in {"yes", "y", "true"}
        car_price = 0.0
        if car_needed:
            rental = (research.get("car_rentals") or [{}])[0]
            car_price = self._price_to_float(rental.get("price"))

            # NOTE: fuel_prices dict now also contains car rental daily rates
            # (economy_car_daily, compact_car_daily, midsize_car_daily, suv_daily)
            # Available for future budget estimation enhancements
        transport_total = car_price

        fuel_price = self._estimate_fuel_cost(preferences, research, itinerary) if car_needed else 0.0
        transport_total += fuel_price

        total = hotel_total + dining_total + activity_total + transport_total
        return {
            "currency": "USD",
            "low": round(total * 0.85, 2),
            "expected": round(total, 2),
            "high": round(total * 1.2, 2),
            "breakdown": {
                "hotels": round(hotel_total, 2),
                "dining": round(dining_total, 2),
                "activities": round(activity_total, 2),
                "transport": round(transport_total, 2),
                "fuel": round(fuel_price, 2),
                "car_rental": round(car_price, 2),
            },
        }

    def _estimate_fuel_cost(
        self,
        preferences: Dict[str, Any],
        research: Dict[str, Any],
        itinerary: Optional[Dict[str, Any]],
    ) -> float:
        if not itinerary or not itinerary.get("days"):
            return 0.0

        price_info = research.get("fuel_prices") or {}
        price_per_gallon = self._to_float(price_info.get("regular"), default=3.75)

        total_distance_m = 0.0
        for day in itinerary.get("days", []):
            coords = [self._coord_tuple(stop.get("coord")) for stop in day.get("stops", [])]
            coords = [c for c in coords if c]
            total_distance_m += self._sum_route_distance(coords)

        if total_distance_m <= 0:
            return 0.0

        miles = total_distance_m / 1609.344
        gallons = miles / self.fuel_efficiency_mpg
        return max(0.0, round(gallons * price_per_gallon, 2))

    def _sum_route_distance(self, coords: Sequence[Optional[Tuple[float, float]]]) -> float:
        total = 0.0
        for origin, dest in zip(coords, coords[1:]):
            if not origin or not dest:
                continue
            try:
                result = distance_matrix.get_distance_matrix([origin], [dest], mode="DRIVE")
            except AssertionError:
                break
            except Exception:
                continue
            if not result:
                continue
            first = result[0]
            if first.get("status") == "OK" and first.get("distance_m"):
                total += float(first["distance_m"])
        return total

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

    def _price_to_float(self, price: Optional[Dict[str, Any]]) -> float:
        if isinstance(price, dict):
            return self._to_float(price.get("amount"), default=0.0)
        return self._to_float(price, default=0.0)

    def _to_float(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
