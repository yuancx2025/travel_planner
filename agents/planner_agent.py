# agents/planner_agent.py
"""
PlannerAgent: Orchestrates ChatAgent → ResearchAgent → Travel Plan.
High-level coordinator that manages the conversation → research → planning workflow.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional, Generator
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agents.chat_agent import ChatAgent
from agents.research_agent import ResearchAgent


class PlannerAgent:
    """
    High-level orchestrator:
    1. Uses ChatAgent to gather user preferences
    2. Triggers ResearchAgent to fetch travel data
    3. Synthesizes results into a cohesive travel plan using LLM
    """

    def __init__(self, model_name: str = "gemini-2.0-flash", temperature: float = 0.3):
        self.chat_agent = ChatAgent(model_name=model_name, temperature=0.2)
        self.research_agent = ResearchAgent()
        self.planner_model = ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
        self.user_state: Dict[str, Any] = {}
        self.research_results: Optional[Dict[str, Any]] = None

    # ==================== PUBLIC API ====================

    def interact(self, user_message: str) -> Dict[str, Any]:
        """
        Main interaction loop:
        - If collecting info: delegate to ChatAgent
        - If info complete: trigger research and generate plan
        
        Returns:
            {
                "phase": "collecting" | "researching" | "planning" | "complete",
                "message": str,  # response to user
                "state": {...},  # current user preferences
                "plan": {...} | None,  # final travel plan (if phase == "complete")
            }
        """
        # 1. Collect user info via ChatAgent
        result = self.chat_agent.collect_info(user_message, state=self.user_state)
        self.user_state = result["state"]
        
        # 2. Check if collection is complete
        if not result["complete"]:
            # Still gathering info
            return {
                "phase": "collecting",
                "message": self._stream_to_text(result["stream"]),
                "state": self.user_state,
                "missing_fields": result["missing_fields"],
                "plan": None,
            }
        
        # 3. Info complete → trigger research
        if self.research_results is None:
            return self._trigger_research()
        
        # 4. Research done → generate final plan
        return self._generate_plan()

    def get_plan(self) -> Optional[Dict[str, Any]]:
        """
        Get the final travel plan (if research is complete).
        """
        if self.research_results is None:
            return None
        return self._generate_plan()

    # ==================== INTERNAL WORKFLOW ====================

    def _trigger_research(self) -> Dict[str, Any]:
        """
        Execute research phase using ResearchAgent.
        """
        print("\n🔍 Triggering research based on your preferences...\n")
        
        try:
            self.research_results = self.research_agent.research(self.user_state)
            
            # Build summary message
            summary_parts = []
            if self.research_results.get("weather"):
                summary_parts.append(f"✓ Weather forecast ({len(self.research_results['weather'])} days)")
            if self.research_results.get("attractions"):
                summary_parts.append(f"✓ Attractions ({len(self.research_results['attractions'])} found)")
            if self.research_results.get("dining"):
                summary_parts.append(f"✓ Restaurants ({len(self.research_results['dining'])} found)")
            if self.research_results.get("hotels"):
                summary_parts.append(f"✓ Hotels ({len(self.research_results['hotels'])} options)")
            if self.research_results.get("car_rentals"):
                summary_parts.append(f"✓ Car rentals ({len(self.research_results['car_rentals'])} options)")
            
            message = (
                "Great! I've gathered all the information for your trip. Here's what I found:\n\n"
                + "\n".join(summary_parts)
                + "\n\nGenerating your personalized travel plan..."
            )
            
            return {
                "phase": "researching",
                "message": message,
                "state": self.user_state,
                "plan": None,
            }
        except Exception as e:
            return {
                "phase": "error",
                "message": f"Sorry, I encountered an error during research: {str(e)}",
                "state": self.user_state,
                "plan": None,
            }

    def _generate_plan(self) -> Dict[str, Any]:
        """
        Synthesize research results into a cohesive travel plan using LLM.
        """
        if not self.research_results:
            return {
                "phase": "error",
                "message": "No research results available.",
                "state": self.user_state,
                "plan": None,
            }
        
        # Build context for LLM
        context = self._build_planning_context()
        
        # Generate plan
        system_msg = SystemMessage(content=(
            "You are a professional travel planner. Based on the user's preferences and research results, "
            "create a detailed, day-by-day travel itinerary. Be specific, mention actual places, "
            "and provide practical tips. Format your response in clear sections:\n"
            "1. Trip Overview\n"
            "2. Weather & Packing Suggestions\n"
            "3. Day-by-Day Itinerary\n"
            "4. Dining Recommendations\n"
            "5. Accommodation Options\n"
            "6. Transportation\n"
            "7. Budget Summary\n"
            "Keep it concise but informative."
        ))
        
        user_msg = HumanMessage(content=context)
        
        try:
            response = self.planner_model.invoke([system_msg, user_msg])
            plan_text = response.content
            
            return {
                "phase": "complete",
                "message": plan_text,
                "state": self.user_state,
                "plan": {
                    "text": plan_text,
                    "research_data": self.research_results,
                    "preferences": self.user_state,
                    "generated_at": datetime.now().isoformat(),
                },
            }
        except Exception as e:
            return {
                "phase": "error",
                "message": f"Error generating plan: {str(e)}",
                "state": self.user_state,
                "plan": None,
            }

    def _build_planning_context(self) -> str:
        """
        Build a comprehensive context string for the planning LLM.
        """
        lines = ["=== USER PREFERENCES ==="]
        lines.append(f"Name: {self.user_state.get('name', 'N/A')}")
        lines.append(f"Destination: {self.user_state.get('destination_city', 'N/A')}")
        lines.append(f"Duration: {self.user_state.get('travel_days', 'N/A')} days")
        lines.append(f"Start Date: {self.user_state.get('start_date', 'N/A')}")
        lines.append(f"Budget: ${self.user_state.get('budget_usd', 'N/A')} USD")
        lines.append(f"Travelers: {self.user_state.get('num_people', 'N/A')} people")
        lines.append(f"Kids: {self.user_state.get('kids', 'N/A')}")
        lines.append(f"Activity Preference: {self.user_state.get('activity_pref', 'N/A')}")
        lines.append(f"Cuisine Preference: {self.user_state.get('cuisine_pref', 'N/A')}")
        lines.append(f"Car Rental: {self.user_state.get('need_car_rental', 'N/A')}")
        lines.append("")
        
        # Weather
        if self.research_results.get("weather"):
            lines.append("=== WEATHER FORECAST ===")
            for day in self.research_results["weather"][:5]:  # first 5 days
                lines.append(
                    f"{day['date']}: {day['temp_low']} to {day['temp_high']}, "
                    f"{day['summary']}, Precipitation: {day['precipitation']}"
                )
            lines.append("")
        
        # Attractions
        if self.research_results.get("attractions"):
            lines.append("=== TOP ATTRACTIONS ===")
            for i, attr in enumerate(self.research_results["attractions"][:8], 1):
                rating = f"{attr.get('rating', 'N/A')}⭐" if attr.get("rating") else "No rating"
                lines.append(
                    f"{i}. {attr['name']} ({rating}, {attr.get('review_count', 0)} reviews) - "
                    f"{attr.get('address', 'N/A')}"
                )
            lines.append("")
        
        # Dining
        if self.research_results.get("dining"):
            lines.append("=== RESTAURANT RECOMMENDATIONS ===")
            for i, rest in enumerate(self.research_results["dining"][:6], 1):
                rating = f"{rest.get('rating', 'N/A')}⭐" if rest.get("rating") else "No rating"
                price = "$" * rest.get("price_level", 2)
                lines.append(
                    f"{i}. {rest['name']} ({rating}, {price}) - {rest.get('address', 'N/A')}"
                )
            lines.append("")
        
        # Hotels
        if self.research_results.get("hotels"):
            lines.append("=== HOTEL OPTIONS ===")
            for i, hotel in enumerate(self.research_results["hotels"][:5], 1):
                lines.append(
                    f"{i}. {hotel.get('name', 'N/A')} - ${hotel.get('price', 'N/A')} {hotel.get('currency', 'USD')} - "
                    f"Rating: {hotel.get('rating', 'N/A')}"
                )
            lines.append("")
        
        # Car Rentals
        if self.research_results.get("car_rentals"):
            lines.append("=== CAR RENTAL OPTIONS ===")
            for i, car in enumerate(self.research_results["car_rentals"][:5], 1):
                veh = car.get("vehicle", {})
                price = car.get("price", {})
                lines.append(
                    f"{i}. {car.get('supplier', 'N/A')} - {veh.get('class', 'N/A')} "
                    f"({veh.get('seats', 'N/A')} seats, {veh.get('transmission', 'N/A')}) - "
                    f"${price.get('amount', 'N/A')} {price.get('currency', 'USD')}"
                )
            lines.append("")
        
        # Fuel Prices
        if self.research_results.get("fuel_prices"):
            fp = self.research_results["fuel_prices"]
            lines.append("=== FUEL PRICES ===")
            lines.append(f"Location: {fp.get('location', 'N/A')} ({fp.get('state', 'N/A')})")
            lines.append(f"Regular: ${fp.get('regular', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Midgrade: ${fp.get('midgrade', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Premium: ${fp.get('premium', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Diesel: ${fp.get('diesel', 'N/A')}/{fp.get('unit', 'gallon')}")
            lines.append(f"Source: {fp.get('source', 'N/A')}")
            lines.append("")
        
        # Distances
        if self.research_results.get("distances"):
            lines.append("=== DISTANCES BETWEEN TOP ATTRACTIONS ===")
            for dist in self.research_results["distances"][:5]:
                km = dist.get("distance_m", 0) / 1000
                mins = dist.get("duration_s", 0) / 60
                lines.append(
                    f"{dist.get('origin_name', 'Origin')} → {dist.get('dest_name', 'Dest')}: "
                    f"{km:.1f} km, {mins:.0f} min drive"
                )
            lines.append("")
        
        return "\n".join(lines)

    # ==================== HELPERS ====================

    def _stream_to_text(self, stream: Generator) -> str:
        """Convert streaming response to text."""
        if stream is None:
            return ""
        
        try:
            chunks = []
            for chunk in stream:
                if hasattr(chunk, "content"):
                    chunks.append(chunk.content)
            
            # Save to chat history
            full_text = "".join(chunks)
            self.chat_agent.conversation_history.append(AIMessage(content=full_text))
            return full_text
        except Exception as e:
            print(f"Error streaming: {e}")
            return ""

    def reset(self):
        """Reset the planner to start a new conversation."""
        self.chat_agent = ChatAgent()
        self.user_state = {}
        self.research_results = None


# ==================== EXAMPLE USAGE ====================

if __name__ == "__main__":
    """
    Simple CLI for PlannerAgent.
    Commands:
      /state   -> show current state
      /plan    -> get current plan
      /reset   -> start over
      /quit    -> exit
    """
    if not os.getenv("GOOGLE_API_KEY"):
        print("❌ Missing GOOGLE_API_KEY. Set it first.")
        exit(1)
    
    planner = PlannerAgent()
    print("🗺️  Travel Planner Agent")
    print("=" * 60)
    print("I'll help you plan your trip! Just chat naturally.\n")
    print("Commands: /state, /plan, /reset, /quit\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input == "/quit":
                print("Goodbye! 👋")
                break
            
            if user_input == "/state":
                import json
                print("\nCurrent State:")
                print(json.dumps(planner.user_state, indent=2))
                continue
            
            if user_input == "/plan":
                plan = planner.get_plan()
                if plan:
                    print("\n" + plan["text"])
                else:
                    print("No plan generated yet. Complete the conversation first.")
                continue
            
            if user_input == "/reset":
                planner.reset()
                print("✓ Reset. Let's start fresh!\n")
                continue
            
            # Normal interaction
            response = planner.interact(user_input)
            print(f"\nAgent: {response['message']}\n")
            
            # If planning complete, show plan
            if response["phase"] == "complete":
                print("\n" + "="*60)
                print("🎉 YOUR TRAVEL PLAN IS READY!")
                print("="*60 + "\n")
        
        except KeyboardInterrupt:
            print("\n\nGoodbye! 👋")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}\n")
