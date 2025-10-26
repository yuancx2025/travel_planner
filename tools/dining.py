# tools/dining.py
"""Restaurant search using Google Places API."""
import os, httpx
from typing import List, Dict, Any, Optional

GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

def search_restaurants(latitude: float, longitude: float, radius: int = 1500, 
                      keyword: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search for restaurants near a location.
    Args:
        latitude, longitude: Search center coordinates
        radius: Search radius in meters (default 1500)
        keyword: Optional keyword (e.g., 'sushi', 'vegan')
    Returns:
        List of {"name", "rating", "address", "lat", "lng", "price_level"}
    """
    if not GOOGLE_API_KEY:
        raise ValueError("Missing GOOGLE_MAPS_API_KEY")
    
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{latitude},{longitude}",
        "radius": radius,
        "type": "restaurant",
        "key": GOOGLE_API_KEY,
    }
    if keyword:
        params["keyword"] = keyword
    
    with httpx.Client(timeout=10) as client:
        r = client.get(url, params=params)
        data = r.json()
    
    if data.get("status") != "OK":
        return []
    
    return [
        {
            "name": p.get("name"),
            "rating": p.get("rating"),
            "address": p.get("vicinity"),
            "lat": p["geometry"]["location"]["lat"],
            "lng": p["geometry"]["location"]["lng"],
            "price_level": p.get("price_level"),
        }
        for p in data["results"]
    ]
