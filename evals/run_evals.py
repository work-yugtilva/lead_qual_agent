#!/usr/bin/env python3
"""
Local eval harness for the lead qualification agent.

Runs entirely offline: no Anthropic key, no Salesforce credentials, no
network. Each case in lead_qualification_cases.json feeds one lead row
through the real scoring + hygiene pipeline and checks:

  - expected_label                exact match on qualification_label
  - expected_action (optional)    exact match on recommended_action
  - expected_tier (optional)      exact match on the Hot/Warm/Cold tier
  - expected_score_min/max        inclusive bounds on the legacy 0-100 score
  - expected_needs_human_review   exact match
  - must_include_reasons          case-insensitive substrings of the joined reasons
  - must_include_risk_flags       exact flag-code membership
  - must_not_include              case-insensitive substrings that must NOT appear
                                  in reasons, flags, label, or action
  - expected_duplicate_ids (opt)  find_duplicates over input + other_rows

Exit status is nonzero if any case fails, so this can gate CI.
"""

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from scoring import score_lead          # noqa: E402
from hygiene import find_duplicates     # noqa: E402

CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lead_qualification_cases.json")


def check_case(case: dict) -> list[str]:
    """Returns a list of failure descriptions; empty list means the case passed."""
    failures = []
    result = score_lead(case["input"])

    joined_reasons = " | ".join(result.reasons)
    haystack = " | ".join(
        result.reasons
        + list(result.risk_flags)
        + [result.qualification_label, result.recommended_action]
    ).lower()

    if result.qualification_label != case["expected_label"]:
        failures.append(f"label: expected {case['expected_label']!r}, got {result.qualification_label!r}")

    expected_tier = case.get("expected_tier")
    if expected_tier and result.tier != expected_tier:
        failures.append(f"tier: expected {expected_tier!r}, got {result.tier!r}")

    expected_action = case.get("expected_action")
    if expected_action and result.recommended_action != expected_action:
        failures.append(f"action: expected {expected_action!r}, got {result.recommended_action!r}")

    lo, hi = case["expected_score_min"], case["expected_score_max"]
    if not lo <= result.score <= hi:
        failures.append(f"score: expected {lo}..{hi}, got {result.score}")

    if result.needs_human_review != case["expected_needs_human_review"]:
        failures.append(
            f"needs_human_review: expected {case['expected_needs_human_review']}, "
            f"got {result.needs_human_review}"
        )

    for needle in case.get("must_include_reasons", []):
        if needle.lower() not in joined_reasons.lower():
            failures.append(f"missing reason substring: {needle!r}")

    for flag in case.get("must_include_risk_flags", []):
        if flag not in result.risk_flags:
            failures.append(f"missing risk flag: {flag!r} (got {result.risk_flags})")

    for needle in case.get("must_not_include", []):
        if needle.lower() in haystack:
            failures.append(f"forbidden text present: {needle!r}")

    if "other_rows" in case:
        dupes = find_duplicates([case["input"], *case["other_rows"]])
        for lead_id, expected_ids in case.get("expected_duplicate_ids", {}).items():
            got = dupes.get(lead_id, [])
            if got != sorted(expected_ids):
                failures.append(f"duplicates for {lead_id}: expected {sorted(expected_ids)}, got {got}")

    return failures


def run_all() -> list[tuple[dict, list[str]]]:
    """Run every case. Returns [(case, failures), ...] for programmatic use (pytest)."""
    with open(CASES_PATH) as f:
        cases = json.load(f)
    return [(case, check_case(case)) for case in cases]


def main() -> None:
    outcomes = run_all()
    passed = 0
    for case, failures in outcomes:
        if failures:
            print(f"FAIL  {case['case_id']}  {case['name']}")
            for failure in failures:
                print(f"        - {failure}")
        else:
            passed += 1
            print(f"PASS  {case['case_id']}  {case['name']}")

    total = len(outcomes)
    print(f"\n{passed}/{total} eval cases passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
