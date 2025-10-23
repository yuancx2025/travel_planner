# test/test_dining.py
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.dining import search_restaurants

def main():
    latitude = 36.0014  # Example: Durham, NC
    longitude = -78.9382
    keyword = "sushi"

    results = search_restaurants(
        latitude, longitude, radius=2000, keyword=keyword
    )

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, start=1):
        print(f"{i}. {r['name']} ({r.get('rating', 'N/A')}★) - {r['address']} - Price Level: {r.get('price_level', 'N/A')}")


if __name__ == "__main__":
    main()
