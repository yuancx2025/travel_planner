#!/usr/bin/env python3
"""Quick test script for the benchmark adapter."""

import json
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.benchmark_adapter import TravelPlannerBenchmarkAdapter


def main():
    # Load test queries
    data_path = ROOT / "data" / "sample_queries.json"

    if not data_path.exists():
        print(f"❌ Sample queries not found at {data_path}")
        print("Please create data/sample_queries.json first")
        return

    with open(data_path) as f:
        queries = json.load(f)

    print(f"Loaded {len(queries)} test queries\n")

    # Initialize adapter
    adapter = TravelPlannerBenchmarkAdapter()

    # Test 1: Format conversion only
    print("=" * 60)
    print("TEST 1: Format Conversion")
    print("=" * 60)

    first_query = queries[0]
    preferences = adapter.benchmark_to_preferences(first_query)

    print(f"\nInput (TravelPlanner format):")
    print(json.dumps(first_query, indent=2))

    print(f"\nOutput (Our format):")
    print(json.dumps(preferences, indent=2))

    # Test 2: Run single query
    print("\n\n" + "=" * 60)
    print("TEST 2: Run Single Query")
    print("=" * 60)

    result = adapter.run_query(first_query, verbose=True)

    if result["success"]:
        print("\n✅ Query executed successfully!")
        print(f"\nGenerated {len(result['itinerary']['days'])} days of itinerary")
        print(f"Budget estimate: ${result['budget']['expected']}")
    else:
        print(f"\n❌ Query failed: {result['error']}")

    # Test 3: Run multiple queries (optional - comment out if too slow)
    print("\n\n" + "=" * 60)
    print("TEST 3: Run Multiple Queries (OPTIONAL - may be slow)")
    print("=" * 60)

    user_input = input("\nRun all queries? This will make real API calls. (y/N): ")

    if user_input.lower() == "y":
        results = adapter.run_multiple_queries(
            queries[:2], verbose=True
        )  # Only first 2

        # Save results
        output_path = ROOT / "results" / "test_results.json"
        output_path.parent.mkdir(exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n✅ Results saved to {output_path}")
    else:
        print("Skipped.")


if __name__ == "__main__":
    main()
