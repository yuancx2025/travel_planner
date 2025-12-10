#!/usr/bin/env python3
"""
workflows/batch_run.py

Run a batch of queries from data/sample_queries.json against the TravelPlannerWorkflow.
Automatically handles interrupts (selecting top options) and saves the resulting
user profile and itinerary to files for evaluation.

Usage:
    python workflows/batch_run.py --indices 2 3 4
    python workflows/batch_run.py --all
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.workflow import TravelPlannerWorkflow
from workflows.state import TravelPlannerState


def load_queries(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_results(thread_id: str, state: TravelPlannerState):
    """Save profile, itinerary, and budget (if present) to disk."""

    # 1. Save User Profile
    profile_data = state.preferences.fields.copy()
    # Add thread_id to profile for tracking
    profile_data["thread_id"] = thread_id

    profile_path = os.path.join(ROOT, "user_profiles", f"user_profile_{thread_id}.json")
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)

    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False)
    print(f"      💾 Saved profile to {profile_path}")

    # 2. Save Itinerary
    if state.itinerary:
        itinerary_path = os.path.join(
            ROOT, "generated_plans", f"itinerary_{thread_id}.json"
        )
        os.makedirs(os.path.dirname(itinerary_path), exist_ok=True)

        with open(itinerary_path, "w", encoding="utf-8") as f:
            json.dump(state.itinerary, f, indent=2, ensure_ascii=False)
        print(f"      💾 Saved itinerary to {itinerary_path}")
    else:
        print("      ⚠️  No itinerary generated to save.")

    # 3. Save Budget (if available)
    if state.budget:
        budget_path = os.path.join(ROOT, "generated_plans", f"budget_{thread_id}.json")
        os.makedirs(os.path.dirname(budget_path), exist_ok=True)

        with open(budget_path, "w", encoding="utf-8") as f:
            json.dump(state.budget, f, indent=2, ensure_ascii=False)
        print(f"      💾 Saved budget to {budget_path}")


def run_single_query(query_obj: Dict[str, Any]):
    """Run a single query through the workflow."""
    idx = query_obj.get("idx")
    query_text = query_obj.get("query")

    print(f"\n=== Running Query #{idx} ===")
    print(f"Query: {query_text[:100]}...")

    # Generate a unique ID for this run
    thread_id = str(uuid.uuid4())
    print(f"Thread ID: {thread_id}")

    try:
        # Initialize workflow (re-instantiate for each run to ensure clean state)
        # We import here to avoid issues if dependencies are missing during script startup
        from agents.chat_agent import ChatAgent
        from agents.research_agent import ResearchAgent
        from agents.itinerary_agent import ItineraryAgent
        from agents.budget_agent import BudgetAgent

        workflow = TravelPlannerWorkflow(
            chat_agent=ChatAgent(),
            research_agent=ResearchAgent(),
            itinerary_agent=ItineraryAgent(),
            budget_agent=BudgetAgent(),
        )

        state = workflow.initial_state(thread_id)
        state, _ = workflow.start(state)

        # Send the user query
        print("      Sending query...")
        state, interrupts = workflow.handle_user_message(state, query_text)

        # Loop to handle interrupts until complete
        max_steps = 10
        step = 0

        while step < max_steps:
            step += 1

            if state.phase == "complete":
                print("      ✅ Workflow completed successfully.")
                break

            if interrupts:
                # Auto-select the first few options
                if state.phase == "selecting_attractions":
                    print("      📍 Selecting top 3 attractions...")
                    num = min(
                        3, len(state.research.attractions) if state.research else 0
                    )
                    indices = list(range(num))
                    state, interrupts = workflow.handle_interrupt(
                        state, {"selected_indices": indices}
                    )

                elif state.phase == "selecting_restaurants":
                    print("      🍽️  Selecting top 2 restaurants...")
                    num = min(2, len(state.research.dining) if state.research else 0)
                    indices = list(range(num))
                    state, interrupts = workflow.handle_interrupt(
                        state, {"selected_indices": indices}
                    )
                else:
                    print(
                        f"      ❓ Unknown interrupt in phase {state.phase}. Stopping."
                    )
                    break
            elif state.phase == "collecting":
                # If we are still collecting after the initial query, it means the agent needs more info.
                # For this batch script, we assume the query is complete enough.
                # If not, we might need to provide a generic "proceed" or fail.
                print(
                    "      ⚠️  Agent is still collecting info. The query might be incomplete."
                )
                print(f"      Missing fields: {state.preferences.missing_fields}")
                # Try to force proceed if possible, or just stop
                break
            else:
                # Processing... (shouldn't happen with synchronous workflow calls unless streaming)
                pass

        save_results(thread_id, state)

    except Exception as e:
        print(f"      ❌ Error running query #{idx}: {e}")
        import traceback

        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Batch run travel queries.")
    parser.add_argument(
        "--indices",
        type=int,
        nargs="+",
        help="Specific query indices to run (e.g. 2 3 4)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Run all queries in sample_queries.json"
    )

    args = parser.parse_args()

    queries_path = os.path.join(ROOT, "data", "sample_queries.json")
    all_queries = load_queries(queries_path)

    queries_to_run = []
    if args.all:
        queries_to_run = all_queries
    elif args.indices:
        queries_to_run = [q for q in all_queries if q.get("idx") in args.indices]
    else:
        print("Please specify --indices or --all")
        return

    print(f"Found {len(queries_to_run)} queries to run.")

    for q in queries_to_run:
        run_single_query(q)


if __name__ == "__main__":
    main()
