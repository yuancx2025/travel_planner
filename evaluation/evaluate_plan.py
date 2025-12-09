#!/usr/bin/env python3
"""
evaluation/evaluate_plan.py

Evaluate whether a generated itinerary is consistent with a saved user profile
and compute a numeric score for the plan.

Usage:
    python evaluation/evaluate_plan.py \
        --profile user_profiles/user_profile_abc123.json \
        --itinerary generated_plans/itinerary_abc123.json \
"""

import argparse
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
import os


# ---------- Helpers ----------


def save_evaluation_result(
    thread_id: str, profile_fields, itinerary_json, budget_json, issues, score, label
):
    """Save evaluation results into results/validation_result_<thread_id>.json."""
    os.makedirs("results", exist_ok=True)

    result = {
        "thread_id": thread_id,
        "score": score,
        "interpretation": label,
        "num_issues": len(issues),
        "issues": issues,
        "profile_summary": profile_fields,
        "itinerary_keys": list(itinerary_json.keys()) if itinerary_json else [],
        "budget_keys": list(budget_json.keys()) if budget_json else [],
    }

    filename = os.path.join("results", f"validation_result_{thread_id}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Evaluation saved to: {filename}\n")


def normalize_value(v: Any) -> Optional[str]:
    """Turn common incoming types into a simple string (or None)."""
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, (str, int, float)):
            return str(first).strip()
        return str(first)
    try:
        return str(v).strip()
    except Exception:
        return None


def safe_lower(v: Any) -> str:
    s = normalize_value(v)
    return s.lower() if isinstance(s, str) else ""


def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s_norm = normalize_value(s)
    if not s_norm:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s_norm, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s_norm)
    except Exception:
        try:
            return datetime.strptime(s_norm[:10], "%Y-%m-%d")
        except Exception:
            return None


# ---------- Core validation ----------


def validate_plan(
    profile_fields: Dict[str, Any],
    itinerary: Optional[Dict[str, Any]],
    budget_summary: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Run a set of heuristic checks to see if the itinerary contradicts the profile.
    Return a list of human-readable issues (empty list == no issues).
    """
    issues: List[str] = []

    if not profile_fields:
        issues.append("No user profile available to validate against.")
        return issues

    # Flatten / normalize profile
    normalized = {k: normalize_value(v) for k, v in profile_fields.items()}

    # --- Check 1: Start date vs itinerary first day ---
    profile_start = parse_date(
        normalized.get("start_date") or normalized.get("Start Date")
    )
    itinerary_dates: List[datetime] = []

    if itinerary:
        days = (
            itinerary.get("days")
            or itinerary.get("itinerary")
            or itinerary.get("schedule")
            or []
        )
        if isinstance(days, dict):
            days = [days]
        for d in days:
            if isinstance(d, dict):
                date_str = normalize_value(
                    d.get("date") or d.get("day_date") or d.get("day")
                )
                dt = parse_date(date_str)
                if dt:
                    itinerary_dates.append(dt)

    if profile_start and itinerary_dates:
        first_itin = min(itinerary_dates)
        if abs((first_itin.date() - profile_start.date()).days) > 1:
            issues.append(
                f"Profile start date ({profile_start.date()}) does not match "
                f"itinerary first day ({first_itin.date()})."
            )

    # --- Check 2: Travel days vs itinerary span ---
    try:
        profile_days = int(
            normalized.get("travel_days") or normalized.get("Travel Days") or 0
        )
    except Exception:
        profile_days = 0

    if profile_days and itinerary_dates:
        itin_span_days = (
            max(itinerary_dates).date() - min(itinerary_dates).date()
        ).days + 1
        if profile_days != itin_span_days:
            issues.append(
                f"Profile travel days ({profile_days}) ≠ itinerary span ({itin_span_days})."
            )

    # --- Check 3: Budget vs estimated cost ---
    try:
        profile_budget = float(
            normalized.get("budget_usd")
            or normalized.get("Budget Usd")
            or normalized.get("budget")
            or 0
        )
    except Exception:
        profile_budget = 0.0

    if profile_budget and budget_summary:
        total = None
        for k in ("total", "total_cost", "estimated_total", "total_usd", "amount"):
            if budget_summary.get(k) is not None:
                try:
                    val = budget_summary.get(k)
                    if isinstance(val, list) and val:
                        val = val[0]
                    total = float(val)
                    break
                except Exception:
                    continue
        if total is not None and total > 0 and profile_budget > 0:
            if total > profile_budget * 1.05:  # allow 5% slack
                issues.append(
                    f"Estimated trip cost ({total}) exceeds profile budget ({profile_budget})."
                )

    # --- Check 4: Car rental preference vs itinerary content ---
    need_car = safe_lower(
        normalized.get("need_car_rental") or normalized.get("Need Car Rental")
    )
    if need_car in ("yes", "true", "1", "y"):
        transport_used = False
        if itinerary:
            try:
                raw = json.dumps(itinerary).lower()
                if any(
                    token in raw
                    for token in (
                        "car",
                        "drive",
                        "rental",
                        "pickup",
                        "rent a car",
                        "rent-car",
                    )
                ):
                    transport_used = True
            except Exception:
                transport_used = False
        if not transport_used:
            issues.append(
                "Profile requests a car rental but the itinerary contains no car/drive segments."
            )

    # --- Check 5: Kids vs nightlife-heavy plan (very heuristic) ---
    kids = safe_lower(normalized.get("kids") or normalized.get("Kids"))
    if kids in ("yes", "true", "1", "y"):
        if itinerary:
            try:
                raw = json.dumps(itinerary).lower()
                if ("nightclub" in raw or "bar" in raw) and not any(
                    k in raw for k in ("park", "museum", "family", "children", "zoo")
                ):
                    issues.append(
                        "Profile indicates children but itinerary seems focused on adult nightlife or lacks family-friendly activities."
                    )
            except Exception:
                pass

    # --- Check 6: Hotel room preference vs lodging text (soft check) ---
    room_pref = normalize_value(
        normalized.get("hotel_room_pref") or normalized.get("Hotel Room Pref")
    )
    if room_pref and itinerary:
        try:
            raw = json.dumps(itinerary).lower()
            if any(
                t in room_pref.lower()
                for t in ("king", "queen", "twin", "double", "single")
            ):
                if room_pref.lower() not in raw:
                    issues.append(
                        f"Hotel room preference '{room_pref}' not mentioned in itinerary lodging details (verify hotel booking)."
                    )
        except Exception:
            pass

    return issues


# ---------- CLI / Scoring ----------


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


def compute_score(num_issues: int) -> int:
    """
    Compute an overall plan score (0–100) based on number of issues.
    Simple rule: start at 1.0, subtract 0.15 per issue, clamp to [0, 1],
    then convert to 0–100.
    """
    PENALTY_PER_ISSUE = 0.15
    score = 1.0 - PENALTY_PER_ISSUE * num_issues
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return int(round(score * 100))


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate consistency between user profile and itinerary."
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
    args = parser.parse_args()

    profile_json = load_json(args.profile)

    itinerary_json = load_json(args.itinerary)
    budget_json = load_json(args.budget) if args.budget else None

    profile_fields = extract_profile_fields(profile_json)

    print("=== Profile Summary ===")
    for k, v in profile_fields.items():
        print(f"- {k}: {v}")

    print("\n=== Itinerary Summary (top-level keys) ===")
    print(f"Keys: {list(itinerary_json.keys())}")

    if budget_json:
        print("\n=== Budget Summary (top-level keys) ===")
        print(f"Keys: {list(budget_json.keys())}")

    issues = validate_plan(profile_fields, itinerary_json, budget_json)

    # Try to extract thread ID from profile (fallback to filename)
    thread_id = (
        profile_fields.get("Thread ID")
        or profile_fields.get("thread_id")
        or os.path.basename(args.profile)
        .replace("user_profile_", "")
        .replace(".json", "")
    )

    print("\n=== Validation Result ===")
    if not issues:
        print("✅ No contradictions found between profile and itinerary.")
    else:
        print("⚠️ Potential issues detected:")
        for i, issue in enumerate(issues, start=1):
            print(f"{i}. {issue}")

    # ---- Score ----
    score = compute_score(len(issues))
    print("\n=== Plan Score ===")
    print(f"Score: {score} / 100")

    # Optional: print a qualitative label
    if score >= 90:
        label = "Excellent alignment"
    elif score >= 75:
        label = "Good alignment"
    elif score >= 60:
        label = "Partial alignment"
    elif score >= 40:
        label = "Weak alignment"
    else:
        label = "Poor alignment"

    print(f"Interpretation: {label}")

    save_evaluation_result(
        thread_id=thread_id,
        profile_fields=profile_fields,
        itinerary_json=itinerary_json,
        budget_json=budget_json,
        issues=issues,
        score=score,
        label=label,
    )


if __name__ == "__main__":
    main()
