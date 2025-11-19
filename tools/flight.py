# tools/flight.py

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
    hostname="production",
)


def search_flights(
    origin,
    destination,
    departure_date,
    return_date=None,
    adults=1,
    max_results=5,
    currency="USD",
):
    """
    Search for flights using the Amadeus Flight Offers API.

    Args:
        origin (str): IATA code of the departure airport (e.g., 'JFK')
        destination (str): IATA code of the destination airport (e.g., 'LHR')
        departure_date (str): YYYY-MM-DD
        return_date (str): Optional, for round-trip
        adults (int): Number of adult passengers
        max_results (int): Max number of results to display
        currency (str): Currency for prices

    Returns:
        list of dict: Flight offers with airline, price, duration, and route
    """
    try:
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": adults,
            "max": max_results,
            "currencyCode": currency,
        }
        if return_date:
            params["returnDate"] = return_date

        response = amadeus.shopping.flight_offers_search.get(**params)
        data = response.data

        results = []
        for offer in data:
            itineraries = offer.get("itineraries", [])
            price = offer.get("price", {}).get("total")
            carrier = (
                offer["validatingAirlineCodes"][0]
                if "validatingAirlineCodes" in offer
                else "N/A"
            )
            duration = itineraries[0].get("duration") if itineraries else "N/A"

            results.append(
                {
                    "carrier": carrier,
                    "price": price,
                    "currency": offer["price"]["currency"],
                    "duration": duration,
                    "origin": origin,
                    "destination": destination,
                    "departure_date": departure_date,
                    "return_date": return_date or None,
                }
            )

        return results

    except ResponseError as error:
        print("❌ Amadeus API error:", error)
        return []
