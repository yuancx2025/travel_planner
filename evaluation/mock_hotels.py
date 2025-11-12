# evaluation/mock_hotels.py
"""Mock hotel data for evaluation when Amadeus API is unavailable."""

from typing import List, Dict, Any


def get_mock_hotels(destination: str, num_people: int = 2) -> List[Dict[str, Any]]:
    """
    Generate realistic mock hotel data for evaluation.

    Args:
        destination: City name
        num_people: Number of travelers (affects price estimation)

    Returns:
        List of mock hotel objects matching the format from tools/hotels.py
    """
    # Price varies by city type
    base_price = 150
    city_lower = destination.lower()

    if any(
        city in city_lower for city in ["new york", "san francisco", "miami", "boston"]
    ):
        base_price = 200  # Expensive cities
    elif any(city in city_lower for city in ["orlando", "las vegas", "phoenix"]):
        base_price = 120  # Tourist cities
    elif any(city in city_lower for city in ["seattle", "chicago", "washington"]):
        base_price = 180  # Mid-tier cities

    # Generate 5 realistic hotels
    hotels = [
        {
            "hotel_id": f"mock_{destination.lower().replace(' ', '_')}_001",
            "name": f"Hilton {destination} Downtown",
            "address": f"123 Main Street, {destination}",
            "price": str(int(base_price * 1.3)),
            "currency": "USD",
            "rating": "4",
            "source": "mock",
            "raw": {},
        },
        {
            "hotel_id": f"mock_{destination.lower().replace(' ', '_')}_002",
            "name": f"Marriott {destination}",
            "address": f"456 Central Ave, {destination}",
            "price": str(int(base_price * 1.1)),
            "currency": "USD",
            "rating": "4",
            "source": "mock",
            "raw": {},
        },
        {
            "hotel_id": f"mock_{destination.lower().replace(' ', '_')}_003",
            "name": f"Holiday Inn {destination}",
            "address": f"789 Park Blvd, {destination}",
            "price": str(int(base_price * 0.85)),
            "currency": "USD",
            "rating": "3",
            "source": "mock",
            "raw": {},
        },
        {
            "hotel_id": f"mock_{destination.lower().replace(' ', '_')}_004",
            "name": f"Hyatt Regency {destination}",
            "address": f"321 Business District, {destination}",
            "price": str(int(base_price * 1.4)),
            "currency": "USD",
            "rating": "4",
            "source": "mock",
            "raw": {},
        },
        {
            "hotel_id": f"mock_{destination.lower().replace(' ', '_')}_005",
            "name": f"Comfort Inn {destination}",
            "address": f"654 Airport Rd, {destination}",
            "price": str(int(base_price * 0.7)),
            "currency": "USD",
            "rating": "3",
            "source": "mock",
            "raw": {},
        },
    ]

    return hotels
