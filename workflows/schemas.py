"""Pydantic schemas for structured agent outputs and user preferences."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# User Preferences Schema
# ============================================================================

class UserPreferences(BaseModel):
    """Structured user preferences with validation."""
    
    name: Optional[str] = None
    destination_city: Optional[str] = None
    travel_days: Optional[int] = Field(None, ge=1, description="Number of travel days")
    start_date: Optional[str] = None
    budget_usd: Optional[float] = Field(None, ge=0, description="Budget in USD")
    num_people: Optional[int] = Field(None, ge=1, description="Number of travelers")
    travelers: Optional[int] = Field(None, ge=1, description="Alternative field for num_people")
    kids: Optional[Union[str, int]] = None
    activity_pref: Optional[Union[str, List[str]]] = None
    need_car_rental: Optional[Union[str, bool]] = None
    hotel_room_pref: Optional[str] = None
    cuisine_pref: Optional[Union[str, List[str]]] = None
    origin_city: Optional[str] = None
    home_airport: Optional[str] = None
    destination_airport: Optional[str] = None
    specific_requirements: Optional[str] = None
    preferred_attractions: Optional[Union[str, List[str]]] = None
    preferred_restaurants: Optional[Union[str, List[str]]] = None
    temp_unit: Optional[str] = Field(None, description="Temperature unit: celsius or fahrenheit")
    currency: Optional[str] = Field(None, description="Currency code")
    
    @field_validator("activity_pref", "cuisine_pref", "preferred_attractions", "preferred_restaurants", mode="before")
    @classmethod
    def normalize_list_fields(cls, v: Any) -> Optional[Union[str, List[str]]]:
        """Normalize list fields to handle both string and list inputs."""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # If comma-separated, split it
            if "," in v:
                return [item.strip() for item in v.split(",") if item.strip()]
            return v
        return str(v)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format compatible with existing code."""
        result = {}
        for key, value in self.model_dump(exclude_none=True).items():
            if key == "travelers" and "num_people" not in result:
                result["num_people"] = value
            else:
                result[key] = value
        return result


# ============================================================================
# Itinerary Output Schema
# ============================================================================

class Coordinate(BaseModel):
    """Geographic coordinate."""
    lat: Optional[float] = None
    lng: Optional[float] = None


class Stop(BaseModel):
    """A single stop in an itinerary."""
    name: str
    address: Optional[str] = None
    coord: Optional[Coordinate] = None
    start_time: Optional[str] = None
    duration_hours: Optional[float] = None
    streetview_url: Optional[str] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None


class Route(BaseModel):
    """Route information for a day."""
    distance_m: Optional[float] = None
    duration_s: Optional[float] = None
    mode: Optional[str] = Field(None, description="Transport mode: DRIVE, WALK, etc.")
    legs: Optional[List[Dict[str, Any]]] = None
    raw: Optional[Dict[str, Any]] = None


class DaySchedule(BaseModel):
    """Schedule for a single day."""
    day: int = Field(ge=1, description="Day number")
    theme: Optional[str] = None
    stops: List[Stop] = Field(default_factory=list)
    route: Optional[Route] = None
    raw: Optional[Dict[str, Any]] = None


class ItineraryOutput(BaseModel):
    """Structured itinerary output."""
    days: List[DaySchedule] = Field(default_factory=list)
    meta: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format compatible with existing code."""
        result = {
            "days": [day.model_dump(exclude_none=True) for day in self.days]
        }
        if self.meta:
            result["meta"] = self.meta
        if self.raw:
            result["raw"] = self.raw
        return result


# ============================================================================
# Budget Output Schema
# ============================================================================

class BudgetBreakdown(BaseModel):
    """Breakdown of budget components."""
    hotels: float = Field(ge=0, default=0.0)
    dining: float = Field(ge=0, default=0.0)
    activities: float = Field(ge=0, default=0.0)
    transport: float = Field(ge=0, default=0.0)
    fuel: float = Field(ge=0, default=0.0)
    car_rental: float = Field(ge=0, default=0.0)


class BudgetOutput(BaseModel):
    """Structured budget output."""
    currency: str = Field(default="USD")
    expected: float = Field(ge=0, description="Expected total cost")
    low: float = Field(ge=0, description="Low estimate")
    high: float = Field(ge=0, description="High estimate")
    breakdown: BudgetBreakdown = Field(default_factory=BudgetBreakdown)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format compatible with existing code."""
        return self.model_dump(exclude_none=True)


# ============================================================================
# Research Output Schema
# ============================================================================

class Attraction(BaseModel):
    """Attraction information."""
    id: Optional[str] = None
    name: Optional[str] = None
    address: Optional[str] = None
    coord: Optional[Coordinate] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    source: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class Restaurant(BaseModel):
    """Restaurant information."""
    id: Optional[str] = None
    name: Optional[str] = None
    address: Optional[str] = None
    coord: Optional[Coordinate] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    price_level: Optional[Union[str, int]] = None
    source: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class Hotel(BaseModel):
    """Hotel information."""
    hotel_id: Optional[str] = None
    name: Optional[str] = None
    address: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    rating: Optional[float] = None
    source: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class WeatherDay(BaseModel):
    """Weather forecast for a day."""
    date: Optional[str] = None
    temp_max: Optional[float] = None
    temp_min: Optional[float] = None
    temp_high: Optional[float] = None
    temp_low: Optional[float] = None
    precip: Optional[float] = None
    precipitation: Optional[float] = None
    conditions: Optional[str] = None
    summary: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class ResearchOutput(BaseModel):
    """Structured research output."""
    attractions: List[Attraction] = Field(default_factory=list)
    dining: List[Restaurant] = Field(default_factory=list)
    hotels: List[Hotel] = Field(default_factory=list)
    weather: List[WeatherDay] = Field(default_factory=list)
    flights: List[Dict[str, Any]] = Field(default_factory=list)
    car_rentals: List[Dict[str, Any]] = Field(default_factory=list)
    fuel_prices: Optional[Dict[str, Any]] = None
    distances: List[Dict[str, Any]] = Field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format compatible with existing code."""
        result = {
            "attractions": [attr.model_dump(exclude_none=True) for attr in self.attractions],
            "dining": [rest.model_dump(exclude_none=True) for rest in self.dining],
            "hotels": [hotel.model_dump(exclude_none=True) for hotel in self.hotels],
            "weather": [w.model_dump(exclude_none=True) for w in self.weather],
            "flights": self.flights,
            "car_rentals": self.car_rentals,
            "distances": self.distances,
        }
        if self.fuel_prices:
            result["fuel_prices"] = self.fuel_prices
        if self.raw:
            result["raw"] = self.raw
        return result


# ============================================================================
# Critic Evaluation Schema
# ============================================================================

class BudgetViolation(BaseModel):
    """Budget violation details."""
    expected_budget: float
    actual_cost: float
    overage: float
    percentage_over: float


class RequirementViolation(BaseModel):
    """A single requirement violation."""
    requirement: str
    reason: str
    severity: str = Field(default="medium", description="low, medium, high")


class CriticEvaluation(BaseModel):
    """Critic's evaluation of itinerary against requirements."""
    requirements_met: bool
    failed_requirements: List[str] = Field(default_factory=list)
    budget_violation: Optional[BudgetViolation] = None
    violations: List[RequirementViolation] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class RequirementCheckResult(BaseModel):
    """Result of requirement validation with explanation."""
    passed: bool
    violations: List[RequirementViolation] = Field(default_factory=list)
    explanation: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)

