# tools/dining.py
import os
import requests
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(dotenv_path)

def search_restaurants(latitude, longitude, radius=1500, keyword=None):
    """
    Search for restaurants near a given location using Google Maps Places API.

    Parameters:
        api_key (str): Your Google Maps API key
        latitude (float): Latitude of the search location
        longitude (float): Longitude of the search location
        radius (int): Search radius in meters (default 1500)
        keyword (str): Optional keyword to refine search (e.g., 'sushi', 'vegan')

    Returns:
        list: A list of restaurant dictionaries with name, rating, address, and coordinates
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise ValueError("Missing environment variable: GOOGLE_MAPS_API_KEY")
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{latitude},{longitude}",
        "radius": radius,
        "type": "restaurant",
        "key": api_key,
    }

    if keyword:
        params["keyword"] = keyword

    response = requests.get(url, params=params)
    data = response.json()

    if data.get("status") != "OK":
        print(f"Error: {data.get('status')}, {data.get('error_message', '')}")
        return []

    restaurants = []
    for place in data["results"]:
        restaurants.append(
            {
                "name": place.get("name"),
                "rating": place.get("rating"),
                "address": place.get("vicinity"),
                "lat": place["geometry"]["location"]["lat"],
                "lng": place["geometry"]["location"]["lng"],
                "price_level": place.get("price_level"),
            }
        )

    return restaurants
