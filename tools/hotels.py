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


def search_hotels_by_city(city_code, check_in, check_out):
    try:
        # 1️⃣ Get hotel IDs for the city
        hotel_list = amadeus.reference_data.locations.hotels.by_city.get(
            cityCode=city_code
        )
        hotel_ids = [h["hotelId"] for h in hotel_list.data[:1]]  # take first 1 hotel for testing

        if not hotel_ids:
            print("No hotels found for this city.")
            return []

        # 2️⃣ Get offers for those hotels
        response = amadeus.shopping.hotel_offers_search.get(
            hotelIds=",".join(hotel_ids),
            checkInDate=check_in,
            checkOutDate=check_out,
            adults=2,
            roomQuantity=1,
            currency="USD",
        )

        results = []
        for offer in response.data:
            hotel = offer.get("hotel", {})
            price = offer.get("offers", [{}])[0].get("price", {})
            results.append(
                {
                    "name": hotel.get("name"),
                    "address": hotel.get("address", {}).get("lines", ["N/A"])[0],
                    "price": price.get("total"),
                    "currency": price.get("currency"),
                    "rating": hotel.get("rating"),
                }
            )

        return results

    except ResponseError as error:
        print("❌ Amadeus API error:", error)
        if hasattr(error, "response") and error.response:
            print("Details:", error.response.body)
        return []
