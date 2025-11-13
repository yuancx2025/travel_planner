# hotels.py
import os
import time
import requests
from dotenv import load_dotenv

# Load .env with your credentials
dotenv_path = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(dotenv_path)

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY")
if not GOOGLE_API_KEY:
    raise RuntimeError(
        "Missing GOOGLE_MAPS_API_KEY (or GOOGLE_PLACES_API_KEY) in environment."
    )

# Endpoints (Classic Places API)
PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Optional: limit fields we fetch from Place Details to save quota/time
DETAILS_FIELDS = "place_id,name,formatted_address,rating,price_level,user_ratings_total,geometry,website,international_phone_number"

# Common city name → IATA airport code (fast path, no API call)
CITY_TO_IATA = {
    # US cities
    "new york": "JFK",
    "nyc": "JFK",
    "new york city": "JFK",
    "los angeles": "LAX",
    "la": "LAX",
    "san francisco": "SFO",
    "sf": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "las vegas": "LAS",
    "seattle": "SEA",
    "boston": "BOS",
    "washington": "IAD",
    "dc": "IAD",
    "washington dc": "IAD",
    "atlanta": "ATL",
    "dallas": "DFW",
    "houston": "IAH",
    "phoenix": "PHX",
    "philadelphia": "PHL",
    "san diego": "SAN",
    "denver": "DEN",
    "orlando": "MCO",
    "durham": "RDU",
    "raleigh": "RDU",
    "raleigh-durham": "RDU",
    "chapel hill": "RDU",
    "salt lake city": "SLC",
    "slc": "SLC",
    "portland": "PDX",
    "austin": "AUS",
    "nashville": "BNA",
}

def _text_search_hotels_in_city(city: str, page_size: int = 20):
    """
    Generator that yields hotel (lodging) results for a city using Text Search.
    """
    params = {
        "query": f"hotels in {city}",
        "type": "lodging",
        "key": GOOGLE_API_KEY,
    }

    while True:
        resp = requests.get(PLACES_TEXT_SEARCH_URL, params=params, timeout=20)
        data = resp.json()

        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            # Common statuses: OVER_QUERY_LIMIT, REQUEST_DENIED, INVALID_REQUEST
            raise RuntimeError(
                f"Google Places Text Search error: {data.get('status')} - {data.get('error_message')}"
            )

        for r in data.get("results", []):
            yield r

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break

        # Per Google docs: you must wait a short time before using next_page_token
        time.sleep(2)
        params = {"pagetoken": next_page_token, "key": GOOGLE_API_KEY}


def _maybe_get_place_details(place_id: str) -> dict:
    """
    Optional: fetch extra fields via Place Details (price_level, website, phone, etc.).
    You can comment this out to save quota if Text Search fields are enough.
    """
    params = {
        "place_id": place_id,
        "fields": DETAILS_FIELDS,
        "key": GOOGLE_API_KEY,
    }
    resp = requests.get(PLACES_DETAILS_URL, params=params, timeout=20)
    data = resp.json()
    if data.get("status") != "OK":
        # Fail softly; just return empty dict
        return {}
    return data.get("result", {}) or {}


def search_hotels_by_city(city_code, check_in, check_out, adults=2, limit=10):
    """
    Search for hotels using Google Places (Text Search + optional Details).

    Args:
        city_code (str): City name (e.g., 'Durham', 'Salt Lake City') or any text query for the city/area.
        check_in (str): Check-in date YYYY-MM-DD (not used by Google Places; kept for compatibility)
        check_out (str): Check-out date YYYY-MM-DD (not used by Google Places; kept for compatibility)
        adults (int): Number of adults (not used by Google Places; kept for compatibility)
        limit (int): Max number of hotels to fetch (default: 10)

    Returns:
        list of dict: [{hotel_id, name, address, price, currency, rating, source, raw}, ...]
                      price/currency are None because Places API does not expose room rates.
    """
    # IMPORTANT NOTE:
    # Google Places API does NOT provide real-time room availability or pricing.
    # This function returns metadata (name, address, rating, etc.). If you need pricing,
    # you'll need to integrate a booking/OTA API.

    try:
        results = []
        seen_ids = set()

        for item in _text_search_hotels_in_city(str(city_code)):
            if len(results) >= limit:
                break

            place_id = item.get("place_id")
            if not place_id or place_id in seen_ids:
                continue
            seen_ids.add(place_id)

            # Pull fields available from Text Search
            name = item.get("name")
            address = item.get("formatted_address") or item.get("vicinity")
            rating = item.get("rating")
            # price_level here is Google's 0..4 "relative cost" index, not actual price
            price_level = item.get("price_level")

            # Optionally enrich with Place Details (can comment out to save quota)
            details = _maybe_get_place_details(place_id) or {}
            if details:
                name = details.get("name", name)
                address = details.get("formatted_address", address)
                rating = details.get("rating", rating)
                price_level = details.get("price_level", price_level)

            # Normalize to your previous schema
            results.append(
                {
                    "hotel_id": place_id,
                    "name": name,
                    "address": address or "N/A",
                    "price": None,  # Not available from Google Places
                    "currency": None,  # Not available from Google Places
                    "rating": rating,
                    "price_level": price_level,  # 0..4 (optional extra)
                    "source": "google_places",
                    "raw": (
                        {"text_search": item, "details": details}
                        if details
                        else {"text_search": item}
                    ),
                }
            )

        if not results:
            print(f"⚠️  No hotels found for '{city_code}'.")
            return []

        return results

    except Exception as e:
        print(f"❌ Google Places error: {e}")
        # Friendly guidance for common issues
        msg = str(e)
        if (
            "REQUEST_DENIED" in msg
            or "API keys with referer restrictions cannot be used" in msg
        ):
            print(
                "\n💡 Check your API key, billing status, and domain/IP restrictions in Google Cloud Console."
            )
            print("   Required APIs: Places API (and optionally Place Details).")
        elif "OVER_QUERY_LIMIT" in msg:
            print(
                "\n💡 You've hit a quota or rate limit. Consider delaying requests, adding caching, or increasing quota."
            )
        return []
