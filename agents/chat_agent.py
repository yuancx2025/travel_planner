import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

# Add parent directory to path when running as script so we can import prompts module
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from prompts import PromptTemplate, load_prompt_template


class ChatAgent:
    """
    A focused, front-end-friendly chatter agent that:
    - uses only an LLM to extract user preferences,
    - maintains minimal conversation history,
    - asks for missing info step-by-step (1→8),
    - streams replies for a snappy UI experience,
    - never calls external tools (gather-only).
    """

    def __init__(
        self,
        model_name: str = "gemini-2.0-flash",
        temperature: float = 0.2,
        model=None,
        intake_prompt: Optional[PromptTemplate] = None,
        extraction_prompt: Optional[PromptTemplate] = None,
    ):
        # Validate API key
        if not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            print("⚠️  Warning: Missing GOOGLE_API_KEY or GEMINI_API_KEY. ChatAgent may not function properly.")
        
        self.model = model if model is not None else ChatGoogleGenerativeAI(model=model_name, temperature=temperature, streaming=True)
        self.intake_prompt_template = intake_prompt or load_prompt_template("intake", "intake.md")
        self.extraction_prompt_template = extraction_prompt or load_prompt_template("extract_preferences", "extract_preferences.md")

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
            "specific_requirements",  # accessibility/dietary/constraints
            "preferred_attractions",  # traveler already has these in mind
            "preferred_restaurants",  # traveler has specific restaurants in mind
        ]

        self.all_fields = self.required_fields + self.optional_fields
        self.conversation_history: List[Any] = []  # [SystemMessage/HumanMessage/AIMessage]

    @staticmethod
    def _merge_preference_list(existing: Optional[Any], incoming: Any) -> List[str]:
        """Merge preference lists (attractions/restaurants) with de-duplication."""

        def to_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, list):
                items = value
            elif isinstance(value, str):
                items = [part.strip() for part in value.split(",")]
            else:
                items = [str(value)]
            normalized = []
            for item in items:
                if not isinstance(item, str):
                    item = str(item)
                cleaned = item.strip()
                if cleaned:
                    normalized.append(cleaned)
            return normalized

        combined = []
        seen = set()
        for item in to_list(existing) + to_list(incoming):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            combined.append(item)
        return combined

    # ---------------------------
    # Conversation initialization
    # ---------------------------
    def _init_system_message(self) -> SystemMessage:
        """One concise directive the model will follow for the whole chat."""
        required_bullets = "\n".join(
            f"- {idx + 1}) {field}" for idx, field in enumerate(self.required_fields)
        )
        optional_bullets = "\n".join(f"- {field}" for field in self.optional_fields)
        prompt_text = self.intake_prompt_template.format(
            required_fields_bullets=required_bullets,
            optional_fields_bullets=optional_bullets,
        )
        return SystemMessage(content=prompt_text)

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

        # Handle empty initial greeting (no user input yet)
        has_user_text = user_input and user_input.strip()
        
        if not has_user_text and len(self.conversation_history) == 1:
            # First call with empty input: return greeting without calling LLM
            missing = [f for f in self.required_fields if not state.get(f)]
            greeting = "Hi there! I'm excited to help you plan your trip. To get started, could you tell me your name and where you'd like to go?"
            
            # Create a simple generator that yields the greeting
            def greeting_stream():
                yield type('Chunk', (), {'content': greeting})()
            
            return {
                "stream": greeting_stream(),
                "missing_fields": missing,
                "complete": False,
                "state": state.copy()
            }

        # 1) LLM extraction → structured fields (merge if present)
        if has_user_text:
            new_info = self.extract_info_from_message(user_input, current_state=state)
            for field, value in new_info.items():
                if value in (None, "", []):
                    continue
                if field in {"preferred_attractions", "preferred_restaurants"}:
                    merged = self._merge_preference_list(state.get(field), value)
                    if merged:
                        state[field] = merged
                    else:
                        state.pop(field, None)
                else:
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
        from datetime import datetime
        field_list = "\n".join(f"- \"{f}\"" for f in self.all_fields)
        current_state_json = json.dumps(current_state, ensure_ascii=False, indent=2)
        current_date = datetime.now().strftime("%Y-%m-%d")
        system_prompt = self.extraction_prompt_template.format(
            field_list=field_list,
            current_state=current_state_json,
            current_date=current_date,
            user_message=message,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=message)
        ]

        try:
            llm_response = self.model.invoke(messages)

            # Gemini sometimes returns content with markdown fences or as a list of parts.
            content = llm_response.content
            if isinstance(content, list):
                # Join any text parts conservatively
                parts: List[str] = []
                for p in content:
                    if isinstance(p, dict):
                        txt = p.get("text") or p.get("content") or ""
                        if txt:
                            parts.append(str(txt))
                    else:
                        parts.append(str(p))
                content_str = "\n".join(parts).strip()
            else:
                content_str = str(content).strip()

            def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
                if not text:
                    return None
                # 1) direct
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass
                # 2) fenced block ```json ... ```
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
                if m:
                    try:
                        obj = json.loads(m.group(1))
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                # 3) first {...} slice
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    candidate = text[start:end + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                return None

            data = _try_parse_json(content_str)
            if data is None:
                raise ValueError("LLM did not return valid JSON")

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
            "preferred_attractions": "any must-see attractions you'd like included",
            "preferred_restaurants": "restaurants you'd love to try",
        }

        # Step 8 summary text
        def summary_text(st: Dict[str, Any]) -> str:
            def _get(k, default="(not provided)"): return st.get(k) or default
            kids_str = _get("kids", "no")
            car_str = _get("need_car_rental", "no")
            pref_attractions = st.get("preferred_attractions") or []
            pref_restaurants = st.get("preferred_restaurants") or []
            pref_attr_str = ", ".join(pref_attractions) if pref_attractions else "(none yet)"
            pref_dine_str = ", ".join(pref_restaurants) if pref_restaurants else "(none yet)"
            return (
                "Here’s what I have so far:\n"
                f"- Name: {_get('name')}\n"
                f"- Destination: {_get('destination_city')}\n"
                f"- Travel: {_get('travel_days')} day(s), starting {_get('start_date')}\n"
                f"- Budget: ${_get('budget_usd')}\n"
                f"- Group: {_get('num_people')} traveler(s), kids: {kids_str}\n"
                f"- Activities: {_get('activity_pref')} | Car rental: {car_str}\n"
                f"- Hotel room: {_get('hotel_room_pref')}\n"
                f"- Cuisine: {_get('cuisine_pref')}\n"
                f"- Preferred attractions: {pref_attr_str}\n"
                f"- Preferred restaurants: {pref_dine_str}\n\n"
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
