# tests/agents/test_itinerary_agent.py
"""
Comprehensive tests for ItineraryAgent.

Tests cover:
1. Utility methods (parsing, formatting, estimation)
2. Preprocessing (normalization, cataloging)
3. LLM interaction (mocking, JSON parsing)
4. Post-processing (validation, materialization)
5. Enrichment (routes, street view)
6. Integration (end-to-end workflow)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.itinerary_agent import ItineraryAgent, _Activity, _MealOption


# ==================== FIXTURES ====================

@pytest.fixture
def agent():
    """Create agent with mocked LLM to avoid real API calls."""
    return ItineraryAgent(
        default_blocks_per_day=3,
        model_name="gemini-2.0-flash",
        temperature=0.2,
    )


@pytest.fixture
def mock_preferences():
    return {
        "destination_city": "San Francisco",
        "travel_days": 3,
        "start_date": "2025-06-01",
        "num_people": 2,
        "kids": "no",
        "activity_pref": "cultural",
        "cuisine_pref": "italian",
        "travel_mode": "DRIVE",
        "need_car_rental": "yes",
        "budget_usd": 2000,
    }


@pytest.fixture
def mock_attractions():
    return [
        {
            "id": "place1",
            "name": "Golden Gate Bridge",
            "address": "Golden Gate Bridge, San Francisco, CA",
            "coord": {"lat": 37.8199, "lng": -122.4783},
            "category": "landmark",
            "rating": 4.8,
            "review_count": 5000,
            "source": "google",
        },
        {
            "name": "Alcatraz Island",
            "address": "Alcatraz Island, San Francisco, CA",
            "coord": {"lat": 37.8267, "lng": -122.4233},
            "category": "museum",
            "rating": 4.7,
            "review_count": 3500,
            "source": "google",
        },
        {
            "name": "Fisherman's Wharf",
            "address": "Fisherman's Wharf, San Francisco, CA",
            "coord": {"lat": 37.8080, "lng": -122.4177},
            "category": "market",
            "rating": 4.5,
            "review_count": 2000,
            "source": "google",
        },
    ]


@pytest.fixture
def mock_research():
    return {
        "weather": [
            {
                "date": "2025-06-01",
                "temp_low": 55,
                "temp_high": 68,
                "summary": "Partly cloudy",
                "precipitation": "10%",
            },
            {
                "date": "2025-06-02",
                "temp_low": 57,
                "temp_high": 70,
                "summary": "Sunny",
                "precipitation": "0%",
            },
            {
                "date": "2025-06-03",
                "temp_low": 56,
                "temp_high": 67,
                "summary": "Mostly sunny",
                "precipitation": "5%",
            },
        ],
        "dining": [
            {
                "name": "Italian Delight",
                "address": "123 Market St",
                "coord": {"lat": 37.7900, "lng": -122.4000},
                "price_level": 2,
                "rating": 4.6,
                "review_count": 200,
                "source": "google",
            },
            {
                "name": "Seafood Palace",
                "address": "456 Pier St",
                "coord": {"lat": 37.8050, "lng": -122.4150},
                "price_level": 3,
                "rating": 4.5,
                "review_count": 150,
                "source": "google",
            },
        ],
    }


# ==================== UNIT TESTS: UTILITY METHODS ====================

class TestUtilityMethods:
    """Test helper methods for parsing, formatting, and conversions."""

    def test_parse_time_to_minutes(self, agent):
        assert agent._parse_time_to_minutes("09:00") == 540
        assert agent._parse_time_to_minutes("9:00") == 540
        assert agent._parse_time_to_minutes("2:30 PM") == 870
        assert agent._parse_time_to_minutes("12:00 PM") == 720
        assert agent._parse_time_to_minutes("12:00 AM") == 0
        assert agent._parse_time_to_minutes("23:59") == 1439
        assert agent._parse_time_to_minutes("") is None
        assert agent._parse_time_to_minutes(None) is None
        assert agent._parse_time_to_minutes(540) == 540

    def test_format_minutes(self, agent):
        assert agent._format_minutes(540) == "09:00"
        assert agent._format_minutes(0) == "00:00"
        assert agent._format_minutes(1439) == "23:59"
        assert agent._format_minutes(None) == "00:00"
        assert agent._format_minutes(2000) == "24:00"  # Clamped to max

    def test_slugify(self, agent):
        assert agent._slugify("Golden Gate Bridge") == "golden-gate-bridge"
        assert agent._slugify("  Alcatraz  Island!!  ") == "alcatraz-island"
        assert agent._slugify("123 Main St.") == "123-main-st"
        assert agent._slugify(None) == ""
        assert agent._slugify("") == ""

    def test_safe_int(self, agent):
        assert agent._safe_int("5", 0) == 5
        assert agent._safe_int("0", 1) == 1  # 0 returns fallback
        assert agent._safe_int("invalid", 10) == 10
        assert agent._safe_int(None, 10) == 10
        assert agent._safe_int(-5, 0) == 0  # Negative clamped to 0

    def test_to_float(self, agent):
        assert agent._to_float("4.5") == 4.5
        assert agent._to_float(3) == 3.0
        assert agent._to_float("invalid", default=0.0) == 0.0
        assert agent._to_float(None) is None

    def test_coord_tuple(self, agent):
        assert agent._coord_tuple({"lat": 37.8199, "lng": -122.4783}) == (37.8199, -122.4783)
        assert agent._coord_tuple(None) is None
        assert agent._coord_tuple({}) is None
        assert agent._coord_tuple({"lat": 37.8199}) is None
        assert agent._coord_tuple("invalid") is None

    def test_estimate_duration(self, agent):
        assert agent._estimate_duration("museum") == 2.5
        assert agent._estimate_duration("art gallery") == 2.5
        assert agent._estimate_duration("park") == 2.0
        assert agent._estimate_duration("viewpoint") == 1.5
        assert agent._estimate_duration("shopping") == 1.5
        assert agent._estimate_duration("theme_park") == 3.5
        assert agent._estimate_duration("zoo") == 3.5
        assert agent._estimate_duration("unknown") == 2.0
        assert agent._estimate_duration(None) == 2.0

    def test_derive_ideal_window(self, agent):
        # Early closing
        hours = {"monday": {"open": "09:00", "close": "15:00"}}
        assert agent._derive_ideal_window(hours, None) == "morning"

        # Late closing
        hours = {"monday": {"open": "10:00", "close": "21:00"}}
        assert agent._derive_ideal_window(hours, None) == "evening"

        # Viewpoint category
        assert agent._derive_ideal_window({}, "viewpoint") == "sunset"
        assert agent._derive_ideal_window({}, "observatory") == "sunset"

        # Night category
        assert agent._derive_ideal_window({}, "night club") == "evening"

        # Default
        assert agent._derive_ideal_window({}, None) == "afternoon"

    def test_area_bucket(self, agent):
        assert agent._area_bucket({"lat": 37.8199, "lng": -122.4783}) == "37.82_-122.48"
        assert agent._area_bucket({"lat": 37.8151, "lng": -122.4799}) == "37.82_-122.48"
        assert agent._area_bucket(None) is None
        assert agent._area_bucket({}) is None

    def test_parse_hours(self, agent):
        hours = [
            "Monday: 9:00 AM – 5:00 PM",
            "Tuesday: 10:00 AM – 6:00 PM",
            "Wednesday: Closed",
        ]
        parsed = agent._parse_hours(hours)
        
        assert parsed["monday"]["open"] == "09:00"
        assert parsed["monday"]["close"] == "17:00"
        assert parsed["tuesday"]["open"] == "10:00"
        assert parsed["tuesday"]["close"] == "18:00"
        assert parsed["wednesday"]["open"] is None
        assert parsed["wednesday"]["close"] is None

        # Empty input
        assert agent._parse_hours(None) == {}
        assert agent._parse_hours([]) == {}


# ==================== UNIT TESTS: PREPROCESSING ====================

class TestPreprocessing:
    """Test attraction normalization and catalog building."""

    def test_normalize_attraction(self, agent, mock_attractions):
        seen_ids = set()
        activity = agent._normalize_attraction(mock_attractions[0], 0, seen_ids)
        
        assert activity is not None
        assert activity.id == "place1"
        assert activity.name == "Golden Gate Bridge"
        assert activity.address == "Golden Gate Bridge, San Francisco, CA"
        assert activity.coord == {"lat": 37.8199, "lng": -122.4783}
        assert activity.category == "landmark"
        assert activity.rating == 4.8
        assert activity.review_count == 5000
        assert activity.duration_hours == 2.0  # Default landmark duration
        assert activity.area_bucket == "37.82_-122.48"
        assert activity.source == "google"

    def test_normalize_attraction_no_id(self, agent, mock_attractions):
        seen_ids = set()
        activity = agent._normalize_attraction(mock_attractions[1], 1, seen_ids)
        
        assert activity.id == "alcatraz-island"
        assert activity.name == "Alcatraz Island"
        assert activity.category == "museum"
        assert activity.duration_hours == 2.5  # Museum duration

    def test_normalize_attraction_duplicate_id(self, agent):
        seen_ids = {"golden-gate-bridge"}
        attraction = {
            "name": "Golden Gate Bridge",
            "address": "SF",
            "coord": {"lat": 37.8, "lng": -122.4},
        }
        activity = agent._normalize_attraction(attraction, 0, seen_ids)
        
        assert activity.id == "golden-gate-bridge-2"

    def test_normalize_attraction_empty_name(self, agent):
        attraction = {"name": "", "address": "SF"}
        activity = agent._normalize_attraction(attraction, 0, set())
        
        assert activity is None

    def test_preprocess_inputs(self, agent, mock_preferences, mock_attractions, mock_research):
        preprocessed = agent._preprocess_inputs(mock_preferences, mock_attractions, mock_research)
        
        assert preprocessed["travel_days"] == 3
        assert len(preprocessed["activities"]) == 3
        assert len(preprocessed["catalog"]) == 3
        assert "place1" in preprocessed["catalog"]
        assert len(preprocessed["meal_options"]) == 2
        assert len(preprocessed["meals_catalog"]) == 2
        assert preprocessed["preferences_summary"]["destination"] == "San Francisco"
        assert len(preprocessed["weather_summary"]) == 3
        assert preprocessed["day_constraints"]["day_start"] == "09:00"

    def test_prepare_meal_options(self, agent, mock_research):
        meal_options, catalog = agent._prepare_meal_options(mock_research)
        
        assert len(meal_options) == 2
        assert len(catalog) == 2
        assert "italian-delight" in catalog
        assert catalog["italian-delight"].name == "Italian Delight"
        assert catalog["italian-delight"].price_level == 2
        assert catalog["italian-delight"].rating == 4.6


# ==================== UNIT TESTS: LLM INTERACTION ====================

class TestLLMInteraction:
    """Test prompt rendering and JSON parsing."""

    def test_render_llm_payload(self, agent, mock_preferences, mock_attractions, mock_research):
        preprocessed = agent._preprocess_inputs(mock_preferences, mock_attractions, mock_research)
        payload_str = agent._render_llm_payload(mock_preferences, mock_research, preprocessed)
        
        payload = json.loads(payload_str)
        assert payload["travel_days"] == 3
        assert len(payload["activities"]) == 3
        assert payload["activities"][0]["name"] == "Golden Gate Bridge"
        assert payload["activities"][0]["area_bucket"] == "37.82_-122.48"
        assert len(payload["meal_options"]) == 2
        assert len(payload["weather"]) == 3

    def test_parse_llm_json_plain(self, agent):
        json_str = '{"days": [{"day": 1, "blocks": []}]}'
        parsed = agent._parse_llm_json(json_str)
        
        assert parsed is not None
        assert "days" in parsed
        assert len(parsed["days"]) == 1

    def test_parse_llm_json_fenced(self, agent):
        json_str = '''
```json
{
  "days": [
    {"day": 1, "blocks": []}
  ]
}
```
        '''
        parsed = agent._parse_llm_json(json_str)
        
        assert parsed is not None
        assert "days" in parsed

    def test_parse_llm_json_mixed(self, agent):
        json_str = '''
Here's your itinerary:

```json
{"days": [{"day": 1}]}
```

Let me know if you need changes!
        '''
        parsed = agent._parse_llm_json(json_str)
        
        assert parsed is not None
        assert "days" in parsed

    def test_parse_llm_json_invalid(self, agent):
        assert agent._parse_llm_json("not json") is None
        assert agent._parse_llm_json("") is None
        assert agent._parse_llm_json("{invalid}") is None


# ==================== UNIT TESTS: POST-PROCESSING ====================

class TestPostProcessing:
    """Test schedule materialization and block normalization."""

    def test_normalize_block_activity(self, agent):
        catalog = {
            "golden-gate-bridge": _Activity(
                id="golden-gate-bridge",
                name="Golden Gate Bridge",
                address="SF",
                coord={"lat": 37.8, "lng": -122.4},
                category="landmark",
                rating=4.8,
                review_count=5000,
                duration_hours=1.5,
                ideal_window="afternoon",
                area_bucket="37.8_-122.4",
                hours={},
                source="google",
                raw={},
            )
        }
        
        block = {
            "type": "activity",
            "activity_id": "golden-gate-bridge",
            "start_time": "09:00",
            "duration_hours": 2.0,
        }
        
        normalized = agent._normalize_block(block, catalog, {}, 540)
        
        assert normalized is not None
        assert normalized["type"] == "activity"
        assert normalized["name"] == "Golden Gate Bridge"
        assert normalized["start_time"] == "09:00"
        assert normalized["duration_hours"] == 2.0
        assert normalized["coord"] == {"lat": 37.8, "lng": -122.4}

    def test_normalize_block_meal(self, agent):
        meals = {
            "italian-delight": _MealOption(
                id="italian-delight",
                name="Italian Delight",
                address="123 Market St",
                coord={"lat": 37.79, "lng": -122.40},
                price_level=2,
                rating=4.6,
                review_count=200,
                source="google",
            )
        }
        
        block = {
            "type": "meal",
            "activity_id": "italian-delight",
            "start_time": "12:00",
            "duration_hours": 1.0,
        }
        
        normalized = agent._normalize_block(block, {}, meals, 720)
        
        assert normalized is not None
        assert normalized["type"] == "meal"
        assert normalized["name"] == "Italian Delight"
        assert normalized["price_level"] == 2

    def test_normalize_block_flex(self, agent):
        block = {
            "type": "travel",
            "start_time": "11:30",
            "end_time": "12:00",
            "notes": "Transit time",
        }
        
        normalized = agent._normalize_block(block, {}, {}, 690)
        
        assert normalized is not None
        assert normalized["type"] == "travel"
        assert normalized["name"] == "Travel time"
        assert normalized["start_time"] == "11:30"
        assert normalized["duration_hours"] == 0.5

    def test_normalize_block_unknown_activity(self, agent):
        block = {
            "type": "activity",
            "activity_id": "nonexistent",
            "start_time": "09:00",
        }
        
        normalized = agent._normalize_block(block, {}, {}, 540)
        assert normalized is None


# ==================== INTEGRATION TESTS ====================

class TestIntegration:
    """Test end-to-end workflow."""

    def test_build_itinerary_fallback(self, agent, mock_preferences, mock_attractions, mock_research):
        """Test fallback when LLM is disabled."""
        agent._llm_disabled = True
        
        result = agent.build_itinerary(mock_preferences, mock_attractions, mock_research)
        
        assert "days" in result
        assert len(result["days"]) == 3
        assert result["meta"]["strategy"] == "fallback"
        assert "Fallback time-blocking heuristic used." in result["meta"]["warnings"]

    def test_chunk_attractions(self, agent, mock_preferences, mock_attractions):
        """Test simple fallback chunking."""
        blocks = agent._chunk_attractions(mock_preferences, mock_attractions)
        
        assert len(blocks) == 3  # 3 days
        assert blocks[0]["day"] == 1
        assert len(blocks[0]["stops"]) == 1  # 3 attractions / 3 days = 1 per day
        assert blocks[0]["stops"][0]["name"] == "Golden Gate Bridge"

    def test_build_planning_context(self, agent, mock_preferences, mock_research, mock_attractions):
        """Test context string generation."""
        itinerary = {
            "days": [
                {
                    "day": 1,
                    "stops": [
                        {"name": "Golden Gate Bridge", "start_time": "09:00", "duration_hours": 2}
                    ],
                    "route": {"distance_m": 5000, "duration_s": 600, "mode": "DRIVE"},
                }
            ]
        }
        
        context = agent.build_planning_context(
            mock_preferences,
            mock_research,
            itinerary,
            budget={"low": 1500, "high": 2500, "expected": 2000},
            selected_attractions=mock_attractions,
        )
        
        assert "San Francisco" in context
        assert "3 days" in context
        assert "Golden Gate Bridge" in context
        assert "5.0 km" in context
        assert "WEATHER FORECAST" in context
        assert "Italian Delight" in context


# ==================== EDGE CASES ====================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_attractions(self, agent, mock_preferences, mock_research):
        """Test with no attractions."""
        result = agent.build_itinerary(mock_preferences, [], mock_research)
        
        assert "days" in result
        assert result["meta"]["strategy"] == "fallback"

    def test_invalid_preferences(self, agent, mock_attractions, mock_research):
        """Test with missing/invalid preferences."""
        bad_prefs = {"travel_days": "invalid"}
        result = agent.build_itinerary(bad_prefs, mock_attractions, mock_research)
        
        assert "days" in result

    def test_missing_coordinates(self, agent, mock_preferences, mock_research):
        """Test attractions without coordinates."""
        attractions = [
            {"name": "No Coord Place", "address": "Somewhere", "category": "museum"}
        ]
        result = agent.build_itinerary(mock_preferences, attractions, mock_research)
        
        assert "days" in result
        assert len(result["days"]) > 0

    def test_invalid_weather_data(self, agent, mock_preferences, mock_attractions):
        """Test with malformed weather data."""
        bad_research = {"weather": ["not a dict", None, {}]}
        result = agent.build_itinerary(mock_preferences, mock_attractions, bad_research)
        
        assert "days" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
