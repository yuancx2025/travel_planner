# test_flight.py
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.flight import search_flights


def main():
    origin = "JFK"  # New York
    destination = "LON"  # London
    departure = "2025-10-30"
    return_date = "2025-11-01"
    adults = 1

    print(
        f"✈️ Searching flights from {origin} to {destination} ({departure} → {return_date})...\n"
    )
    results = search_flights(origin, destination, departure, return_date, adults)

    if not results:
        print("No flights found.")
        return

    for i, f in enumerate(results, start=1):
        print(f"{i}. {f['carrier']} — {f['price']} {f['currency']} — {f['duration']}")


if __name__ == "__main__":
    main()
