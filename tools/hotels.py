# hotels.py
import os
from amadeus import Client, ResponseError
from dotenv import load_dotenv

# Load .env with your credentials
dotenv_path = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(dotenv_path)

# Initialize the Amadeus client
amadeus = Client(
    client_id=os.getenv("AMADEUS_API_KEY"),
    client_secret=os.getenv("AMADEUS_API_SECRET"),
)

# Common city name → IATA airport code (fast path, no API call)
CITY_TO_IATA = {
    # US cities
    "new york": "JFK", "nyc": "JFK", "new york city": "JFK",
    "los angeles": "LAX", "la": "LAX",
    "san francisco": "SFO", "sf": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "las vegas": "LAS",
    "seattle": "SEA",
    "boston": "BOS",
    "washington": "IAD", "dc": "IAD", "washington dc": "IAD",
    "atlanta": "ATL",
    "dallas": "DFW",
    "houston": "IAH",
    "phoenix": "PHX",
    "philadelphia": "PHL",
    "san diego": "SAN",
    "denver": "DEN",
    "orlando": "MCO",
    "durham": "RDU", "raleigh": "RDU", "raleigh-durham": "RDU",
    "chapel hill": "RDU",
    "salt lake city": "SLC", "slc": "SLC",
    "portland": "PDX",
    "austin": "AUS",
    "nashville": "BNA",
}


def _resolve_city_code(city_input: str) -> str:
    city_clean = city_input.strip().lower()
    
    # Fast path: already a 3-letter IATA code
    if len(city_clean) == 3 and city_clean.isalpha():
        return city_clean.upper()
    
    # Fast path: known city in lookup table
    if city_clean in CITY_TO_IATA:
        return CITY_TO_IATA[city_clean]
    
    # Unknown city - provide helpful error
    raise ValueError(
        f"Could not resolve city '{city_input}' to IATA code.\n"
        f"Look up your airport code: https://www.iata.org/en/publications/directories/code-search/"
    )


def search_hotels_by_city(city_code, check_in, check_out, adults=2, limit=10):
    """
    Search for hotels using Amadeus Hotel Search API.
    
    Args:
        city_code (str): City name (e.g., 'Durham', 'Salt Lake City') or IATA code (e.g., 'RDU', 'SLC')
        check_in (str): Check-in date YYYY-MM-DD
        check_out (str): Check-out date YYYY-MM-DD
        adults (int): Number of adults (default: 2)
        limit (int): Max number of hotels to fetch (default: 10)
    
    Returns:
        list of dict: [{hotel_id, name, address, price, currency, rating, source}, ...]
    """
    try:
        # Resolve city name to IATA code
        resolved_code = _resolve_city_code(city_code)
        
        # 1️⃣ Get hotel IDs for the city
        hotel_list = amadeus.reference_data.locations.hotels.by_city.get(
            cityCode=resolved_code
        )
        
        if not hotel_list.data:
            print(f"⚠️  No hotels found for '{city_code}' (resolved to {resolved_code}).")
            return []
        
        # Take multiple hotels to increase chance of finding availability
        hotel_ids = [h["hotelId"] for h in hotel_list.data[:limit]]
        print(f"🔍 Found {len(hotel_ids)} hotels near '{city_code}' ({resolved_code}), checking availability...")

        # 2️⃣ Get offers for those hotels (batch query)
        response = amadeus.shopping.hotel_offers_search.get(
            hotelIds=",".join(hotel_ids),
            checkInDate=check_in,
            checkOutDate=check_out,
            adults=adults,
            roomQuantity=1,
            currency="USD",
            bestRateOnly=True,  # Improves availability filtering
        )

        if not response.data:
            print(f"⚠️  No availability for {check_in} to {check_out} near '{city_code}'.")
            print("💡 Try different dates or increase limit parameter.")
            return []

        results = []
        for offer in response.data:
            hotel = offer.get("hotel", {})
            offers_list = offer.get("offers", [])
            if not offers_list:
                continue
            
            price = offers_list[0].get("price", {})
            results.append(
                {
                    "hotel_id": hotel.get("hotelId"),
                    "name": hotel.get("name"),
                    "address": hotel.get("address", {}).get("lines", ["N/A"])[0],
                    "price": price.get("total"),
                    "currency": price.get("currency"),
                    "rating": hotel.get("rating"),
                    "source": "amadeus",
                }
            )

        return results

    except ValueError as e:
        # City resolution error
        print(f"❌ {e}")
        return []
    except ResponseError as error:
        print(f"❌ Amadeus API error: {error}")
        if hasattr(error, "response") and error.response:
            print(f"Details: {error.response.body}")
        
        # Common error guidance
        error_str = str(error)
        if "NO ROOMS AVAILABLE" in error_str:
            print("\n💡 Tips:")
            print("  - Try different dates (avoid peak season/holidays)")
            print("  - Increase the limit parameter to search more hotels")
            print(f"  - Use a nearby airport code (e.g., {_resolve_city_code(city_code)})")
        elif "INVALID FORMAT" in error_str or "cityCode" in error_str:
            print("\n💡 Use 3-letter IATA airport codes or supported city names")
            print("  Check docs/HOTEL_CITY_CODES.md for the full list")
        
        return []