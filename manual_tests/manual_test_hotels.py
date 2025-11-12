"""
Manual integration test for tools.hotels — this actually calls Google Places API.
Use it to verify your API key and see live hotel results.
"""

import os, sys, pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]  # travel_planner/
sys.path.insert(0, str(PROJECT_ROOT))

from tools import hotels
from pprint import pprint


def main():
    city = (
        input("Enter a city name (e.g. Durham, Chicago, New York): ").strip()
        or "Durham"
    )
    check_in = "2025-11-20"
    check_out = "2025-11-22"

    print(f"\n🔍 Searching hotels in {city} ({check_in} → {check_out}) ...\n")

    results = hotels.search_hotels_by_city(city, check_in, check_out, adults=2, limit=5)

    if not results:
        print("⚠️  No hotels found or API returned nothing.")
        return

    print(f"✅ Found {len(results)} hotels:\n")

    for idx, h in enumerate(results, start=1):
        print(f"{idx}. {h['name']} — {h['address']}")
        print(f"   ⭐ Rating: {h.get('rating')}, Price level: {h.get('price_level')}")
        print(f"   🔗 Source: {h['source']}")
        print()


if __name__ == "__main__":
    main()
