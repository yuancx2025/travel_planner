from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

import config
from agents.prompts import load_prompt_template
from tools import distance_matrix
from workflows.schemas import (
    BudgetOutput,
    BudgetBreakdown,
    BudgetViolation,
    CriticEvaluation,
    RequirementCheckResult,
    RequirementViolation,
    UserPreferences,
    ItineraryOutput,
)


class BudgetAgent:
    """Estimate trip budget components, including fuel derived from distance matrix."""

    def __init__(
        self,
        *,
        default_hotel_rate: float = None,
        dining_per_person: float = None,
        activity_per_stop: float = None,
        fuel_efficiency_mpg: float = None,
        model_name: str = None,
        temperature: float = None,
        llm: Optional[ChatGoogleGenerativeAI] = None,
        explain_failure_prompt: Optional[Any] = None,
        explain_failure_user_prompt: Optional[Any] = None,
    ) -> None:
        self.default_hotel_rate = default_hotel_rate if default_hotel_rate is not None else config.BUDGET_DEFAULT_HOTEL_RATE
        self.dining_per_person = dining_per_person if dining_per_person is not None else config.BUDGET_DINING_PER_PERSON
        self.activity_per_stop = activity_per_stop if activity_per_stop is not None else config.BUDGET_ACTIVITY_PER_STOP
        self.fuel_efficiency_mpg = max(fuel_efficiency_mpg if fuel_efficiency_mpg is not None else config.BUDGET_FUEL_EFFICIENCY_MPG, 1.0)
        self.model_name = model_name if model_name is not None else config.DEFAULT_MODEL_NAME
        self.temperature = temperature if temperature is not None else config.DEFAULT_TEMPERATURE
        self._llm: Optional[ChatGoogleGenerativeAI] = llm
        self._llm_disabled = False
        
        # Load prompt templates
        self.explain_failure_prompt = explain_failure_prompt or load_prompt_template("explain_failure", "explain_failure.md")
        self.explain_failure_user_prompt = explain_failure_user_prompt or load_prompt_template("explain_failure_user", "explain_failure_user.md")
        
    def _ensure_llm(self) -> Optional[ChatGoogleGenerativeAI]:
        """Lazy initialization of LLM."""
        if self._llm_disabled:
            return None
        if self._llm is None:
            if not config.get_google_api_key():
                self._llm_disabled = True
                return None
            try:
                self._llm = ChatGoogleGenerativeAI(
                    model=self.model_name,
                    temperature=self.temperature,
                )
            except Exception:
                self._llm_disabled = True
                return None
        return self._llm

    def compute_budget(
        self,
        preferences: Dict[str, Any],
        research: Dict[str, Any],
        itinerary: Optional[Dict[str, Any]] = None,
    ) -> BudgetOutput:
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
        return BudgetOutput(
            currency="USD",
            low=round(total * 0.85, 2),
            expected=round(total, 2),
            high=round(total * 1.2, 2),
            breakdown=BudgetBreakdown(
                hotels=round(hotel_total, 2),
                dining=round(dining_total, 2),
                activities=round(activity_total, 2),
                transport=round(transport_total, 2),
                fuel=round(fuel_price, 2),
                car_rental=round(car_price, 2),
            ),
        )

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
            route_distance = self._route_distance(day.get("route"))
            if route_distance > 0:
                total_distance_m += route_distance
                continue

            coords = [self._coord_tuple(stop.get("coord")) for stop in day.get("stops", [])]
            coords = [c for c in coords if c]
            total_distance_m += self._sum_route_distance(coords)

        if total_distance_m <= 0:
            return 0.0

        miles = total_distance_m / 1609.344
        gallons = miles / self.fuel_efficiency_mpg
        return max(0.0, round(gallons * price_per_gallon, 2))

    def _route_distance(self, route: Optional[Dict[str, Any]]) -> float:
        if not route:
            return 0.0

        distance = self._to_float(route.get("distance_m"), default=0.0)
        if distance > 0:
            return distance

        legs = route.get("legs") if isinstance(route, dict) else None
        if isinstance(legs, Sequence):
            leg_total = 0.0
            for leg in legs:
                if not isinstance(leg, dict):
                    continue
                leg_total += self._to_float(leg.get("distance_m"), default=0.0)
            if leg_total > 0:
                return leg_total

        return 0.0

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
    
    # ============================================================================
    # Critic Functionality
    # ============================================================================
    
    def evaluate_requirements(
        self,
        preferences: UserPreferences,
        itinerary: ItineraryOutput,
        budget: BudgetOutput,
    ) -> CriticEvaluation:
        """
        Evaluate itinerary against user requirements.
        Returns CriticEvaluation with requirements_met flag and violations.
        """
        failed_requirements: List[str] = []
        violations: List[RequirementViolation] = []
        budget_violation: Optional[BudgetViolation] = None
        suggestions: List[str] = []
        
        # Check budget constraint (more lenient - only fail if significantly over)
        budget_usd = preferences.budget_usd
        if budget_usd is not None and budget.expected > budget_usd:
            overage = budget.expected - budget_usd
            percentage_over = (overage / budget_usd) * 100
            budget_violation = BudgetViolation(
                expected_budget=budget_usd,
                actual_cost=budget.expected,
                overage=overage,
                percentage_over=percentage_over,
            )
            # Only fail if overage is more than 15% (more lenient threshold)
            if percentage_over > 15:
                failed_requirements.append(f"Budget exceeded by ${overage:.2f} ({percentage_over:.1f}%)")
                violations.append(RequirementViolation(
                    requirement="budget",
                    reason=f"Expected budget: ${budget_usd:.2f}, Actual cost: ${budget.expected:.2f}",
                    severity="high" if percentage_over > 30 else "medium",
                ))
                suggestions.append(f"Consider reducing activities or choosing more budget-friendly options")
            else:
                # Small overage - just note it, don't fail
                suggestions.append(f"Budget is slightly over by ${overage:.2f} ({percentage_over:.1f}%) - consider minor adjustments")
        
        # Check activity preferences (more lenient matching)
        activity_pref = preferences.activity_pref
        if activity_pref:
            # Normalize to list for checking
            if isinstance(activity_pref, str):
                activity_pref_list = [activity_pref.lower()]
            else:
                activity_pref_list = [a.lower() if isinstance(a, str) else str(a).lower() for a in activity_pref]
            
            # Check if itinerary includes activities matching preferences
            itinerary_activities = []
            itinerary_text = ""  # Full text for fuzzy matching
            for day in itinerary.days:
                for stop in day.stops:
                    if stop.category:
                        itinerary_activities.append(stop.category.lower())
                        itinerary_text += " " + stop.category.lower()
                    if stop.name:
                        itinerary_activities.append(stop.name.lower())
                        itinerary_text += " " + stop.name.lower()
            
            # More lenient matching: check for keywords and synonyms
            # Map common activity preferences to related keywords
            activity_synonyms = {
                "outdoor": ["outdoor", "adventure", "park", "trail", "hiking", "nature", "wildlife", "camping", "kayak", "canoe", "climbing"],
                "adventure": ["adventure", "outdoor", "extreme", "thrill", "exciting", "active"],
                "cultural": ["cultural", "museum", "art", "history", "heritage", "gallery", "monument"],
                "relaxing": ["relaxing", "spa", "beach", "pool", "quiet", "peaceful", "zen"],
                "family": ["family", "kids", "children", "playground", "zoo", "aquarium"],
            }
            
            matches = False
            for pref in activity_pref_list:
                # Direct keyword match
                if any(pref in activity for activity in itinerary_activities) or pref in itinerary_text:
                    matches = True
                    break
                # Synonym matching
                synonyms = activity_synonyms.get(pref, [])
                if synonyms:
                    if any(syn in itinerary_text for syn in synonyms):
                        matches = True
                        break
            
            # Only fail if we have activities but NO matches at all (more lenient)
            if not matches and itinerary_activities:
                # Make this a low-severity violation, not a blocker
                violations.append(RequirementViolation(
                    requirement="activity_preferences",
                    reason=f"Requested: {', '.join(activity_pref_list)}, Found: {', '.join(itinerary_activities[:3])}",
                    severity="low",  # Changed from "medium" to "low"
                ))
                # Don't add to failed_requirements - just note it as a suggestion
                suggestions.append(f"Consider adding more {', '.join(activity_pref_list)} activities if desired")
        
        # Check cuisine preferences
        cuisine_pref = preferences.cuisine_pref
        if cuisine_pref:
            # This is harder to check without restaurant data in itinerary
            # For now, we'll note it but not fail on it
            pass
        
        # Check hotel preferences
        hotel_room_pref = preferences.hotel_room_pref
        if hotel_room_pref:
            # Hotel preferences are handled during research phase
            # We can note if budget allows for preferred hotel type
            pass
        
        # Check travel days match (allow ±1 day flexibility)
        travel_days = preferences.travel_days
        if travel_days is not None:
            actual_days = len(itinerary.days)
            day_diff = abs(actual_days - travel_days)
            # Only fail if difference is more than 1 day (more lenient)
            if day_diff > 1:
                failed_requirements.append(f"Expected {travel_days} days, itinerary has {actual_days} days")
                violations.append(RequirementViolation(
                    requirement="travel_days",
                    reason=f"Requested: {travel_days} days, Planned: {actual_days} days",
                    severity="low",
                ))
            elif day_diff == 1:
                # Just note it, don't fail
                suggestions.append(f"Itinerary has {actual_days} days instead of {travel_days} days")
        
        # Consider requirements met if:
        # 1. No failed requirements, OR
        # 2. Only low-severity violations (and no budget violation)
        has_only_low_severity = all(
            v.severity == "low" for v in violations
        ) and budget_violation is None
        
        requirements_met = len(failed_requirements) == 0 or has_only_low_severity
        
        return CriticEvaluation(
            requirements_met=requirements_met,
            failed_requirements=failed_requirements,
            budget_violation=budget_violation,
            violations=violations,
            suggestions=suggestions,
        )
    
    def explain_failure(
        self,
        evaluation: CriticEvaluation,
        preferences: Optional[UserPreferences] = None,
    ) -> RequirementCheckResult:
        """
        Generate LLM-based explanation for why requirements were not met.
        Returns RequirementCheckResult with explanation and suggestions.
        """
        model = self._ensure_llm()
        if model is None:
            # Fallback to simple explanation without LLM
            explanation = "Unfortunately, the itinerary does not meet all your requirements:\n\n"
            for req in evaluation.failed_requirements:
                explanation += f"- {req}\n"
            if evaluation.suggestions:
                explanation += "\nSuggestions:\n"
                for suggestion in evaluation.suggestions:
                    explanation += f"- {suggestion}\n"
            return RequirementCheckResult(
                passed=False,
                violations=evaluation.violations,
                explanation=explanation,
                suggestions=evaluation.suggestions,
            )
        
        # Build context for LLM
        context_parts = []
        if evaluation.budget_violation:
            context_parts.append(
                f"Budget exceeded: Expected ${evaluation.budget_violation.expected_budget:.2f}, "
                f"Actual ${evaluation.budget_violation.actual_cost:.2f} "
                f"({evaluation.budget_violation.percentage_over:.1f}% over budget)"
            )
        if evaluation.failed_requirements:
            context_parts.append(f"Failed requirements: {', '.join(evaluation.failed_requirements)}")
        if preferences:
            context_parts.append(f"User preferences: Budget ${preferences.budget_usd or 'N/A'}, "
                              f"{preferences.travel_days or 'N/A'} days, "
                              f"Activity: {preferences.activity_pref or 'N/A'}")
        
        system_prompt = self.explain_failure_prompt.text
        
        user_prompt = self.explain_failure_user_prompt.format(
            issues_context="\n".join(context_parts)
        )
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = model.invoke(messages)
            content = getattr(response, "content", "")
            if isinstance(content, list):
                content = "".join(str(part) for part in content)
            explanation = str(content).strip()
        except Exception:
            # Fallback if LLM fails
            explanation = "Unfortunately, the itinerary does not meet all your requirements. "
            if evaluation.budget_violation:
                explanation += f"The budget is exceeded by ${evaluation.budget_violation.overage:.2f}. "
            explanation += "Please consider adjusting your preferences or budget."
        
        # Combine LLM explanation with structured suggestions
        all_suggestions = evaluation.suggestions.copy()
        if evaluation.budget_violation:
            all_suggestions.append(
                f"Consider reducing the number of activities or choosing more budget-friendly options "
                f"to save approximately ${evaluation.budget_violation.overage:.2f}"
            )
        
        return RequirementCheckResult(
            passed=False,
            violations=evaluation.violations,
            explanation=explanation,
            suggestions=all_suggestions,
        )
