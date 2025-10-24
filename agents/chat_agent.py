import os
import json
from typing import Generator, Dict, Any, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

class ChatAgent:
    """
    A focused, front-end-friendly chatter agent that:
    - uses only an LLM to extract user preferences,
    - maintains minimal conversation history,
    - asks for missing info step-by-step (1→8),
    - streams replies for a snappy UI experience,
    - never calls external tools (gather-only).
    """

    def __init__(self, model_name: str = "gemini-2.0-flash", temperature: float = 0.2, model=None):
        self.model = model if model is not None else ChatGoogleGenerativeAI(model=model_name, temperature=temperature, streaming=True)

        # === REQUIRED FIELDS (aligned with your 8 steps) ===
        self.required_fields: List[str] = [
            "name",                # Step 1
            "destination_city",    # Step 2  (your "city of preference")
            "travel_days",         # Step 3 (duration)
            "start_date",          # Step 3 (allow "not decided")
            "budget_usd",          # Step 4
            "num_people",          # Step 5
            "kids",                # Step 5 (yes/no or count)
            "activity_pref",       # Step 6 ("outdoor" or "indoor")
            "need_car_rental",     # Step 7 (yes/no)
            "hotel_room_pref",     # Step 8 (e.g., "1 king", "2 queens")
            "cuisine_pref",        # Step 9
        ]

        # === OPTIONAL FIELDS (kept light; won’t block completion) ===
        self.optional_fields: List[str] = [
            "origin_city",         # where they start (nice to have)
            "home_airport",        # optional IATA
            "specific_requirements"  # accessibility/dietary/constraints
        ]

        self.all_fields = self.required_fields + self.optional_fields
        self.conversation_history: List[Any] = []  # [SystemMessage/HumanMessage/AIMessage]

    # ---------------------------
    # Conversation initialization
    # ---------------------------
    def _init_system_message(self) -> SystemMessage:
        """One concise directive the model will follow for the whole chat."""
        return SystemMessage(
            content=(
                "You are a friendly US travel intake assistant. "
                "Your job is to gather the user's trip preferences in a natural, conversational way. "
                "Do NOT book or search anything. Only collect information.\n\n"
                "Required fields you must help the user fill (in a friendly way):\n"
                "1) name\n"
                "2) destination_city (their preferred city)\n"
                "3) travel_days and start_date (YYYY-MM-DD; if not known, user can say 'not decided')\n"
                "4) budget_usd (numeric)\n"
                "5) num_people and kids (yes/no or a count)\n"
                "6) activity_pref ('outdoor' or 'indoor'), need_car_rental (yes/no), hotel_room_pref (e.g., '1 king')\n"
                "7) cuisine_pref (e.g., 'ramen', 'vegan', 'seafood', 'kid-friendly')\n"
                "8) Summarize and confirm. Do not hand off to other agents.\n\n"
                "Also capture optional fields if mentioned: origin_city, home_airport, specific_requirements "
                "(e.g., accessibility, dietary restrictions, special constraints). "
                "Always acknowledge information already provided; ask one or two natural questions at a time."
            )
        )

    # ---------------------------
    # Public API: main entrypoint
    # ---------------------------
    def collect_info(self, user_input: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Incrementally collect info:
        - Extract any fields present in `user_input` using the LLM (JSON),
        - Merge into `state`,
        - Ask a natural next question about the next missing field(s),
        - Return a streaming reply + updated state + missing fields + completion flag.
        """
        if state is None:
            state = {}

        # Initialize conversation on first call
        if not self.conversation_history:
            self.conversation_history.append(self._init_system_message())

        # 1) LLM extraction → structured fields (merge if present)
        if user_input and user_input.strip():
            new_info = self.extract_info_from_message(user_input, current_state=state)
            for field, value in new_info.items():
                if value not in (None, "", []):
                    state[field] = value

            # Add user turn to history
            self.conversation_history.append(HumanMessage(content=user_input))

        # 2) Compute what's missing
        missing = [f for f in self.required_fields if not state.get(f)]
        complete = len(missing) == 0

        # 3) Build a guiding system message for the assistant’s next turn
        guidance = self._build_guidance_system_message(state, missing)
        messages = self.conversation_history + [guidance]

        # 4) Stream the model’s response for UI
        try:
            response_stream = self.model.stream(messages)
            return {
                "stream": response_stream,
                "missing_fields": missing,
                "complete": complete,
                "state": state.copy()
            }
        except Exception as e:
            return {
                "stream": None,
                "missing_fields": missing,
                "complete": complete,
                "state": state.copy(),
                "error": str(e)
            }

    def interact_with_user(self, message: str) -> Generator:
        """
        Lightweight stream of the assistant continuation given the current conversation history.
        Use this if you want to stream a reply without updating state.
        """
        self.conversation_history.append(HumanMessage(content=message))
        try:
            return self.model.stream(self.conversation_history)
        except Exception as e:
            print(f"Error in interact_with_user: {e}")
            return None

    # ---------------------------
    # LLM-powered field extraction
    # ---------------------------
    def extract_info_from_message(self, message: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use an LLM to extract ALL relevant fields from arbitrary user text.
        No regexes or hard-coded parsing — model-only extraction to JSON.
        """
        system_prompt = f"""
Extract the user's travel details and return a SINGLE JSON object with these keys:
{', '.join([f'"{f}"' for f in self.all_fields])}

Rules:
- If a field isn't mentioned, set it to "" (empty string).
- name: string (first name is fine).
- destination_city: city name string.
- travel_days: integer if clear; else "".
- start_date: if provided, format YYYY-MM-DD; if unclear/unknown/not provided, set to "not decided".
- budget_usd: numeric (strip $ and commas). If unclear, "".
- num_people: integer if clear; else "".
- kids: "yes" | "no" | integer count | "". If user says "no kids" or "all adults", set "no".
- activity_pref: "outdoor" | "indoor" | "" (pick the dominant preference if clearly stated).
- need_car_rental: "yes" | "no" | "" (keep as string for downstream UI).
- hotel_room_pref: short text like "1 king", "2 queens", "suite" if explicitly mentioned; else "".
- cuisine_pref: short text (e.g., "ramen", "vegan", "seafood", "kid-friendly") if mentioned; else "".
- origin_city, home_airport are optional; fill only if clearly present; otherwise "".
- specific_requirements: any accessibility needs, dietary restrictions, constraints, or special requests; else "".

Current known state (may be partial, use it to stay consistent but do NOT hallucinate):
{json.dumps(current_state, ensure_ascii=False)}
"""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=message)
        ]

        try:
            llm_response = self.model.invoke(messages)
            data = json.loads(llm_response.content)

            # Only keep non-empty values
            filtered: Dict[str, Any] = {}
            for field in self.all_fields:
                val = data.get(field, "")
                if val not in ("", None, []):
                    filtered[field] = val
            return filtered

        except Exception as e:
            print("Error parsing LLM output:", e)
            return {}

    # ---------------------------
    # Guidance for next assistant turn
    # ---------------------------
    def _build_guidance_system_message(self, state: Dict[str, Any], missing: List[str]) -> SystemMessage:
        """
        Tells the assistant what’s already known, what’s missing, and how to ask next.
        Keeps the reply friendly and concise. Handles Step 8 summary.
        """
        # Friendly labels for better natural prompts
        labels = {
            "name": "your name",
            "destination_city": "the city you'd like to visit",
            "travel_days": "how many days you’ll travel",
            "start_date": "your start date (YYYY-MM-DD, or say 'not decided')",
            "budget_usd": "your total trip budget in USD",
            "num_people": "how many people are traveling",
            "kids": "whether kids are coming (yes/no or a count)",
            "activity_pref": "whether you prefer outdoor or indoor activities",
            "need_car_rental": "whether you need a car rental (yes/no)",
            "hotel_room_pref": "your hotel room preference (e.g., '1 king' or '2 queens')",
            "cuisine_pref": "any cuisine preference (e.g., ramen, seafood, vegan)",
        }

        # Step 8 summary text
        def summary_text(st: Dict[str, Any]) -> str:
            def _get(k, default="(not provided)"): return st.get(k) or default
            kids_str = _get("kids", "no")
            car_str = _get("need_car_rental", "no")
            return (
                "Here’s what I have so far:\n"
                f"- Name: {_get('name')}\n"
                f"- Destination: {_get('destination_city')}\n"
                f"- Travel: {_get('travel_days')} day(s), starting {_get('start_date')}\n"
                f"- Budget: ${_get('budget_usd')}\n"
                f"- Group: {_get('num_people')} traveler(s), kids: {kids_str}\n"
                f"- Activities: {_get('activity_pref')} | Car rental: {car_str}\n"
                f"- Hotel room: {_get('hotel_room_pref')}\n"
                f"- Cuisine: {_get('cuisine_pref')}\n\n"
                "If this looks right, say 'confirm'. If not, tell me what to change."
            )

        if not missing:
            # Step 8: Summarize + confirm
            text = summary_text(state)
        else:
            # Ask for the next missing field(s) naturally (1–2 at a time)
            ask_these = missing[:2]
            asks = [labels[m] for m in ask_these if m in labels]
            text = (
                f"Current state: {json.dumps(state, ensure_ascii=False)}\n"
                f"Missing: {', '.join(missing)}\n\n"
                f"Please reply conversationally. Acknowledge what we already have, then ask for: "
                f"{' and '.join(asks)}. "
                "Remind the user they can say 'not decided' for the start date if unsure."
            )

        return SystemMessage(content=text)
