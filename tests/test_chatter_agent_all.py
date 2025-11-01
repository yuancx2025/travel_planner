# tests/test_chatter_agent_all.py
import json
import types
import importlib
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- CHANGE THIS to your actual module path ---
MODULE_IMPORT = "agents.chat_agent"   

# -----------------------
# Fake LLM for unit tests
# -----------------------
class FakeStream:
    """Iterable that mimics a streaming response."""
    def __iter__(self):
        yield types.SimpleNamespace(content="(fake streamed assistant reply chunk 1) ")
        yield types.SimpleNamespace(content="(fake streamed assistant reply chunk 2)")

class FakeModel:
    """
    Fakes a LangChain chat model with:
      - .invoke(messages) -> returns an object with .content JSON
      - .stream(messages) -> returns an iterable of chunks with .content
    You can pre-seed a queue of extraction payloads to simulate multi-turn updates.
    """
    def __init__(self, queue=None):
        # queue: list of dicts; each dict becomes the JSON content for one .invoke() call
        self.queue = list(queue) if queue else []

    def invoke(self, messages):
        if self.queue:
            payload = self.queue.pop(0)
        else:
            # default empty payload (no updates)
            payload = {}
        # Ensure payload has string JSON
        return types.SimpleNamespace(content=json.dumps(payload))

    def stream(self, messages):
        return FakeStream()


# -----------------------
# Fixtures
# -----------------------
@pytest.fixture
def ChatAgentClass():
    mod = importlib.import_module(MODULE_IMPORT)
    return getattr(mod, "ChatAgent")


@pytest.fixture
def empty_agent(ChatAgentClass):
    # Pass FakeModel directly during initialization to avoid Google API calls
    fake_model = FakeModel(queue=[])
    agent = ChatAgentClass(model=fake_model)
    return agent


# -----------------------
# Tests
# -----------------------

def test_initial_required_fields_and_missing_list(empty_agent):
    agent = empty_agent
    state = {}
    out = agent.collect_info("hello", state=state)

    # The agent should return missing fields list for all required ones (since extractor returned nothing)
    missing = out["missing_fields"]
    # Expected keys match your ChatAgent.required_fields contract
    for k in [
        "name", "destination_city", "travel_days", "start_date",
        "budget_usd", "num_people", "kids",
        "activity_pref", "need_car_rental", "hotel_room_pref", "cuisine_pref"
    ]:
        assert k in missing
    assert out["complete"] is False
    assert out["stream"] is not None


def test_extraction_merges_only_non_empty_values(empty_agent):
    agent = empty_agent
    # Prime the model with a single extraction payload:
    agent.model = FakeModel(queue=[{
        "name": "Michael",
        "destination_city": "",        # empty must not overwrite later
        "travel_days": 3,
        "start_date": "2025-11-03",
        "budget_usd": 1000,
        "num_people": 2,
        "kids": "no",
        "activity_pref": "outdoor",
        "need_car_rental": "no",
        "hotel_room_pref": "",
        "cuisine_pref": "ramen",
        "origin_city": "Raleigh",
        "home_airport": "RDU",
        "specific_requirements": ""
    }])

    state = {"destination_city": "San Francisco"}  # pre-existing value should survive
    out = agent.collect_info("We plan a 3-day SF trip starting Nov 3", state=state)

    s = out["state"]
    assert s["name"] == "Michael"
    assert s["destination_city"] == "San Francisco"   # not overwritten by empty string
    assert s["travel_days"] == 3
    assert s["start_date"] == "2025-11-03"
    assert s["budget_usd"] == 1000
    assert s["num_people"] == 2
    assert s["kids"] == "no"
    assert s["activity_pref"] == "outdoor"
    assert s["need_car_rental"] == "no"
    assert s["cuisine_pref"] == "ramen"
    # optional fields captured if present
    assert s["origin_city"] == "Raleigh"
    assert s["home_airport"] == "RDU"
    # still missing: hotel_room_pref (extractor gave "")
    assert "hotel_room_pref" in out["missing_fields"]


def test_streaming_chunks_present(empty_agent):
    agent = empty_agent
    # No need to seed extraction; we just want to test streaming object
    out = agent.collect_info("hi", state={})

    chunks = []
    for chunk in out["stream"]:
        chunks.append(getattr(chunk, "content", ""))

    assert any("fake streamed" in c for c in chunks)


def test_multi_turn_accumulation(empty_agent):
    agent = empty_agent

    # Turn 1: only provides name
    agent.model = FakeModel(queue=[{
        "name": "Alex",
        "destination_city": "",
        "travel_days": "",
        "start_date": "",
        "budget_usd": "",
        "num_people": "",
        "kids": "",
        "activity_pref": "",
        "need_car_rental": "",
        "hotel_room_pref": "",
        "cuisine_pref": ""
    }])
    state = {}
    out1 = agent.collect_info("Hi, I'm Alex.", state=state)
    s1 = out1["state"]
    assert s1["name"] == "Alex"
    assert "destination_city" in out1["missing_fields"]

    # Turn 2: user gives destination and budget, still missing others
    agent.model = FakeModel(queue=[{
        "destination_city": "San Francisco",
        "budget_usd": 900
    }])
    out2 = agent.collect_info("Thinking about San Francisco; budget under $900.", state=s1)
    s2 = out2["state"]
    assert s2["name"] == "Alex"                  # preserved
    assert s2["destination_city"] == "San Francisco"
    assert s2["budget_usd"] == 900
    assert "travel_days" in out2["missing_fields"]
    assert out2["complete"] is False

    # Turn 3: provide the rest; allow "not decided" for the date
    agent.model = FakeModel(queue=[{
        "travel_days": 3,
        "start_date": "not decided",
        "num_people": 2,
        "kids": "no",
        "activity_pref": "outdoor",
        "need_car_rental": "no",
        "hotel_room_pref": "1 king",
        "cuisine_pref": "seafood"
    }])
    out3 = agent.collect_info("3 days, not sure on exact date yet; two adults, no kids; outdoor, no car; 1 king; seafood.", state=s2)
    s3 = out3["state"]
    assert s3["travel_days"] == 3
    assert s3["start_date"] == "not decided"     # permitted by design
    assert s3["num_people"] == 2
    assert s3["kids"] == "no"
    assert s3["activity_pref"] == "outdoor"
    assert s3["need_car_rental"] == "no"
    assert s3["hotel_room_pref"] == "1 king"
    assert s3["cuisine_pref"] == "seafood"
    # Now everything should be complete
    assert out3["complete"] is True
    assert out3["missing_fields"] == []


def test_all_fields_complete_in_one_go(empty_agent):
    agent = empty_agent
    agent.model = FakeModel(queue=[{
        "name": "Jordan",
        "destination_city": "Washington, DC",
        "travel_days": 2,
        "start_date": "2025-12-20",
        "budget_usd": 1200,
        "num_people": 3,
        "kids": "1",
        "activity_pref": "indoor",
        "need_car_rental": "yes",
        "hotel_room_pref": "2 queens",
        "cuisine_pref": "kid-friendly",
        # optional:
        "origin_city": "Boston",
        "home_airport": "BOS",
        "specific_requirements": "stroller access"
    }])

    out = agent.collect_info("Here is the full plan.", state={})
    s = out["state"]

    # Requireds
    assert s["name"] == "Jordan"
    assert s["destination_city"] == "Washington, DC"
    assert s["travel_days"] == 2
    assert s["start_date"] == "2025-12-20"
    assert s["budget_usd"] == 1200
    assert s["num_people"] == 3
    assert s["kids"] == "1"
    assert s["activity_pref"] == "indoor"
    assert s["need_car_rental"] == "yes"
    assert s["hotel_room_pref"] == "2 queens"
    assert s["cuisine_pref"] == "kid-friendly"

    # Optionals
    assert s["origin_city"] == "Boston"
    assert s["home_airport"] == "BOS"
    assert s["specific_requirements"] == "stroller access"

    assert out["complete"] is True
    assert out["missing_fields"] == []


def test_conversation_history_grows(empty_agent):
    agent = empty_agent

    # Prime with two small turns
    agent.model = FakeModel(queue=[{"name": "Sam"}])
    state = {}
    out1 = agent.collect_info("I'm Sam", state=state)
    # Next: add destination
    agent.model = FakeModel(queue=[{"destination_city": "Denver"}])
    agent.collect_info("Going to Denver", state=out1["state"])

    # The conversation history should contain at least:
    # [system_init, human_turn1, human_turn2]
    # (assistant responses are streamed but not stored in history)
    assert len(agent.conversation_history) >= 3


def test_interact_with_user_stream_returns_generator(empty_agent):
    agent = empty_agent
    # interact_with_user should produce a stream generator without touching state
    stream = agent.interact_with_user("Tell me more about the process.")
    chunks = [getattr(c, "content", "") for c in stream]
    assert any("fake streamed" in c for c in chunks)
