# agents/planner_agent.py
"""
PlannerAgent: Orchestrates ChatAgent → ResearchAgent → Travel Plan.
High-level coordinator that manages the conversation → research → planning workflow.
"""
from __future__ import annotations
import math
import os
from typing import Any, Dict, List, Optional, Generator
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agents.chat_agent import ChatAgent
from agents.research_agent import ResearchAgent
from agents.itinerary_agent import ItineraryAgent
from agents.budget_agent import BudgetAgent


class AttractionSelectionAgent:
    """Curate attractions and help interpret the user's choices."""

    def __init__(self, max_options: int = 5) -> None:
        self.max_options = max_options

    def present_options(self, attractions: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
        shortlist = (attractions or [])[: self.max_options]
        if not shortlist:
            return ("I couldn't find standout attractions to shortlist, so feel free to tell me what interests you.", [])

        def _line(idx: int, item: Dict[str, Any]) -> str:
            rating = item.get("rating")
            badge = f" ({rating}★)" if rating else ""
            return f"{idx}. {item.get('name', 'Attraction')}{badge}"

        lines = ["Here are a few attractions that match your trip:"]
        lines.extend(_line(idx, item) for idx, item in enumerate(shortlist, 1))
        lines.append("Reply with the numbers of the spots you like (e.g., '1 3') or mention them by name.")
        return ("\n".join(lines), shortlist)

    def parse_selection(self, user_message: str, shortlist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not user_message or not shortlist:
            return []

        tokens = [token.strip() for token in user_message.replace(",", " ").split() if token.strip()]
        numeric = [shortlist[int(t) - 1] for t in tokens if t.isdigit() and 1 <= int(t) <= len(shortlist)]

        if numeric:
            chosen = numeric
        else:
            lowered = user_message.lower()
            chosen = [item for item in shortlist if (item.get("name") or "").lower() in lowered]

        dedup: List[Dict[str, Any]] = []
        seen = set()
        for item in chosen:
            key = item.get("id") or item.get("name")
            if key and key not in seen:
                dedup.append(item)
                seen.add(key)
        return dedup


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
        self.selection_agent = AttractionSelectionAgent()
        self.itinerary_agent = ItineraryAgent()
        self.budget_agent = BudgetAgent()
        self.user_state: Dict[str, Any] = {}
        self.research_results: Optional[Dict[str, Any]] = None
        self.presented_attractions = []
        self.selected_attractions = []
        self.itinerary_summary = None
        self.phase = "collecting"

    # ==================== PUBLIC API ====================

    def interact(self, user_message: str) -> Dict[str, Any]:
        """Route the conversation through collection → research → selection → plan."""

        if self.phase == "selection":
            return self._handle_selection_message(user_message)

        if self.phase == "complete":
            return self._generate_plan()

        # Default to information gathering until requirements are met.
        result = self.chat_agent.collect_info(user_message, state=self.user_state)
        self.user_state = result["state"]

        if not result["complete"]:
            return {
                "phase": "collecting",
                "message": self._stream_to_text(result["stream"]),
                "state": self.user_state,
                "missing_fields": result["missing_fields"],
                "plan": None,
            }

        if self.research_results is None:
            return self._trigger_research()

        if self.selected_attractions and self.itinerary_summary:
            return self._generate_plan()

        # We have preferences and research but still need selections.
        return self._handle_selection_message(user_message)

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
            self.selected_attractions = []
            self.itinerary_summary = None

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
            if self.research_results.get("fuel_prices"):
                # Check if it contains car rental daily rates
                fp = self.research_results["fuel_prices"]
                has_rental_rates = any(fp.get(k) for k in ["economy_car_daily", "compact_car_daily", "midsize_car_daily", "suv_daily"])
                if has_rental_rates:
                    summary_parts.append("✓ Fuel prices & car rental daily rates")
                else:
                    summary_parts.append("✓ Fuel prices")

            selection_text, shortlist = self.selection_agent.present_options(self.research_results.get("attractions"))
            self.presented_attractions = shortlist
            self.phase = "selection"

            message = (
                "Great! I've gathered research for your trip:\n"
                + ("\n".join(summary_parts) + "\n\n" if summary_parts else "")
                + selection_text
            )

            return {
                "phase": "selection",
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

    def _handle_selection_message(self, user_message: str) -> Dict[str, Any]:
        if not self.research_results:
            return self._trigger_research()

        if not self.presented_attractions:
            selection_text, shortlist = self.selection_agent.present_options(self.research_results.get("attractions"))
            self.presented_attractions = shortlist
            return {
                "phase": "selection",
                "message": selection_text,
                "state": self.user_state,
                "plan": None,
            }

        chosen = self.selection_agent.parse_selection(user_message, self.presented_attractions)
        if not chosen:
            prompt = (
                "I didn't catch which attractions you liked. "
                "Please reply with the numbers from the list (e.g., '1 3') or mention them by name."
            )
            return {
                "phase": "selection",
                "message": prompt,
                "state": self.user_state,
                "plan": None,
            }

        self.selected_attractions = chosen
        return self._generate_itinerary()

    def _generate_itinerary(self) -> Dict[str, Any]:
        self.itinerary_summary = self.itinerary_agent.build_itinerary(
            self.user_state,
            self.selected_attractions,
            self.research_results or {},
        )
        budget = self.budget_agent.compute_budget(
            self.user_state,
            self.research_results or {},
            self.itinerary_summary,
        )
        self.itinerary_summary["budget"] = budget
        self.phase = "planning"
        return self._generate_plan()

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
        
        context = self.itinerary_agent.build_planning_context(
            self.user_state,
            self.research_results,
            self.itinerary_summary,
            self.itinerary_summary.get("budget") if self.itinerary_summary else None,
            self.selected_attractions,
        )
        
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
            if self.itinerary_summary and self.itinerary_summary.get("budget"):
                budget = self.itinerary_summary["budget"]
                plan_text = (
                    f"{plan_text}\n\n---\nBudget range (USD): "
                    f"${budget['low']} – ${budget['high']} (expected ${budget['expected']})."
                )

            self.phase = "complete"
            return {
                "phase": "complete",
                "message": plan_text,
                "state": self.user_state,
                "plan": {
                    "text": plan_text,
                    "research_data": self.research_results,
                    "preferences": self.user_state,
                    "selected_attractions": self.selected_attractions,
                    "itinerary": self.itinerary_summary,
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
        self.presented_attractions = []
        self.selected_attractions = []
        self.itinerary_summary = None
        self.phase = "collecting"


# ==================== EXAMPLE USAGE ====================

if __name__ == "__main__":
    """
    Simple CLI wired up to the LangGraph runtime.
    Commands:
      /state   -> show current serialized state
      /plan    -> show the latest itinerary summary
      /reset   -> start over
      /quit    -> exit
    """
    import asyncio
    import json

    from workflows.runtime import TravelPlannerRuntime
    from workflows.state import TravelPlannerState

    if not os.getenv("GOOGLE_API_KEY"):
        print("❌ Missing GOOGLE_API_KEY. Set it first.")
        exit(1)

    runtime = TravelPlannerRuntime()

    async def main():
        state = TravelPlannerState()

        async def run_and_display(payload=None):
            nonlocal state
            state, _ = await runtime.run_turn(state, payload)
            if state.last_agent_response:
                print(f"\nPlanner: {state.last_agent_response}\n")
            if state.phase == "awaiting_attraction_selection" and state.candidate_attractions:
                print("🎯 Please choose attractions (comma-separated indices):")
                for idx, attr in enumerate(state.candidate_attractions, 1):
                    name = attr.get("name", "Attraction")
                    rating = attr.get("rating")
                    rating_text = f" – {rating}⭐" if rating else ""
                    print(f"  {idx}. {name}{rating_text}")
            elif state.phase == "awaiting_itinerary_approval":
                print("✅ Approve the itinerary? (yes/no)")
            elif state.phase == "awaiting_budget_confirmation":
                print("✅ Approve the budget? (yes/no)")

        await run_and_display("")

        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break

            if not user_input:
                continue

            if user_input == "/quit":
                print("Goodbye! 👋")
                break

            if user_input == "/reset":
                state = TravelPlannerState()
                await run_and_display("")
                continue

            if user_input == "/state":
                print(json.dumps(state.model_dump(), indent=2))
                continue

            if user_input == "/plan":
                if state.itinerary.get("days"):
                    summary = "\n".join(
                        f"Day {day.get('day', idx + 1)}: "
                        + ", ".join(stop.get("name", "Attraction") for stop in day.get("stops", []))
                        for idx, day in enumerate(state.itinerary.get("days", []))
                    )
                    print(f"\n{summary}\n")
                else:
                    print("No itinerary yet. Continue the flow first.")
                continue

            if state.phase == "awaiting_attraction_selection":
                indices = [int(part) - 1 for part in user_input.split(",") if part.strip().isdigit()]
                await run_and_display({"selected_indices": indices})
                continue

            if state.phase in {"awaiting_itinerary_approval", "awaiting_budget_confirmation"}:
                await run_and_display(user_input)
                continue

            await run_and_display(user_input)

    asyncio.run(main())
