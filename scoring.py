"""
Lead scoring engine — deterministic, rules-based (not ML).
No historical conversion data exists to train a model, so every point
awarded is traceable to a named rule. This is intentional: it mirrors
how most real SDR scoring setups work before enough data exists to
justify a predictive model, and it's fully defensible in an interview.

Score is out of 100, split across four weighted factors:
  - Industry fit          (20 pts)
  - Company size fit       (20 pts)
  - Lead source quality     (20 pts)
  - Behavioral engagement + recency (40 pts)

Tier mapping matches Salesforce's native Lead.Rating picklist
(Hot / Warm / Cold) so the score can be written straight back to
that field once this is wired to a real org.
"""

from dataclasses import dataclass, field

# ---- Ideal Customer Profile (ICP) — confirmed targeting values (2026-07) ----
ICP_INDUSTRIES = {"Technology", "Financial Services"}
ICP_ADJACENT_INDUSTRIES = {"Healthcare", "Retail"}

ICP_EMPLOYEE_RANGE = (100, 1500)       # sweet spot
ICP_EMPLOYEE_ADJACENT = (50, 3000)     # acceptable but not ideal

SOURCE_SCORES = {
    "Referral": 20,
    "Demo Request": 18,
    "Content Download": 12,
    "Web": 6,
    "Cold List": 0,
}


@dataclass
class ScoreResult:
    lead_id: str
    score: int
    tier: str          # Hot / Warm / Cold — maps to Lead.Rating
    reasons: list = field(default_factory=list)


def _score_industry(industry: str) -> tuple[int, str]:
    if not industry:
        return 0, "✗ Industry unknown — cannot confirm ICP fit"
    if industry in ICP_INDUSTRIES:
        return 20, f"✓ ICP industry match ({industry})"
    if industry in ICP_ADJACENT_INDUSTRIES:
        return 10, f"~ Adjacent industry ({industry})"
    return 0, f"✗ Industry outside target market ({industry})"


def _score_company_size(employees) -> tuple[int, str]:
    if employees in (None, "", 0):
        return 0, "✗ Employee count unknown"
    employees = int(employees)
    lo, hi = ICP_EMPLOYEE_RANGE
    alo, ahi = ICP_EMPLOYEE_ADJACENT
    if lo <= employees <= hi:
        return 20, f"✓ Company size in target range ({employees} employees)"
    if alo <= employees <= ahi:
        return 10, f"~ Company size adjacent to target range ({employees} employees)"
    return 0, f"✗ Company size outside target range ({employees} employees)"


def _score_lead_source(source: str) -> tuple[int, str]:
    pts = SOURCE_SCORES.get(source, 0)
    if pts >= 18:
        return pts, f"✓ High-intent source: {source}"
    if pts >= 10:
        return pts, f"~ Moderate-intent source: {source}"
    return pts, f"✗ Low-intent source: {source or 'unknown'}"


def _score_engagement(row: dict) -> tuple[int, list]:
    pts = 0
    reasons = []

    if str(row.get("Requested_Demo__c", "")).upper() == "TRUE":
        pts += 10
        reasons.append("✓ Requested a demo")

    if str(row.get("Whitepaper_Downloaded__c", "")).upper() == "TRUE":
        pts += 5
        reasons.append("✓ Downloaded gated content")

    pages = int(row.get("Pages_Visited__c") or 0)
    page_pts = min(pages * 1, 10)
    pts += page_pts
    if pages > 0:
        reasons.append(f"~ {pages} pages visited (+{page_pts} pts)")

    days = row.get("Days_Since_Last_Activity__c")
    days = int(days) if days not in (None, "") else 999
    if days <= 2:
        pts += 15
        reasons.append("✓ Active in the last 2 days")
    elif days <= 7:
        pts += 10
        reasons.append("~ Active in the last week")
    elif days <= 30:
        pts += 5
        reasons.append("~ Active in the last month")
    else:
        reasons.append(f"✗ No activity in {days} days")

    return pts, reasons


def score_lead(row: dict) -> ScoreResult:
    total = 0
    reasons = []

    pts, r = _score_industry(row.get("Industry"))
    total += pts
    reasons.append(r)

    pts, r = _score_company_size(row.get("NumberOfEmployees"))
    total += pts
    reasons.append(r)

    pts, r = _score_lead_source(row.get("LeadSource"))
    total += pts
    reasons.append(r)

    pts, r_list = _score_engagement(row)
    total += pts
    reasons.extend(r_list)

    total = min(total, 100)

    if total >= 75:
        tier = "Hot"
    elif total >= 50:
        tier = "Warm"
    else:
        tier = "Cold"

    return ScoreResult(lead_id=row.get("Id", ""), score=total, tier=tier, reasons=reasons)
