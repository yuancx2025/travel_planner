"""
Simple Chat → Research → Selection Workflow
============================================

This workflow demonstrates:
1. ChatAgent collects user preferences through conversation
2. Once complete, preferences are passed to ResearchAgent
3. Research results are returned
4. User selects attractions and restaurants interactively (LangGraph + interrupts)

This evolves the simple workflow by adding LangGraph state management and
human-in-the-loop selection steps after research completes.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, TypedDict
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END, START
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

from agents.chat_agent import ChatAgent
from agents.research_agent import ResearchAgent
from agents.itinerary_agent import ItineraryAgent
from agents.budget_agent import BudgetAgent


# ==================== UTILS ====================

def _safe_int(value: Any) -> Optional[int]:
    """Best-effort conversion of numeric inputs to int."""
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ==================== STATE MODEL ====================

class WorkflowState(TypedDict):
    """LangGraph state for chat → research → selection workflow."""
    # Chat phase
    preferences: Dict[str, Any]
    chat_complete: bool
    
    # Research phase
    research_results: Optional[Dict[str, Any]]
    
    # Selection phase
    selected_attractions: Optional[List[Dict[str, Any]]]
    selected_restaurants: Optional[List[Dict[str, Any]]]

    # Itinerary phase
    itinerary: Optional[Dict[str, Any]]
    planning_context: Optional[str]
    budget_summary: Optional[Dict[str, Any]]
    
    # Control flow
    phase: str  # "collecting" | "researching" | "selecting_attractions" | "selecting_restaurants" | "building_itinerary" | "complete"


class SelectionSummary(BaseModel):
    """Validated summary returned after selections are complete."""

    destination: Optional[str] = None
    travel_days: Optional[int] = Field(default=None, ge=0)
    budget_usd: Optional[Any] = None
    selected_attractions: List[Dict[str, Any]] = Field(default_factory=list)
    selected_restaurants: List[Dict[str, Any]] = Field(default_factory=list)
    itinerary: Optional[Dict[str, Any]] = None
    planning_context: Optional[str] = None
    budget_summary: Optional[Dict[str, Any]] = None


# ==================== WORKFLOW CLASS ====================

class ChatResearchSelectionWorkflow:
    """
    Workflow with LangGraph state management for chat → research → selection.
    
    Flow:
    1. ChatAgent collects preferences (interactive)
    2. ResearchAgent runs when preferences complete
    3. User selects attractions (interrupt for input)
    4. User selects restaurants (interrupt for input)
    5. Workflow returns final selections
    """
    
    def __init__(
        self,
        *,
        chat_agent: Optional[ChatAgent] = None,
        research_agent: Optional[ResearchAgent] = None,
        itinerary_agent: Optional[ItineraryAgent] = None,
        budget_agent: Optional[BudgetAgent] = None,
    ):
        """
        Initialize with optional agent injection (useful for testing).
        
        Args:
            chat_agent: ChatAgent instance (creates default if None)
            research_agent: ResearchAgent instance (creates default if None)
            itinerary_agent: ItineraryAgent instance (creates default if None)
            budget_agent: BudgetAgent instance (creates default if None)
        """
        self.chat_agent = chat_agent or ChatAgent()
        self.research_agent = research_agent or ResearchAgent()
        self.itinerary_agent = itinerary_agent or ItineraryAgent()
        self.budget_agent = budget_agent or BudgetAgent()
        
        # Build LangGraph workflow
        self.graph = self._build_graph()
        self.checkpointer = MemorySaver()
        self.app = self.graph.compile(checkpointer=self.checkpointer)
        
        # Thread ID for checkpointer
        self.thread_id = "default"
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        workflow = StateGraph(WorkflowState)
        
        # Nodes
        workflow.add_node("run_research", self._run_research_node)
        workflow.add_node("await_attraction_selection", self._await_attraction_selection_node)
        workflow.add_node("await_restaurant_selection", self._await_restaurant_selection_node)
        workflow.add_node("build_itinerary", self._build_itinerary_node)
        
        # Edges
        workflow.add_edge(START, "run_research")
        workflow.add_edge("run_research", "await_attraction_selection")
        workflow.add_edge("await_attraction_selection", "await_restaurant_selection")
        workflow.add_edge("await_restaurant_selection", "build_itinerary")
        workflow.add_edge("build_itinerary", END)
        
        return workflow
    
    # ==================== GRAPH NODES ====================
    
    def _run_research_node(self, state: WorkflowState) -> Dict[str, Any]:
        """Node: Execute research based on preferences."""
        print("\n🔍 Running research for your trip...\n")
        
        research_results = self.research_agent.research(state["preferences"])
        
        return {
            "research_results": research_results,
            "phase": "selecting_attractions",
        }
    
    def _await_attraction_selection_node(self, state: WorkflowState) -> Dict[str, Any]:
        """Node: Pause for user to select attractions."""
        attractions = state["research_results"].get("attractions", [])
        valid_attractions = [a for a in attractions if not a.get("error")]

        if not valid_attractions:
            errors = [a.get("error") for a in attractions if a.get("error")]
            if errors:
                print(f"⚠️  Could not fetch attractions: {errors[0]}\n")
            else:
                print("⚠️  No attractions found, skipping selection.\n")
            return {"selected_attractions": [], "phase": "selecting_restaurants"}
        
        # Display options
        print("\n🎡 ATTRACTIONS FOUND:")
        print("=" * 70)
        for idx, attr in enumerate(valid_attractions, 1):
            rating = f"{attr.get('rating')}⭐" if attr.get('rating') else "N/A"
            print(f"  {idx}. {attr.get('name')} ({rating})")
        print("=" * 70)
        
        # Interrupt and wait for user input
        selection_input = interrupt(
            "Enter attraction numbers to visit (e.g., '1,3,5' or 'all' or 'none'): "
        )
        
        # Parse selection
        selected = self._parse_selection(selection_input, valid_attractions)
        
        print(f"\n✅ Selected {len(selected)} attraction(s)\n")
        
        return {
            "selected_attractions": selected,
            "phase": "selecting_restaurants",
        }
    
    def _await_restaurant_selection_node(self, state: WorkflowState) -> Dict[str, Any]:
        """Node: Pause for user to select restaurants."""
        restaurants = state["research_results"].get("dining", [])
        valid_restaurants = [r for r in restaurants if not r.get("error")]

        if not valid_restaurants:
            errors = [r.get("error") for r in restaurants if r.get("error")]
            if errors:
                print(f"⚠️  Could not fetch restaurants: {errors[0]}\n")
            else:
                print("⚠️  No restaurants found, skipping selection.\n")
            return {"selected_restaurants": [], "phase": "building_itinerary"}
        
        # Display options
        print("\n🍽️  RESTAURANTS FOUND:")
        print("=" * 70)
        for idx, rest in enumerate(valid_restaurants, 1):
            rating = f"{rest.get('rating')}⭐" if rest.get('rating') else "N/A"
            price = self._format_price_level(rest.get("price_level"))
            print(f"  {idx}. {rest.get('name')} ({rating}, {price})")
        print("=" * 70)
        
        # Interrupt and wait for user input
        selection_input = interrupt(
            "Enter restaurant numbers to visit (e.g., '1,2,4' or 'all' or 'none'): "
        )
        
        # Parse selection
        selected = self._parse_selection(selection_input, valid_restaurants)
        
        print(f"\n✅ Selected {len(selected)} restaurant(s)\n")
        
        return {
            "selected_restaurants": selected,
            "phase": "building_itinerary",
        }

    def _build_itinerary_node(self, state: WorkflowState) -> Dict[str, Any]:
        """Node: Build itinerary using selected options."""
        preferences = state.get("preferences") or {}
        research_results = state.get("research_results") or {}
        selected_attractions = state.get("selected_attractions") or []
        selected_restaurants = state.get("selected_restaurants") or []

        attractions_input = selected_attractions or [
            item for item in research_results.get("attractions", []) if not item.get("error")
        ]

        itinerary: Optional[Dict[str, Any]] = None
        planning_context: Optional[str] = None
        budget_summary: Optional[Dict[str, Any]] = None

        try:
            itinerary = self.itinerary_agent.build_itinerary(
                preferences=preferences,
                attractions=attractions_input,
                research=research_results,
            ) if attractions_input else None
            if itinerary and selected_restaurants and isinstance(itinerary, dict):
                itinerary.setdefault("meta", {}).setdefault("notes", {})[
                    "selected_restaurants"
                ] = selected_restaurants
        except Exception as exc:  # pragma: no cover - safeguard against downstream errors
            print(f"⚠️  Itinerary generation failed: {exc}")
            itinerary = {"error": str(exc)}

        try:
            if research_results:
                budget_summary = self.budget_agent.compute_budget(
                    preferences=preferences,
                    research=research_results,
                    itinerary=itinerary if isinstance(itinerary, dict) else None,
                )
        except Exception as exc:  # pragma: no cover
            print(f"⚠️  Budget estimation failed: {exc}")

        try:
            planning_context = self.itinerary_agent.build_planning_context(
                user_state=preferences,
                research_results=research_results,
                itinerary=itinerary if isinstance(itinerary, dict) else None,
                budget=budget_summary,
                selected_attractions=attractions_input or None,
            )
        except Exception as exc:  # pragma: no cover
            print(f"⚠️  Planning context generation failed: {exc}")

        return {
            "itinerary": itinerary,
            "planning_context": planning_context,
            "budget_summary": budget_summary,
            "phase": "complete",
        }
    
    # ==================== HELPER METHODS ====================
    
    @staticmethod
    def _parse_selection(user_input: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse user selection string into list of items."""
        if not user_input:
            return []
        
        user_input = user_input.strip().lower()
        
        # Handle special keywords
        if user_input in {"all", "a"}:
            return items
        
        if user_input in {"none", "n", "skip"}:
            return []
        
        # Parse comma-separated numbers
        selected = []
        try:
            indices = [int(x.strip()) for x in user_input.split(",")]
            for idx in indices:
                if 1 <= idx <= len(items):
                    selected.append(items[idx - 1])
        except ValueError:
            print(f"⚠️  Invalid selection: '{user_input}'. Skipping.")
            return []
        
        return selected
    
    @staticmethod
    def _format_price_level(value: Any) -> str:
        """Normalize price level representations to dollar signs."""
        if value is None:
            return "$$"

        if isinstance(value, (int, float)):
            repeat = max(1, int(round(value)))
            return "$" * repeat

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return "$$"
            if stripped.isdigit():
                repeat = max(1, int(stripped))
                return "$" * repeat
            if all(ch == "$" for ch in stripped):
                return stripped
            return stripped

        return "$$"
    
    def collect_preferences(self, user_message: str, current_preferences: Dict[str, Any]) -> Dict[str, Any]:
        """
        Collect preferences via ChatAgent (used before triggering graph).
        
        Args:
            user_message: User's message
            current_preferences: Current preference state
            
        Returns:
            {
                "agent_reply": str,
                "preferences": dict,
                "missing_fields": list,
                "complete": bool,
            }
        """
        chat_result = self.chat_agent.collect_info(user_message, state=current_preferences)
        
        agent_reply = self._consume_stream(chat_result.get("stream"))
        
        return {
            "agent_reply": agent_reply,
            "preferences": chat_result["state"],
            "missing_fields": chat_result["missing_fields"],
            "complete": chat_result["complete"],
        }
    
    def run_workflow(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the LangGraph workflow (research → selections).
        
        This is called AFTER preferences are fully collected.
        Returns the final state with selections.
        """
        initial_state: WorkflowState = {
            "preferences": preferences,
            "chat_complete": True,
            "research_results": None,
            "selected_attractions": None,
            "selected_restaurants": None,
            "itinerary": None,
            "planning_context": None,
            "budget_summary": None,
            "phase": "researching",
        }
        
        config = {"configurable": {"thread_id": self.thread_id}}
        
        # Run until first interrupt (attraction selection)
        result = None
        for event in self.app.stream(initial_state, config, stream_mode="values"):
            result = event
        
        # Resume with user input (handled externally in interactive mode)
        return result
    
    def resume_with_input(self, user_input: Any) -> Dict[str, Any]:
        """
        Resume workflow after interrupt with user input.
        
        Args:
            user_input: User's selection input
            
        Returns:
            Updated state after resumption
        """
        config = {"configurable": {"thread_id": self.thread_id}}
        
        result = None
        for event in self.app.stream(Command(resume=user_input), config, stream_mode="values"):
            result = event
        
        return result
    
    @staticmethod
    def _consume_stream(stream) -> str:
        """Convert ChatAgent's streaming response to text."""
        if stream is None:
            return ""
        
        chunks = []
        try:
            for chunk in stream:
                if hasattr(chunk, "content"):
                    chunks.append(chunk.content)
        except Exception as e:
            print(f"⚠️  Stream error: {e}")
        
        return "".join(chunks)


# ==================== LEGACY SIMPLE CLASS (for backward compatibility) ====================

class SimpleChatResearchWorkflow:
    """
    Minimal workflow showing ChatAgent → ResearchAgent integration.
    
    Flow:
    1. User sends message → ChatAgent extracts preferences
    2. ChatAgent streams conversational reply
    3. When all required fields collected → trigger ResearchAgent
    4. ResearchAgent fans out to APIs, returns structured data
    5. Workflow returns both chat response and research results
    """
    
    def __init__(
        self,
        *,
        chat_agent: Optional[ChatAgent] = None,
        research_agent: Optional[ResearchAgent] = None,
    ):
        """
        Initialize with optional agent injection (useful for testing).
        
        Args:
            chat_agent: ChatAgent instance (creates default if None)
            research_agent: ResearchAgent instance (creates default if None)
        """
        self.chat_agent = chat_agent or ChatAgent()
        self.research_agent = research_agent or ResearchAgent()
        
        # Workflow state (simple dict, no fancy state machines)
        self.preferences: Dict[str, Any] = {}
        self.research_results: Optional[Dict[str, Any]] = None
        self.phase: str = "collecting"  # "collecting" | "complete"
    
    def send_message(self, user_message: str) -> Dict[str, Any]:
        """
        Process a user message and return the response.
        
        This is the main entry point. Call it with each user message,
        and it handles the chat → research handoff automatically.
        
        Args:
            user_message: What the user said
            
        Returns:
            {
                "agent_reply": str,              # What to show the user
                "preferences": dict,             # Current collected preferences
                "missing_fields": list,          # What's still needed
                "complete": bool,                # All preferences collected?
                "research_results": dict | None, # Research data (if complete)
                "phase": str,                    # "collecting" | "complete"
            }
        """
        # Step 1: Let ChatAgent process the message and extract preferences
        chat_result = self.chat_agent.collect_info(user_message, state=self.preferences)
        
        # Step 2: Update our workflow state with extracted preferences
        self.preferences = chat_result["state"]
        missing = chat_result["missing_fields"]
        complete = chat_result["complete"]
        
        # Step 3: Convert streaming response to text for simplicity
        agent_reply = self._consume_stream(chat_result.get("stream"))
        
        # Step 4: If preferences are complete AND we haven't researched yet → trigger research
        if complete and self.research_results is None:
            print("\n🔍 All preferences collected! Triggering research...\n")
            self.research_results = self.research_agent.research(self.preferences)
            self.phase = "complete"
        
        # Step 5: Return everything the caller needs
        return {
            "agent_reply": agent_reply,
            "preferences": dict(self.preferences),
            "missing_fields": missing,
            "complete": complete,
            "research_results": self.research_results,
            "phase": self.phase,
        }
    
    def get_research_summary(self) -> str:
        """
        Get a human-readable summary of research results.
        
        Returns:
            Formatted text describing what was found (or empty if no research yet)
        """
        if not self.research_results:
            return "No research data available yet."
        
        lines = ["=" * 70, "📊 RESEARCH SUMMARY", "=" * 70]
        
        # Weather
        if self.research_results.get("weather"):
            weather = self.research_results["weather"]
            lines.append(f"\n☀️  WEATHER ({len(weather)} days forecasted)")
            for day in weather[:3]:
                lines.append(
                    f"  {day.get('date')}: {day.get('temp_low')}–{day.get('temp_high')} "
                    f"({day.get('summary')})"
                )
        
        # Attractions
        if self.research_results.get("attractions"):
            attractions = self.research_results["attractions"]
            lines.append(f"\n🎡 ATTRACTIONS ({len(attractions)} found)")
            for idx, attr in enumerate(attractions[:5], 1):
                rating = f"{attr.get('rating')}⭐" if attr.get('rating') else "N/A"
                lines.append(f"  {idx}. {attr.get('name')} ({rating})")
        
        # Dining
        if self.research_results.get("dining"):
            dining = self.research_results["dining"]
            lines.append(f"\n🍽️  DINING ({len(dining)} restaurants)")
            for idx, rest in enumerate(dining[:5], 1):
                rating = f"{rest.get('rating')}⭐" if rest.get('rating') else "N/A"
                price_level = rest.get("price_level")
                price = self._format_price_level(price_level)
                lines.append(f"  {idx}. {rest.get('name')} ({rating}, {price})")
        
        # Hotels
        if self.research_results.get("hotels"):
            hotels = self.research_results["hotels"]
            lines.append(f"\n🏨 HOTELS ({len(hotels)} options)")
            for idx, hotel in enumerate(hotels[:5], 1):
                price = hotel.get("price", {})
                amount = price.get("amount", "N/A") if isinstance(price, dict) else price
                lines.append(f"  {idx}. {hotel.get('name')} (${amount}/night)")
        
        # Flights
        if self.research_results.get("flights"):
            flights = self.research_results["flights"]
            lines.append(f"\n✈️  FLIGHTS ({len(flights)} offers)")
            for idx, flight in enumerate(flights[:3], 1):
                carrier = flight.get("carrier", "N/A")
                price = flight.get("price", {})
                amount = price.get("amount", "N/A") if isinstance(price, dict) else price
                lines.append(f"  {idx}. {carrier} – ${amount}")
        
        # Car/Fuel
        if self.research_results.get("car_rentals"):
            cars = self.research_results["car_rentals"]
            lines.append(f"\n🚗 CAR RENTALS ({len(cars)} options)")
            for idx, car in enumerate(cars[:3], 1):
                supplier = car.get("supplier", "N/A")
                vehicle = car.get("vehicle", {})
                price = car.get("price", {})
                amount = price.get("amount", "N/A") if isinstance(price, dict) else price
                lines.append(f"  {idx}. {supplier} – {vehicle.get('class', 'N/A')} (${amount})")
        
        if self.research_results.get("fuel_prices"):
            fp = self.research_results["fuel_prices"]
            lines.append(f"\n⛽ FUEL PRICES ({fp.get('location', 'N/A')})")
            lines.append(f"  Regular: ${fp.get('regular', 'N/A')}/gal")
            if fp.get("economy_car_daily"):
                lines.append(f"  Economy car rental: ${fp['economy_car_daily']}/day")
        
        # Distances
        if self.research_results.get("distances"):
            distances = self.research_results["distances"]
            lines.append(f"\n📍 DISTANCES ({len(distances)} routes)")
            for dist in distances[:3]:
                km = dist.get("distance_m", 0) / 1000
                mins = dist.get("duration_s", 0) / 60
                lines.append(
                    f"  {dist.get('origin_name', 'A')} → {dist.get('dest_name', 'B')}: "
                    f"{km:.1f}km, {mins:.0f}min"
                )
        
        lines.append("\n" + "=" * 70)
        return "\n".join(lines)

    @staticmethod
    def _format_price_level(value: Any) -> str:
        """Normalize price level representations to dollar signs."""
        if value is None:
            return "$$"

        if isinstance(value, (int, float)):
            repeat = max(1, int(round(value)))
            return "$" * repeat

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return "$$"
            if stripped.isdigit():
                repeat = max(1, int(stripped))
                return "$" * repeat
            if all(ch == "$" for ch in stripped):
                return stripped
            return stripped

        return "$$"

    def reset(self):
        """Clear all state and start over."""
        self.preferences = {}
        self.research_results = None
        self.phase = "collecting"
        self.chat_agent.conversation_history.clear()
    
    @staticmethod
    def _consume_stream(stream) -> str:
        """Convert ChatAgent's streaming response to text."""
        if stream is None:
            return ""
        
        chunks = []
        try:
            for chunk in stream:
                if hasattr(chunk, "content"):
                    chunks.append(chunk.content)
        except Exception as e:
            print(f"⚠️  Stream error: {e}")
        
        return "".join(chunks)


# ==================== INTERACTIVE DEMO ====================

def run_interactive_selection_demo():
    """
    Interactive demo with LangGraph-powered selection flow.
    
    Flow:
    1. Chat to collect preferences
    2. Automatic research
    3. Select attractions (interactive)
    4. Select restaurants (interactive)
    5. View final plan
    
    Usage:
        python -m workflows.simple_chat_research_workflow --with-selection
    """
    import os
    
    print("=" * 70)
    print("🧪 CHAT → RESEARCH → SELECTION WORKFLOW DEMO")
    print("=" * 70)
    print("\nThis demo shows the full workflow:")
    print("1. ChatAgent collects preferences")
    print("2. ResearchAgent finds options")
    print("3. You select attractions and restaurants interactively\n")
    
    if not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
        print("❌ Missing GOOGLE_API_KEY or GEMINI_API_KEY")
        print("Set one of these environment variables to run the demo.\n")
        return
    
    workflow = ChatResearchSelectionWorkflow()
    preferences = {}
    
    print("Commands:")
    print("  /state   - Show collected preferences")
    print("  /quit    - Exit")
    print("\n" + "=" * 70 + "\n")
    
    # Phase 1: Collect preferences
    print("📝 STEP 1: Collecting your travel preferences...\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input == "/quit":
                print("👋 Goodbye!")
                return
            
            if user_input == "/state":
                print("\n📋 Current Preferences:")
                print(json.dumps(preferences, indent=2))
                print()
                continue
            
            # Collect preferences
            result = workflow.collect_preferences(user_input, preferences)
            preferences = result["preferences"]
            
            # Show agent's reply
            print(f"\nAgent: {result['agent_reply']}\n")
            
            # Show progress
            if not result["complete"] and result["missing_fields"]:
                print(f"[Still need: {', '.join(result['missing_fields'])}]\n")
            
            # If complete, move to research + selection
            if result["complete"]:
                print("\n✅ All preferences collected!\n")
                break
        
        except KeyboardInterrupt:
            print("\n👋 Interrupted. Type /quit to exit.\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")
    
    # Phase 2: Run LangGraph workflow (research → selections)
    print("\n" + "=" * 70)
    print("📊 STEP 2: Running research and interactive selection...")
    print("=" * 70 + "\n")
    
    try:
        # Initialize and run workflow
        config = {"configurable": {"thread_id": workflow.thread_id}}
        
        payload: Any = {
            "preferences": preferences,
            "chat_complete": True,
            "research_results": None,
            "selected_attractions": None,
            "selected_restaurants": None,
            "itinerary": None,
            "planning_context": None,
            "budget_summary": None,
            "phase": "researching",
        }
        
        final_state: Optional[Dict[str, Any]] = None
        
        while True:
            interrupted = False
            for event in workflow.app.stream(payload, config, stream_mode="values"):
                if os.getenv("DEBUG_SELECTION"):  # pragma: no cover
                    print(f"[DEBUG] event type={type(event)} value={event}")

                interrupt_payload = None
                prompt_text = None

                if isinstance(event, Command):
                    interrupt_payload = event
                    prompt_text = getattr(event, "value", None)
                elif isinstance(event, dict) and "__interrupt__" in event:
                    interrupt_payload = event["__interrupt__"][0]
                    prompt_text = getattr(interrupt_payload, "value", None)

                if interrupt_payload is not None:
                    if isinstance(prompt_text, dict):
                        prompt_text = prompt_text.get("prompt") or prompt_text.get("message")
                    if not isinstance(prompt_text, str):
                        prompt_text = "Selection: "

                    try:
                        user_input = input(prompt_text).strip()
                        print()
                    except KeyboardInterrupt:
                        print("\n👋 Interrupted during selection. Exiting.\n")
                        return

                    payload = Command(resume=user_input)
                    interrupted = True
                    break

                final_state = event

            if not interrupted:
                break
        
        # Phase 3: Show final selections
        print("\n" + "=" * 70)
        print("🎉 STEP 3: Your Final Travel Plan")
        print("=" * 70)
        
        if not final_state:
            print("\n⚠️  Workflow ended before producing a final plan.\n")
            return

        summary = SelectionSummary(
            destination=preferences.get("destination_city"),
            travel_days=_safe_int(preferences.get("travel_days")),
            budget_usd=preferences.get("budget_usd"),
            selected_attractions=final_state.get("selected_attractions") or [],
            selected_restaurants=final_state.get("selected_restaurants") or [],
            itinerary=final_state.get("itinerary"),
            planning_context=final_state.get("planning_context"),
            budget_summary=final_state.get("budget_summary"),
        )

        print(f"\n📍 Destination: {summary.destination or 'N/A'}")
        if summary.travel_days is not None:
            print(f"📅 Duration: {summary.travel_days} day(s)")
        print(f"💰 Budget: {summary.budget_usd if summary.budget_usd is not None else 'N/A'}")

        print(f"\n🎡 SELECTED ATTRACTIONS ({len(summary.selected_attractions)}):")
        for idx, attr in enumerate(summary.selected_attractions, 1):
            rating = f"{attr.get('rating')}⭐" if attr.get('rating') else "N/A"
            print(f"  {idx}. {attr.get('name')} ({rating})")

        print(f"\n🍽️  SELECTED RESTAURANTS ({len(summary.selected_restaurants)}):")
        for idx, rest in enumerate(summary.selected_restaurants, 1):
            rating = f"{rest.get('rating')}⭐" if rest.get('rating') else "N/A"
            price = workflow._format_price_level(rest.get("price_level"))
            print(f"  {idx}. {rest.get('name')} ({rating}, {price})")

        itinerary = summary.itinerary or {}
        if itinerary.get("error"):
            print(f"\n⚠️  Itinerary generation failed: {itinerary['error']}")
        elif itinerary.get("days"):
            print(f"\n🗓️  ITINERARY OVERVIEW ({len(itinerary['days'])} day(s)):")
            for day in itinerary["days"]:
                day_num = day.get("day")
                stops = ", ".join(stop.get("name", "Stop") for stop in day.get("stops", [])) or "Flex time"
                print(f"  Day {day_num}: {stops}")
                route = day.get("route")
                if route and route.get("distance_m"):
                    km = route["distance_m"] / 1000
                    mins = (route.get("duration_s", 0) or 0) / 60
                    mode = route.get("mode", "DRIVE")
                    print(f"    • Route: {km:.1f} km, {mins:.0f} min ({mode})")

        if summary.planning_context:
            print("\n📘 PLANNING CONTEXT PREVIEW:")
            preview_lines = summary.planning_context.strip().splitlines()
            for line in preview_lines[:10]:
                print(f"  {line}")
            if len(preview_lines) > 10:
                print("  … (truncated, see planning context for full details)")

        if summary.budget_summary and isinstance(summary.budget_summary, dict):
            print("\n💵 BUDGET SNAPSHOT:")
            expected = summary.budget_summary.get("expected")
            low = summary.budget_summary.get("low")
            high = summary.budget_summary.get("high")
            currency = summary.budget_summary.get("currency", "USD")
            spend_text = f"{currency} ${expected}" if expected is not None else "N/A"
            range_text = None
            if low is not None and high is not None:
                range_text = f"${low} – ${high}"
            elif low is not None:
                range_text = f"≥ ${low}"
            elif high is not None:
                range_text = f"≤ ${high}"
            if range_text:
                print(f"  Estimated spend: {spend_text} (range {range_text})")
            else:
                print(f"  Estimated spend: {spend_text}")
            breakdown = summary.budget_summary.get("breakdown") or {}
            if breakdown:
                for key, value in breakdown.items():
                    label = key.replace("_", " ").title()
                    amount = f"${value}" if value is not None else "N/A"
                    print(f"  • {label}: {amount}")

        print("\n" + "=" * 70)
        print("✅ Workflow complete! Enjoy your trip! 🌍")
        print("=" * 70 + "\n")
    
    except KeyboardInterrupt:
        print("\n👋 Interrupted.\n")
    except Exception as e:
        print(f"\n❌ Error during workflow: {e}\n")
        import traceback
        traceback.print_exc()


# ==================== PROGRAMMATIC EXAMPLE ====================

def example_programmatic_usage():
    """
    Example showing how to use the workflow programmatically (not interactively).
    
    This is what you'd use in tests or when building a UI.
    """
    workflow = SimpleChatResearchWorkflow()
    
    # Simulate a conversation
    messages = [
        "I want to visit Orlando",
        "3 days in March",
        "$2000 budget for 2 people",
        "No kids, we like outdoor activities",
        "Yes we need a car rental, prefer 1 king bed hotel room",
        "We love seafood",
    ]
    
    for msg in messages:
        result = workflow.send_message(msg)
        print(f"User: {msg}")
        print(f"Agent: {result['agent_reply'][:100]}...")
        
        if result["complete"]:
            print("\n✅ Preferences complete! Research triggered.")
            break
    
    # Access the data
    if workflow.research_results:
        print(f"\nFound {len(workflow.research_results.get('attractions', []))} attractions")
        print(f"Found {len(workflow.research_results.get('hotels', []))} hotels")


if __name__ == "__main__":
    run_interactive_selection_demo()
