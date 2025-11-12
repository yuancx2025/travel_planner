# evaluation/test_single_query.py
"""Test a single query with mock hotels."""

import json
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.benchmark_adapter import TravelPlannerBenchmarkAdapter


def main():
    print("=" * 70)
    print("SINGLE QUERY TEST (with mock hotels)")
    print("=" * 70)

    # Simple test query
    query = {
        "idx": 0,
        "org": "Charlotte",
        "dest": "Miami",
        "days": 3,
        "date": ["2025-12-01", "2025-12-03"],
        "people_number": 2,
        "budget": 1400,
        "local_constraint": {
            "cuisine": ["Italian"],
            "room type": "shared room",
            "transportation": "no self-driving",
        },
    }

    print(f"\nTest query:")
    print(f"  Destination: {query['dest']}")
    print(f"  Days: {query['days']}")
    print(f"  Budget: ${query['budget']}")
    print(f"  People: {query['people_number']}")
    print()

    # Create adapter with mock hotels
    adapter = TravelPlannerBenchmarkAdapter(use_mock_hotels=True)

    # Run query
    print("Running query (this will take 10-20 seconds)...\n")
    result = adapter.run_query(query, verbose=True)

    # Print result
    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)

    if result["success"]:
        print("✅ SUCCESS!\n")

        # Budget
        if result["budget"]:
            budget = result["budget"]
            print(f"Budget:")
            print(f"  Expected: ${budget['expected']}")
            print(f"  Range: ${budget['low']} - ${budget['high']}")
            print(
                f"  Within limit: {'✅ Yes' if budget['expected'] <= query['budget'] else '❌ No'}"
            )

        # Itinerary
        if result["itinerary"]:
            itinerary = result["itinerary"]
            days = itinerary.get("days", [])
            print(f"\nItinerary:")
            print(f"  Days planned: {len(days)}")
            print(
                f"  Correct count: {'✅ Yes' if len(days) == query['days'] else '❌ No'}"
            )

            # Show first day details
            if days:
                first_day = days[0]
                print(f"\n  Day 1 sample:")
                stops = first_day.get("stops", [])
                for i, stop in enumerate(stops[:3], 1):
                    print(f"    {i}. {stop.get('name', 'Unknown')}")
                if len(stops) > 3:
                    print(f"    ... and {len(stops) - 3} more stops")

        # Save result
        Path("results").mkdir(exist_ok=True)
        with open("results/single_query_test.json", "w") as f:
            json.dump(result, f, indent=2, default=str)

        print(f"\n✅ Full result saved to: results/single_query_test.json")

    else:
        print("❌ FAILED\n")
        print(f"Error: {result.get('error', 'Unknown error')}")

        if result.get("traceback"):
            print("\nTraceback:")
            print(result["traceback"])

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
