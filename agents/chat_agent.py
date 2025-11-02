import json
import os
import re
from typing import Any, Dict, Generator, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from prompts import PromptTemplate, load_prompt_template

if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("Missing GOOGLE_API_KEY. Run: export GOOGLE_API_KEY='your_key_here'")

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
            "specific_requirements"  # accessibility/dietary/constraints
        ]

        self.all_fields = self.required_fields + self.optional_fields
        self.conversation_history: List[Any] = []  # [SystemMessage/HumanMessage/AIMessage]

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
        field_list = "\n".join(f"- \"{f}\"" for f in self.all_fields)
        current_state_json = json.dumps(current_state, ensure_ascii=False, indent=2)
        system_prompt = self.extraction_prompt_template.format(
            field_list=field_list,
            current_state=current_state_json,
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

# A mini test to see if chat agent works as expected
if __name__ == "__main__":
    """
    Terminal REPL for ChatAgent.
    Commands:
      /state      -> print current state JSON
      /missing    -> print missing required fields
      /reset      -> clear state and conversation
      /save PATH  -> save state to a file (JSON)
      /load PATH  -> load state from a file (JSON)
      /help       -> show commands
      /quit       -> exit
    """
    import json
    import pathlib
    import sys

    # 1) init the agent (uses your default gemini model)
    agent = ChatAgent()
    state: Dict[str, Any] = {}

    print("🔹 ChatAgent REPL (Gemini). Type /help for commands. Ctrl+C to exit.")
    while True:
        try:
            user = input("\nYou: ").strip()

            # --- commands ---
            if not user:
                continue
            if user == "/quit":
                print("Bye! 👋")
                sys.exit(0)
            if user == "/help":
                print(
                    "Commands:\n"
                    "  /state         show current state\n"
                    "  /missing       show missing required fields\n"
                    "  /reset         clear state & conversation\n"
                    "  /save PATH     save state to PATH (json)\n"
                    "  /load PATH     load state from PATH (json)\n"
                    "  /quit          exit"
                )
                continue
            if user == "/state":
                print(json.dumps(state, indent=2, ensure_ascii=False))
                continue
            if user == "/missing":
                missing = [f for f in agent.required_fields if not state.get(f)]
                print("Missing:", ", ".join(missing) if missing else "(none)")
                continue
            if user == "/reset":
                state = {}
                agent.conversation_history.clear()
                print("Reset OK.")
                continue
            if user.startswith("/save "):
                path = pathlib.Path(user.split(" ", 1)[1].strip())
                path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                print(f"Saved -> {path}")
                continue
            if user.startswith("/load "):
                path = pathlib.Path(user.split(" ", 1)[1].strip())
                state = json.loads(path.read_text())
                print(f"Loaded <- {path}")
                continue
            # Optional: auto-complete exit if user confirms and all fields are present
            if user.lower() in {"confirm", "yes", "y"}:
                missing = [f for f in agent.required_fields if not state.get(f)]
                if not missing:
                    print("Confirmed. Final state:")
                    print(json.dumps(state, indent=2, ensure_ascii=False))
                    print("Bye! 👋")
                    sys.exit(0)

            # 2) normal chat turn -> collect info
            out = agent.collect_info(user, state=state)
            state = out["state"]  # update local state

            # 3) stream assistant reply
            stream = out["stream"]
            print("Assistant:", end=" ", flush=True)
            if stream is not None:
                for chunk in stream:
                    # langchain streaming returns message chunks with `.content`
                    piece = getattr(chunk, "content", None)
                    if piece:
                        print(piece, end="", flush=True)
            print()  # newline

            # 4) show completion hint
            if out["complete"]:
                print("✅ All required fields collected. Type 'confirm' to finish, or /state to review.")

        except KeyboardInterrupt:
            print("\nInterrupted. Type /quit to exit.")
        except Exception as e:
            print(f"\n[error] {e}")
