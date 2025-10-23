# test_hotels.py

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.hotels import search_hotels_by_city

def main():
    city_code = "MAD"  # Madrid
    check_in = "2025-10-25"
    check_out = "2025-10-27"

    print(f"🏨 Searching hotels in {city_code} from {check_in} to {check_out}…\n")

    results = search_hotels_by_city(
        city_code, check_in, check_out)

    if not results:
        print("No results found.")
        return

    for i, h in enumerate(results[:10], start=1):
        print(
            f"{i}. {h['name']} — {h['price']} {h['currency']} — {h['address']} (⭐{h.get('rating', 'N/A')})"
        )


if __name__ == "__main__":
    main()
