#!/usr/bin/env python3
"""
evaluation/evaluate_plan_llm.py

Use Gemini (LLM-as-judge) to evaluate a travel plan on *subjective* aspects
that are not covered by rule-based validation, then combine this score with
the existing validation score to get a comprehensive evaluation.

Usage example:

    python evaluation/evaluate_plan_llm.py \
        --profile user_profile/user_profile_abc123.json \
        --itinerary itinerary_abc123.json \
        --budget budget_abc123.json \
        --validation results/validation_result_abc123.json
"""

import argparse
import json
import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai


# ----------------- Helpers -----------------


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_profile_fields(profile_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle both:
    {
      "Traveler Profile": { ... }
    }
    and:
    {
      "name": "...",
      "destination_city": "...",
      ...
    }
    """
    if "Traveler Profile" in profile_json and isinstance(
        profile_json["Traveler Profile"], dict
    ):
        return profile_json["Traveler Profile"]
    return profile_json


def get_thread_id_from_profile(
    profile_fields: Dict[str, Any], profile_path: str
) -> str:
    # Try explicit fields first, then fall back to filename
    thread_id = (
        profile_fields.get("Thread ID")
        or profile_fields.get("thread_id")
        or os.path.basename(profile_path)
        .replace("user_profile_", "")
        .replace(".json", "")
    )
    return str(thread_id)


def configure_gemini():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is not set.")
    genai.configure(api_key=api_key)
    # You can switch to "gemini-1.5-pro" if you want heavier judging
    return genai.GenerativeModel("gemini-2.0-flash-exp")


# ----------------- LLM-as-judge prompt -----------------


def build_llm_judge_prompt(
    profile_fields: Dict[str, Any],
    itinerary_json: Dict[str, Any],
    budget_json: Optional[
        Dict[str, Any]
    ] = None,  # you can drop this param later if you fully remove budget
) -> str:
    """
    Build a prompt asking Gemini to judge the plan on high-level / subjective criteria.
    We explicitly say: ignore low-level consistency checks because those are handled by
    the rule-based validator.
    """
    profile_str = json.dumps(profile_fields, indent=2, ensure_ascii=False)
    itinerary_str = json.dumps(itinerary_json, indent=2, ensure_ascii=False)

    prompt = (
        "You are an expert travel planning evaluator.\n\n"
        "You are given:\n"
        "1. A traveler profile (preferences, constraints).\n"
        "2. A generated travel itinerary.\n\n"
        "A separate rule-based system already checks things like:\n"
        "- date alignment\n"
        "- number of days vs itinerary span\n"
        "- rough budget vs cost\n"
        "- simple contradictions such as 'needs car vs no car in itinerary'\n\n"
        "Your job is to evaluate ONLY higher-level, subjective aspects that are NOT\n"
        "captured by such simple validation, for example:\n"
        "- How well the activities match the traveler's stated interests.\n"
        "- Variety and richness of activities.\n"
        "- Coherence and logical structure of the days.\n"
        "- Reasonable pacing.\n"
        "- Alignment with soft preferences like cuisine and neighborhoods.\n"
        "- Overall attractiveness and likely user satisfaction.\n\n"
        "IMPORTANT:\n"
        "- Ignore low-level issues such as exact date formats or minor budget mismatches.\n"
        "- Focus on human-level quality and preference fit.\n\n"
        "You MUST output a single JSON object with the following fields:\n"
        "- llm_score: number from 0 to 100 (higher is better)\n"
        "- sub_scores: an object with keys:\n"
        "    - preference_alignment (0–100)\n"
        "    - variety_and_richness (0–100)\n"
        "    - pacing_and_structure (0–100)\n"
        "    - overall_appeal (0–100)\n"
        "- strengths: list of 2–5 short sentences\n"
        "- weaknesses: list of 2–5 short sentences\n"
        "- comment: a short paragraph (2–4 sentences) summarizing your judgment\n\n"
        "Do NOT include any extra commentary outside of the JSON.\n\n"
        "----------------------\n"
        "TRAVELER PROFILE:\n"
        f"{profile_str}\n\n"
        "----------------------\n"
        "ITINERARY JSON:\n"
        f"{itinerary_str}\n"
    )

    return prompt


def call_llm_judge(
    model,
    profile_fields: Dict[str, Any],
    itinerary_json: Dict[str, Any],
    budget_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Call Gemini with our judging prompt and parse JSON response."""
    prompt = build_llm_judge_prompt(profile_fields, itinerary_json, budget_json)
    response = model.generate_content(prompt)
    text = response.text.strip()

    # Try to parse as JSON directly
    try:
        data = json.loads(text)
        return data
    except Exception:
        # Fallback: try to extract JSON block if the model wrapped it in text (shouldn't happen if instructions followed)
        try:
            start = text.index("{")
            end = text.rfind("}") + 1
            json_str = text[start:end]
            data = json.loads(json_str)
            return data
        except Exception as e:
            raise RuntimeError(
                f"Failed to parse LLM response as JSON: {e}\nRaw response:\n{text}"
            )


# ----------------- Combining with validation -----------------


def combine_scores(validation_score: float, llm_score: float) -> float:
    """
    Combine rule-based validation score and LLM-as-judge score.

    You can tune these weights. For now:
      - 0.6 * validation (objective consistency)
      - 0.4 * llm_score (subjective quality)
    """
    W_VALIDATION = 0.6
    W_LLM = 0.4
    combined = W_VALIDATION * validation_score + W_LLM * llm_score
    # Clamp to [0, 100]
    if combined < 0:
        combined = 0.0
    if combined > 100:
        combined = 100.0
    return round(combined, 1)


def save_llm_and_combined_results(
    thread_id: str,
    profile_fields: Dict[str, Any],
    itinerary_json: Dict[str, Any],
    budget_json: Optional[Dict[str, Any]],
    validation_result: Optional[Dict[str, Any]],
    llm_result: Dict[str, Any],
    combined_score: float,
):
    os.makedirs("results", exist_ok=True)

    # Save LLM-only judgment
    llm_path = os.path.join("results", f"llm_judge_{thread_id}.json")
    with open(llm_path, "w", encoding="utf-8") as f:
        json.dump(llm_result, f, indent=2, ensure_ascii=False)
    print(f"\n💾 LLM judgment saved to: {llm_path}")

    # Build combined result
    validation_score = validation_result.get("score") if validation_result else None
    validation_issues = validation_result.get("issues") if validation_result else None
    num_validation_issues = (
        validation_result.get("num_issues") if validation_result else None
    )

    combined = {
        "thread_id": thread_id,
        "validation_score": validation_score,
        "validation_num_issues": num_validation_issues,
        "validation_issues": validation_issues,
        "llm_score": llm_result.get("llm_score"),
        "llm_sub_scores": llm_result.get("sub_scores"),
        "llm_strengths": llm_result.get("strengths"),
        "llm_weaknesses": llm_result.get("weaknesses"),
        "llm_comment": llm_result.get("comment"),
        "combined_score": combined_score,
        "weights": {
            "validation": 0.6,
            "llm": 0.4,
        },
        "profile_summary": profile_fields,
        "itinerary_keys": list(itinerary_json.keys()) if itinerary_json else [],
        "budget_keys": list(budget_json.keys()) if budget_json else [],
    }

    combined_path = os.path.join("results", f"combined_evaluation_{thread_id}.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    print(f"💾 Combined evaluation saved to: {combined_path}\n")


# ----------------- main() -----------------


def main():
    parser = argparse.ArgumentParser(
        description="LLM-as-judge evaluation for travel plans, and combination with rule-based validation."
    )
    parser.add_argument(
        "--profile", required=True, help="Path to user profile JSON file"
    )
    parser.add_argument(
        "--itinerary", required=True, help="Path to itinerary JSON file"
    )
    parser.add_argument(
        "--budget", required=False, help="Path to budget JSON file (optional)"
    )
    parser.add_argument(
        "--validation",
        required=False,
        help="Path to validation_result_<thread_id>.json (optional but recommended)",
    )
    args = parser.parse_args()

    profile_json = load_json(args.profile)
    itinerary_json = load_json(args.itinerary)
    budget_json = load_json(args.budget) if args.budget else None
    validation_json = load_json(args.validation) if args.validation else None

    profile_fields = extract_profile_fields(profile_json)
    thread_id = get_thread_id_from_profile(profile_fields, args.profile)

    print("=== LLM-as-Judge Evaluation ===")
    print(f"Thread ID: {thread_id}")
    if validation_json:
        print(f"Found validation result with score: {validation_json.get('score')}")

    # Configure Gemini
    model = configure_gemini()

    # Call LLM-as-judge
    llm_result = call_llm_judge(model, profile_fields, itinerary_json, budget_json)

    llm_score = float(llm_result.get("llm_score", 0.0))
    validation_score = (
        float(validation_json.get("score"))
        if validation_json and validation_json.get("score") is not None
        else None
    )

    print("\n=== LLM Result ===")
    print(json.dumps(llm_result, indent=2, ensure_ascii=False))

    # Combine scores (if validation score is provided)
    if validation_score is not None:
        combined_score = combine_scores(validation_score, llm_score)
    else:
        combined_score = round(
            llm_score, 1
        )  # fallback: if no validation, just use LLM score

    print(f"\nCombined Score: {combined_score} / 100")

    # Save outputs
    save_llm_and_combined_results(
        thread_id=thread_id,
        profile_fields=profile_fields,
        itinerary_json=itinerary_json,
        budget_json=budget_json,
        validation_result=validation_json,
        llm_result=llm_result,
        combined_score=combined_score,
    )


if __name__ == "__main__":
    main()
