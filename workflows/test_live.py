#!/usr/bin/env python3
"""Live integration test with real API calls.

This script tests the complete workflow using actual agents:
- Real ChatAgent with Google Gemini LLM
- Real ResearchAgent with Google Places, Amadeus, etc.
- Real ItineraryAgent with LLM-based planning
- Real BudgetAgent with actual cost calculations

WARNING: This will consume API credits and take several minutes to run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.workflow import TravelPlannerWorkflow
from workflows.state import TravelPlannerState


def check_environment() -> Dict[str, bool]:
    """Check which API credentials are available."""
    import config
    
    status = {
        "GOOGLE_API_KEY": bool(config.get_google_api_key()),
        "GOOGLE_MAPS_API_KEY": bool(config.get_google_maps_api_key()),
        "AMADEUS_API_KEY": bool(config.get_amadeus_api_key()),
        "AMADEUS_API_SECRET": bool(config.get_amadeus_api_secret()),
    }
    return status


def print_environment_status() -> bool:
    """Print API credential status and return True if all required are present."""
    print("\n" + "=" * 70)
    print("🔑 API CREDENTIALS CHECK")
    print("=" * 70)
    
    status = check_environment()
    all_present = True
    
    for key, present in status.items():
        icon = "✅" if present else "❌"
        status_text = "Present" if present else "Missing"
        print(f"{icon} {key}: {status_text}")
        if not present:
            all_present = False
    
    print()
    
    if not all_present:
        print("⚠️  WARNING: Some API credentials are missing.")
        print("   The test may fail or use fallback/stub data.\n")
        print("   To set credentials:")
        print("   export GOOGLE_API_KEY='your-key'")
        print("   export GOOGLE_PLACES_API_KEY='your-key'")
        print("   export AMADEUS_API_KEY='your-key'")
        print("   export AMADEUS_API_SECRET='your-secret'\n")
    else:
        print("✅ All required credentials are present.\n")
    
    return all_present


def run_automated_live_test() -> None:
    """Run an automated test with real APIs (non-interactive)."""
    print("=" * 70)
    print("🌍 LIVE WORKFLOW TEST (Automated)")
    print("=" * 70)
    print("\nUsing REAL agents with live API calls.")
    print("This will take 30-60 seconds and consume API credits.\n")
    
    if not print_environment_status():
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            print("Exiting.")
            return
    
    try:
        # Import real agents (may fail if dependencies missing)
        from agents.chat_agent import ChatAgent
        from agents.research_agent import ResearchAgent
        from agents.itinerary_agent import ItineraryAgent
        from agents.budget_agent import BudgetAgent
        
        print("✅ Successfully imported all agent modules\n")
        
        # Create workflow with real agents
        workflow = TravelPlannerWorkflow(
            chat_agent=ChatAgent(),
            research_agent=ResearchAgent(),
            itinerary_agent=ItineraryAgent(),
            budget_agent=BudgetAgent(),
        )
        
        print("[1/6] Initializing workflow...")
        state = workflow.initial_state("live-test-thread")
        state, _ = workflow.start(state)
        
        # Show initial greeting
        print(f"      🤖 {state.conversation_turns[-1].content[:60]}...\n")
        
        print("[2/6] Sending user message with travel preferences...")
        user_message = "I want a 2-day trip to San Francisco for 2 people, budget $1500, love outdoor activities and good food"
        state, interrupts = workflow.handle_user_message(state, user_message)
        
        # Show response
        if state.conversation_turns:
            last_msg = state.conversation_turns[-1].content
            print(f"      🤖 {last_msg[:80]}...")
        
        print(f"      Preferences complete: {state.preferences.complete}")
        print(f"      Collected fields: {list(state.preferences.fields.keys())}\n")
        
        # Check if we need more info or if research started
        if not interrupts and state.phase == "collecting":
            print("      ℹ️  Chat agent needs more information. Sending follow-up...\n")
            
            follow_up = "Starting next week, we like museums and Italian food, no car rental needed"
            state, interrupts = workflow.handle_user_message(state, follow_up)
            
            if state.conversation_turns:
                print(f"      🤖 {state.conversation_turns[-1].content[:80]}...\n")
        
        if not interrupts:
            print("❌ ERROR: Research phase did not trigger after providing preferences.")
            print(f"   Current phase: {state.phase}")
            print(f"   Preferences complete: {state.preferences.complete}")
            print(f"   Missing fields: {state.preferences.missing_fields}")
            return
        
        print("[3/6] Research completed! Analyzing results...")
        if state.research:
            print(f"      📍 Found {len(state.research.attractions)} attractions")
            print(f"      🍽️  Found {len(state.research.dining)} restaurants")
            
            # Show sample results
            if state.research.attractions:
                print(f"      Sample attraction: {state.research.attractions[0].get('name', 'N/A')}")
            if state.research.dining:
                print(f"      Sample restaurant: {state.research.dining[0].get('name', 'N/A')}")
        print()
        
        # Handle attraction selection
        print("[4/6] Selecting attractions...")
        if state.phase == "selecting_attractions" and interrupts:
            # Select first 2-3 attractions
            num_to_select = min(3, len(state.research.attractions) if state.research else 0)
            indices = list(range(num_to_select))
            
            state, interrupts = workflow.handle_interrupt(
                state, {"selected_indices": indices}
            )
            
            print(f"      ✅ Selected {len(state.selected_attractions)} attractions:")
            for attr in state.selected_attractions[:3]:
                print(f"         • {attr.get('name', 'N/A')}")
        print()
        
        # Handle restaurant selection
        print("[5/6] Selecting restaurants...")
        if state.phase == "selecting_restaurants" and interrupts:
            # Select first 1-2 restaurants
            num_to_select = min(2, len(state.research.dining) if state.research else 0)
            indices = list(range(num_to_select))
            
            state, interrupts = workflow.handle_interrupt(
                state, {"selected_indices": indices}
            )
            
            print(f"      ✅ Selected {len(state.selected_restaurants)} restaurants:")
            for rest in state.selected_restaurants[:3]:
                print(f"         • {rest.get('name', 'N/A')}")
        print()
        
        # Show final results
        print("[6/6] Generating final itinerary and budget...")
        if state.phase == "complete":
            print("\n" + "=" * 70)
            print("✨ LIVE TEST RESULTS")
            print("=" * 70)
            
            # Preferences
            print("\n📋 Captured Preferences:")
            for key, value in state.preferences.fields.items():
                print(f"   • {key}: {value}")
            
            # Itinerary
            if state.itinerary:
                print("\n📅 Itinerary:")
                if isinstance(state.itinerary, dict):
                    days = state.itinerary.get("days", [])
                    for day_info in days[:3]:  # Show first 3 days
                        day_num = day_info.get("day", "?")
                        print(f"\n   Day {day_num}:")
                        stops = day_info.get("stops", [])
                        for stop in stops[:5]:  # Show first 5 stops per day
                            print(f"      • {stop.get('name', 'Unknown')}")
                        if len(stops) > 5:
                            print(f"      ... and {len(stops) - 5} more stops")
                    if len(days) > 3:
                        print(f"\n   ... and {len(days) - 3} more days")
                else:
                    print(f"   {state.itinerary}")
            
            # Budget
            if state.budget:
                print("\n💰 Budget Estimate:")
                if isinstance(state.budget, dict):
                    currency = state.budget.get("currency", "USD")
                    expected = state.budget.get("expected", 0)
                    print(f"   Total: {currency} {expected:,.2f}")
                    
                    breakdown = state.budget.get("breakdown", {})
                    if breakdown:
                        print("\n   Breakdown:")
                        for category, amount in breakdown.items():
                            print(f"      • {category.replace('_', ' ').title()}: {currency} {amount:,.2f}")
                else:
                    print(f"   {state.budget}")
            
            # Planning context
            if state.planning_context:
                print("\n💬 Planning Summary:")
                # Print first 300 chars
                context = str(state.planning_context)[:300]
                print(f"   {context}...")
            
            print("\n" + "=" * 70)
            print("✅ LIVE TEST COMPLETED SUCCESSFULLY!")
            print("=" * 70)
            print(f"\nTotal conversation turns: {len(state.conversation_turns)}")
            print(f"Final state phase: {state.phase}")
            print()
            
        else:
            print(f"\n❌ ERROR: Workflow did not complete. Final phase: {state.phase}")
    
    except ImportError as e:
        print(f"\n❌ ERROR: Failed to import agent modules: {e}")
        print("   Make sure all dependencies are installed:")
        print("   pip install -r requirements.txt\n")
    except Exception as e:
        print(f"\n❌ ERROR during live test: {e}")
        import traceback
        traceback.print_exc()


def run_interactive_live_test() -> None:
    """Run an interactive test with real APIs (you type messages)."""
    print("=" * 70)
    print("🌍 LIVE WORKFLOW TEST (Interactive)")
    print("=" * 70)
    print("\nUsing REAL agents with live API calls.")
    print("You'll chat naturally and the system will use actual LLMs and APIs.\n")
    
    if not print_environment_status():
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            print("Exiting.")
            return
    
    try:
        from agents.chat_agent import ChatAgent
        from agents.research_agent import ResearchAgent
        from agents.itinerary_agent import ItineraryAgent
        from agents.budget_agent import BudgetAgent
        
        print("✅ Successfully imported all agent modules\n")
        
        workflow = TravelPlannerWorkflow(
            chat_agent=ChatAgent(),
            research_agent=ResearchAgent(),
            itinerary_agent=ItineraryAgent(),
            budget_agent=BudgetAgent(),
        )
        
        state = workflow.initial_state("live-interactive-thread")
        state, _ = workflow.start(state)
        
        # Show initial greeting
        print(f"\n🤖 Assistant: {state.conversation_turns[-1].content}\n")
        
        # Phase 1: Conversation loop
        print("💡 Tip: Type your travel plans naturally. Type 'quit' to exit.\n")
        
        turn_count = 0
        max_turns = 10  # Prevent infinite loops
        
        while state.phase == "collecting" and turn_count < max_turns:
            print("👤 You: ", end="", flush=True)
            user_input = input().strip()
            if not user_input:
                continue
            if user_input.lower() in ["quit", "exit", "q"]:
                print("\nExiting live test.")
                return
            
            turn_count += 1
            print("   ⏳ Processing (calling real LLM)...")
            
            state, interrupts = workflow.handle_user_message(state, user_input)
            
            # Show assistant response
            last_turn = state.conversation_turns[-1]
            if last_turn.role == "assistant":
                print(f"\n🤖 Assistant: {last_turn.content}\n")
            
            if interrupts:
                print("   ✅ Research triggered!\n")
                break
        
        if turn_count >= max_turns:
            print(f"\n⚠️  Reached maximum turns ({max_turns}). Ending test.")
            return
        
        # Phase 2: Attraction selection
        if state.phase == "selecting_attractions" and state.research:
            print("=" * 70)
            print("🏛️  ATTRACTION SELECTION (from real API data)")
            print("=" * 70)
            
            attractions = state.research.attractions
            print(f"\nFound {len(attractions)} attractions:\n")
            
            for idx, attr in enumerate(attractions[:10]):  # Show max 10
                print(f"  [{idx}] {attr.get('name', 'N/A')}")
                if attr.get('address'):
                    print(f"      📍 {attr['address']}")
                if attr.get('rating'):
                    print(f"      ⭐ {attr['rating']} ({attr.get('review_count', 0)} reviews)")
                print()
            
            if len(attractions) > 10:
                print(f"   ... and {len(attractions) - 10} more\n")
            
            sys.stdout.flush()

            while True:
                print("👤 Select attractions (e.g., '0,1,2'): ", end="", flush=True)
                selection = input().strip()
                if selection.lower() in ["quit", "exit", "q"]:
                    print("\nExiting live test.")
                    return
                
                try:
                    if "," in selection:
                        indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
                    else:
                        indices = [int(x.strip()) for x in selection.split() if x.strip()]
                    
                    print("   ⏳ Processing selections...")
                    state, interrupts = workflow.handle_interrupt(
                        state, {"selected_indices": indices}
                    )
                    
                    print(f"\n✅ Selected {len(state.selected_attractions)} attractions:")
                    for attr in state.selected_attractions:
                        print(f"   • {attr.get('name', 'N/A')}")
                    print()
                    break
                except (ValueError, IndexError) as e:
                    print(f"❌ Invalid selection. Try again.\n")
        
        # Phase 3: Restaurant selection
        if state.phase == "selecting_restaurants" and state.research:
            print("=" * 70)
            print("🍽️  RESTAURANT SELECTION (from real API data)")
            print("=" * 70)
            
            last_turn = state.conversation_turns[-1]
            if last_turn.role == "assistant":
                print(f"\n🤖 Assistant: {last_turn.content}\n")
            
            restaurants = state.research.dining
            print(f"Found {len(restaurants)} restaurants:\n")
            
            for idx, rest in enumerate(restaurants[:10]):
                print(f"  [{idx}] {rest.get('name', 'N/A')}")
                if rest.get('address'):
                    print(f"      📍 {rest['address']}")
                if rest.get('rating'):
                    print(f"      ⭐ {rest['rating']} ({rest.get('review_count', 0)} reviews)")
                price = rest.get('price_level')
                if price and isinstance(price, int):
                    print(f"      💰 {'$' * price}")
                print()
            
            if len(restaurants) > 10:
                print(f"   ... and {len(restaurants) - 10} more\n")
            
            sys.stdout.flush()

            while True:
                print("👤 Select restaurants (e.g., '0,1'): ", end="", flush=True)
                selection = input().strip()
                if selection.lower() in ["quit", "exit", "q"]:
                    print("\nExiting live test.")
                    return
                
                try:
                    if "," in selection:
                        indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
                    else:
                        indices = [int(x.strip()) for x in selection.split() if x.strip()]
                    
                    print("   ⏳ Generating itinerary and budget (this may take 30+ seconds)...")
                    state, interrupts = workflow.handle_interrupt(
                        state, {"selected_indices": indices}
                    )
                    
                    print(f"\n✅ Selected {len(state.selected_restaurants)} restaurants:")
                    for rest in state.selected_restaurants:
                        print(f"   • {rest.get('name', 'N/A')}")
                    print()
                    break
                except (ValueError, IndexError) as e:
                    print(f"❌ Invalid selection. Try again.\n")
        
        # Phase 4: Final results
        if state.phase == "complete":
            print("=" * 70)
            print("✨ YOUR PERSONALIZED TRAVEL PLAN")
            print("=" * 70)
            
            last_turn = state.conversation_turns[-1]
            if last_turn.role == "assistant":
                print(f"\n🤖 Assistant: {last_turn.content}\n")
            
            # Show full results
            print("📋 Your Preferences:")
            for key, value in state.preferences.fields.items():
                formatted_key = key.replace("_", " ").title()
                print(f"   • {formatted_key}: {value}")
            
            if state.itinerary:
                print("\n📅 Day-by-Day Itinerary:")
                if isinstance(state.itinerary, dict):
                    days = state.itinerary.get("days", [])
                    for day_info in days:
                        day_num = day_info.get("day", "?")
                        print(f"\n   🗓️  Day {day_num}:")
                        for stop in day_info.get("stops", []):
                            print(f"      • {stop.get('name', 'Unknown')}")
                else:
                    print(f"   {state.itinerary}")
            
            if state.budget:
                print("\n💰 Budget Breakdown:")
                if isinstance(state.budget, dict):
                    total = state.budget.get("expected", 0)
                    currency = state.budget.get("currency", "USD")
                    print(f"   Total Estimated Cost: {currency} {total:,.2f}\n")
                    
                    breakdown = state.budget.get("breakdown", {})
                    for category, amount in breakdown.items():
                        pct = (amount / total * 100) if total > 0 else 0
                        print(f"      • {category.replace('_', ' ').title()}: {currency} {amount:,.2f} ({pct:.0f}%)")
                else:
                    print(f"   {state.budget}")
            
            if state.planning_context:
                print("\n📝 Planning Notes:")
                print(f"   {state.planning_context}\n")
            
            print("=" * 70)
            print("✅ LIVE TEST COMPLETE!")
            print("=" * 70)
            
    except ImportError as e:
        print(f"\n❌ ERROR: Failed to import agent modules: {e}")
        print("   Make sure all dependencies are installed.\n")
    except Exception as e:
        print(f"\n❌ ERROR during live test: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Live workflow integration test with real API calls"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive mode (you type messages)"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check API credentials, don't run test"
    )
    
    args = parser.parse_args()
    
    if args.check_only:
        print_environment_status()
    elif args.interactive:
        run_interactive_live_test()
    else:
        run_automated_live_test()
