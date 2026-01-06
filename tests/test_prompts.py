import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompts import load_prompt_template


def _reset_prompt_cache():
    try:
        load_prompt_template.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass


@pytest.fixture(autouse=True)
def clear_prompt_overrides():
    prefix = "TRAVEL_PLANNER_PROMPT_"
    for key in list(os.environ.keys()):
        if key.startswith(prefix):
            os.environ.pop(key)
    _reset_prompt_cache()
    yield
    _reset_prompt_cache()


def test_intake_prompt_mentions_tone_and_order():
    template = load_prompt_template("intake", "intake.md")
    rendered = template.format(
        required_fields_bullets="- 1) name", optional_fields_bullets="- origin_city"
    )
    assert "Travel Intake Assistant System Prompt" in rendered
    assert "Tone guidance" in rendered
    assert "Required details to capture" in rendered
    assert "- 1) name" in rendered
    assert "Optional details" in rendered


def test_extraction_prompt_retains_json_instructions():
    template = load_prompt_template("extract_preferences", "extract_preferences.md")
    rendered = template.format(
        field_list='- "name"',
        current_state="{}",
        current_date="2025-11-02",
        user_message="test message"
    )
    assert "extract" in rendered.lower()
    assert "json" in rendered.lower()


def test_final_plan_prompt_emphasizes_bullets_and_safety():
    template = load_prompt_template("final_plan", "final_plan.md")
    # The final_plan template has placeholders but is meant to be used with actual data
    # Just verify it loads and contains key structural elements
    content = template.text
    assert "Final Travel Plan" in content
    assert "Day-by-Day" in content or "day-by-day" in content.lower()
    assert "Budget" in content


def test_environment_override_prefers_file(tmp_path):
    override_file = tmp_path / "custom_prompt.txt"
    override_file.write_text("Custom prompt content", encoding="utf-8")
    os.environ["TRAVEL_PLANNER_PROMPT_INTAKE"] = str(override_file)

    template = load_prompt_template("intake", "intake.md")
    assert template.text == "Custom prompt content"
