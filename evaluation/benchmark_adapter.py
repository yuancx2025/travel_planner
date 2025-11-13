# evaluation/benchmark_adapter.py
"""Adapter to run TravelPlanner benchmark queries through our workflow."""

from typing import Dict, Any, List
import sys
from pathlib import Path

# Add project root to Python path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.workflow import TravelPlannerWorkflow
from workflows.state import TravelPlannerState, PreferencesState


class TravelPlannerBenchmarkAdapter:
    """Convert TravelPlanner benchmark format to our workflow format."""

    def __init__(self):
        self.workflow = TravelPlannerWorkflow()

    def benchmark_to_preferences(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert format: TravelPlanner → our preferences

        Input example (TravelPlanner format):
        {
            "org": "Charlotte",          # origin city
            "dest": "Miami",              # destination
            "days": 3,                    # number of days
            "date": ["2022-03-01", "2022-03-03"],  # date range
            "people_number": 2,           # number of people
            "budget": 1400,               # budget
            "local_constraint": {         # local constraints
                "cuisine": ["Italian", "Chinese"],
                "room type": "shared room",
                "transportation": "no self-driving"
            }
        }

        Output (our format):
        {
            "destination_city": "Miami",
            "travel_days": 3,
            "budget_usd": 1400,
            ...
        }
        """
        # Basic fields
        start_date = query["date"][0] if query.get("date") else "2025-12-01"

        preferences = {
            "name": "Benchmark User",
            "origin_city": query.get("org", ""),
            "destination_city": query["dest"],
            "travel_days": query["days"],
            "start_date": start_date,
            "num_people": query.get("people_number", 1),
            "budget_usd": query.get("budget"),
        }

        # Handle constraints
        constraints = query.get("local_constraint", {})

        # Cuisine preference
        if "cuisine" in constraints:
            cuisines = constraints["cuisine"]
            if cuisines and len(cuisines) > 0:
                preferences["cuisine_pref"] = cuisines[0]  # Take first one

        # Room type
        if "room type" in constraints:
            preferences["hotel_room_pref"] = constraints["room type"]

        # Transportation
        if "transportation" in constraints:
            transport = constraints["transportation"]
            # "no self-driving" → need_car_rental = "no"
            # "self-driving" → need_car_rental = "yes"
            preferences["need_car_rental"] = (
                "yes" if "self-driving" in transport.lower() else "no"
            )

        # Fill default values (required fields for your system)
        preferences.setdefault("kids", "no")
        preferences.setdefault("activity_pref", "cultural")
        preferences.setdefault("cuisine_pref", "any")
        preferences.setdefault("need_car_rental", "no")
        preferences.setdefault("hotel_room_pref", "standard")

        return preferences

    def run_query(self, query: Dict[str, Any], verbose: bool = True) -> Dict[str, Any]:
        """
        Execute a single benchmark query.

        Args:
            query: TravelPlanner format query
            verbose: Whether to print detailed info

        Returns:
            {
                "success": bool,           # Whether successful
                "state": TravelPlannerState,  # Final state
                "preferences": dict,       # Extracted preferences
                "itinerary": dict,         # Generated itinerary
                "budget": dict,            # Budget estimate
                "error": str               # Error message (if failed)
            }
        """
        try:
            if verbose:
                print(f"\n{'='*60}")
                print(
                    f"Processing: {query['dest']} ({query['days']} days, ${query.get('budget')} budget)"
                )
                print(f"{'='*60}")

            # Step 1: Convert format
            preferences = self.benchmark_to_preferences(query)
            if verbose:
                print(f"✓ Converted preferences: {list(preferences.keys())}")

            # Step 2: Initialize workflow
            thread_id = f"benchmark-{query.get('idx', 0)}"
            state = self.workflow.initial_state(thread_id)

            # Step 3: Directly populate preferences (skip chat phase)
            state.preferences = PreferencesState(
                fields=preferences, missing_fields=[], complete=True
            )
            if verbose:
                print(f"✓ Initialized workflow with preferences")

            # Step 4: Trigger research phase
            if verbose:
                print(
                    f"⏳ Running research (fetching attractions, restaurants, hotels)..."
                )

            state, interrupts = self.workflow._run_research(state)

            if not interrupts:
                return {
                    "success": False,
                    "error": "Research phase failed to produce interrupts",
                    "state": state,
                }

            if verbose:
                attractions_count = (
                    len(state.research.attractions) if state.research else 0
                )
                dining_count = len(state.research.dining) if state.research else 0
                print(
                    f"✓ Research complete: {attractions_count} attractions, {dining_count} restaurants"
                )

            # Step 5: Auto-select attractions
            if state.phase == "selecting_attractions" and state.research:
                num_to_select = min(
                    preferences["travel_days"] * 2,  # 2 per day
                    len(state.research.attractions),
                )
                indices = list(range(num_to_select))

                if verbose:
                    print(f"⏳ Auto-selecting {num_to_select} attractions...")

                state, interrupts = self.workflow.handle_interrupt(
                    state, {"selected_indices": indices}
                )

                if verbose:
                    print(f"✓ Selected {len(state.selected_attractions)} attractions")

            # Step 6: Auto-select restaurants
            if state.phase == "selecting_restaurants" and state.research:
                num_to_select = min(3, len(state.research.dining))
                indices = list(range(num_to_select))

                if verbose:
                    print(f"⏳ Auto-selecting {num_to_select} restaurants...")

                state, interrupts = self.workflow.handle_interrupt(
                    state, {"selected_indices": indices}
                )

                if verbose:
                    print(f"✓ Selected {len(state.selected_restaurants)} restaurants")

            # Step 7: Check completion
            if state.phase != "complete":
                return {
                    "success": False,
                    "error": f"Workflow stopped at phase: {state.phase}",
                    "state": state,
                }

            if verbose:
                print(f"✓ Workflow complete!")
                if state.budget:
                    print(f"  Budget: ${state.budget.get('expected', 0)}")
                if state.itinerary:
                    num_days = len(state.itinerary.get("days", []))
                    print(f"  Itinerary: {num_days} days planned")

            return {
                "success": True,
                "state": state,
                "preferences": state.preferences.fields,
                "itinerary": state.itinerary,
                "budget": state.budget,
            }

        except Exception as e:
            import traceback

            if verbose:
                print(f"\n❌ Error: {e}")
                traceback.print_exc()

            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }

    def run_multiple_queries(
        self, queries: List[Dict[str, Any]], verbose: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Run multiple benchmark queries in sequence.

        Args:
            queries: List of TravelPlanner queries
            verbose: Whether to print progress

        Returns:
            List of results (one per query)
        """
        results = []

        for i, query in enumerate(queries):
            if verbose:
                print(f"\n\n{'#'*60}")
                print(f"QUERY {i+1}/{len(queries)}")
                print(f"{'#'*60}")

            result = self.run_query(query, verbose=verbose)
            results.append({"query_idx": i, "query": query, "result": result})

            # Print success/failure
            status = "✅ SUCCESS" if result["success"] else "❌ FAILED"
            print(f"\n{status}")

            if not result["success"]:
                print(f"Error: {result.get('error', 'Unknown error')}")

        # Summary
        if verbose:
            print(f"\n\n{'='*60}")
            print(f"SUMMARY")
            print(f"{'='*60}")
            successful = sum(1 for r in results if r["result"]["success"])
            print(
                f"Success rate: {successful}/{len(queries)} ({successful/len(queries)*100:.1f}%)"
            )

        return results
