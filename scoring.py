"""
Lead scoring engine — deterministic, rules-based (not ML).
No historical conversion data exists to train a model, so every point
awarded is traceable to a named rule. This is intentional: it mirrors
how most real SDR scoring setups work before enough data exists to
justify a predictive model, and it's fully defensible in an interview.

Legacy composite score is out of 100, split across four weighted factors:
  - Industry fit          (20 pts)
  - Company size fit       (20 pts)
  - Lead source quality     (20 pts)
  - Behavioral engagement + recency (40 pts)

Tier mapping matches Salesforce's native Lead.Rating picklist
(Hot / Warm / Cold); the app writes the tier straight back to that
field in Salesforce mode (see app.py / salesforce_client.py).

On top of the legacy composite, score_lead now produces five 0-100
sub-scores (fit, intent, authority, urgency, data confidence), a
qualification label, a recommended action, and risk flags. The legacy
score/tier math is a compatibility contract — characterization tests
lock it — so the new dimensions are additive: fit and intent are
derived from the same legacy point values, and new reason lines are
appended after the legacy ones, never inserted before them.
"""

import re
from dataclasses import dataclass, field

import hygiene
from parsing import parse_int_safe, text

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

QUALIFICATION_LABELS = ("qualified", "warm", "nurture", "not_fit", "needs_review")

RECOMMENDED_ACTIONS = (
    "route_to_sales",
    "send_personalized_outreach",
    "research_more",
    "nurture_sequence",
    "do_not_contact",
    "human_review",
)

# Flags that always route to a human — heuristics may be wrong, so a hit
# never auto-disqualifies; it escalates.
REVIEW_TRIGGER_FLAGS = {"prompt_injection_suspected", "conflicting_data", "possible_competitor"}
# Flags that disqualify outright — these are not sales leads.
DISQUALIFY_FLAGS = {"spam_or_junk", "student_or_academic"}


@dataclass
class ScoreResult:
    lead_id: str
    score: int
    tier: str          # Hot / Warm / Cold — maps to Lead.Rating
    reasons: list = field(default_factory=list)
    # v2 additive fields — defaulted so ScoreResult(lead_id, score, tier) still constructs
    fit_score: int = 0
    intent_score: int = 0
    authority_score: int = 0
    urgency_score: int = 0
    data_confidence_score: int = 0
    qualification_label: str = "nurture"
    recommended_action: str = "nurture_sequence"
    missing_fields: list = field(default_factory=list)
    risk_flags: list = field(default_factory=list)
    needs_human_review: bool = False


def _score_industry(industry: str) -> tuple[int, str]:
    industry = str(industry or "").strip()   # tolerate None/padded/non-str values
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
    parsed = parse_int_safe(employees)
    if parsed is None:
        return 0, "✗ Employee count unknown"
    employees = parsed
    lo, hi = ICP_EMPLOYEE_RANGE
    alo, ahi = ICP_EMPLOYEE_ADJACENT
    if lo <= employees <= hi:
        return 20, f"✓ Company size in target range ({employees} employees)"
    if alo <= employees <= ahi:
        return 10, f"~ Company size adjacent to target range ({employees} employees)"
    return 0, f"✗ Company size outside target range ({employees} employees)"


def _score_lead_source(source: str) -> tuple[int, str]:
    source = str(source or "").strip()       # tolerate None/padded/non-str values
    pts = SOURCE_SCORES.get(source, 0)
    if pts >= 18:
        return pts, f"✓ High-intent source: {source}"
    if pts >= 10:
        return pts, f"~ Moderate-intent source: {source}"
    return pts, f"✗ Low-intent source: {source or 'unknown'}"


def _score_engagement(row: dict) -> tuple[int, list]:
    pts = 0
    reasons = []

    if str(row.get("Requested_Demo__c", "")).strip().upper() == "TRUE":
        pts += 10
        reasons.append("✓ Requested a demo")

    if str(row.get("Whitepaper_Downloaded__c", "")).strip().upper() == "TRUE":
        pts += 5
        reasons.append("✓ Downloaded gated content")

    pages = parse_int_safe(row.get("Pages_Visited__c")) or 0
    pages = max(pages, 0)
    page_pts = min(pages * 1, 10)
    pts += page_pts
    if pages > 0:
        reasons.append(f"~ {pages} pages visited (+{page_pts} pts)")

    days = parse_int_safe(row.get("Days_Since_Last_Activity__c"))
    if days is None or days < 0:   # negative "days since" is malformed, not hot
        days = 999
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


# ---------------------------------------------------------------------------
# v2 sub-scores — each 0-100, each explainable
# ---------------------------------------------------------------------------

# Checked in order; first match wins. Student/intern first so "Marketing
# Intern" never matches "Marketing" seniority tokens further down.
_AUTHORITY_BUCKETS = [
    (10, "student or intern — not a buyer", re.compile(r"\b(student|intern)\b", re.I)),
    # VP/head checked before executive so "Vice President" scores 85, not 100
    # via the bare "president" token in the executive pattern.
    (85, "senior leadership (VP/head)", re.compile(r"\b(vp|svp|evp|avp|vice\s+president|head)\b", re.I)),
    (100, "executive decision-maker", re.compile(r"\b(founder|co-founder|owner|ceo|president|chief|c[a-z]o)\b", re.I)),
    (70, "director-level influence", re.compile(r"\bdirector\b", re.I)),
    # "lead" the role, not "lead generation" the function
    (50, "manager-level influence", re.compile(r"\b(manager|principal|lead(?!\s+gen(eration)?\b))\b", re.I)),
    (25, "external consultant/advisor — indirect authority", re.compile(r"\b(consultant|advisor|freelance|contractor)\b", re.I)),
    (30, "individual contributor", re.compile(r"\b(engineer|developer|analyst|associate|specialist|coordinator|administrator|officer|representative|accountant|designer|scientist)\b", re.I)),
]


def _score_authority(title: str) -> tuple[int, str]:
    if not title:
        return 40, "Authority unknown — title missing"
    for score, label, pattern in _AUTHORITY_BUCKETS:
        if pattern.search(title):
            return score, f"{label} ({title})"
    return 40, f"Authority unknown — unrecognized title ({title})"


def _score_urgency(row: dict) -> tuple[int, str]:
    pts = 0
    signals = []
    if str(row.get("Requested_Demo__c", "")).strip().upper() == "TRUE":
        pts += 50
        signals.append("demo requested")
    days = parse_int_safe(row.get("Days_Since_Last_Activity__c"))
    if days is not None and days >= 0:
        if days <= 2:
            pts += 50
            signals.append("active within 2 days")
        elif days <= 7:
            pts += 35
            signals.append("active within a week")
        elif days <= 30:
            pts += 15
            signals.append("active within a month")
    pts = min(pts, 100)
    return pts, (", ".join(signals) if signals else "no urgency signals")


# (field, points, treat-invalid-email-as-missing handled separately)
_CONFIDENCE_COMPONENTS = [
    ("Email", 20),
    ("Phone", 10),
    ("Company", 15),
    ("LastName", 10),
    ("Title", 15),
    ("Website", 10),
    ("Industry", 10),
    ("NumberOfEmployees", 10),
]


def _score_data_confidence(row: dict) -> tuple[int, list, str]:
    score = 0
    missing = []
    for field_name, points in _CONFIDENCE_COMPONENTS:
        value = text(row, field_name)
        if not value:
            missing.append(field_name)
            continue
        if field_name == "Email" and not hygiene.EMAIL_RE.match(value):
            missing.append(field_name)
            continue
        if field_name == "NumberOfEmployees" and parse_int_safe(value) is None:
            missing.append(field_name)
            continue
        score += points
    reason = "all key fields present" if not missing else f"missing/invalid: {', '.join(missing)}"
    return score, missing, reason


def _qualify(fit, intent, authority, urgency, confidence, flags: set, missing_fields: list):
    """Deterministic decision tree. Returns (label, action, needs_review, why)."""
    if flags & REVIEW_TRIGGER_FLAGS:
        hit = ", ".join(sorted(flags & REVIEW_TRIGGER_FLAGS))
        return "needs_review", "human_review", True, f"risk flag requires a human ({hit})"

    if flags & DISQUALIFY_FLAGS:
        hit = ", ".join(sorted(flags & DISQUALIFY_FLAGS))
        return "not_fit", "do_not_contact", False, f"not a real buyer ({hit})"

    if confidence < 40:
        if intent >= 60 or urgency >= 70:
            return "needs_review", "human_review", True, "strong buying signals but record too incomplete to trust"
        return "nurture", "research_more", False, "record too incomplete to qualify"

    if "missing_contact_info" in flags:
        return "nurture", "research_more", False, "no way to contact this lead yet"

    label = action = why = None
    if fit >= 75 and authority >= 60 and (intent >= 60 or (intent >= 45 and urgency >= 80)):
        return "qualified", "route_to_sales", False, "strong fit, strong intent, senior contact"
    if fit >= 75 and intent >= 60:
        label, action, why = "warm", "send_personalized_outreach", "right company, engaged, but contact seniority unclear"
    elif fit >= 50 and intent >= 60:
        label, action, why = "warm", "send_personalized_outreach", "engaged lead with partial ICP fit"
    elif fit >= 75 and intent >= 35:
        label, action, why = "warm", "send_personalized_outreach", "strong ICP fit with moderate engagement"
    elif fit < 30 and intent >= 60:
        return "nurture", "research_more", False, "high intent but weak ICP fit — verify before investing"
    elif fit >= 50 or intent >= 35:
        return "nurture", "nurture_sequence", False, "plausible future fit but no buying signals yet"
    else:
        return "not_fit", "do_not_contact", False, "outside ICP with no engagement"

    # Warm leads with unverified firmographics get researched before outreach.
    if {"Industry", "NumberOfEmployees", "Title"} & set(missing_fields):
        action = "research_more"
        why += "; verify missing firmographics first"
    return label, action, False, why


def score_lead(row: dict) -> ScoreResult:
    # ---- legacy composite (compatibility contract — do not reorder) ----
    reasons = []

    industry_pts, r = _score_industry(row.get("Industry"))
    reasons.append(r)

    size_pts, r = _score_company_size(row.get("NumberOfEmployees"))
    reasons.append(r)

    source_pts, r = _score_lead_source(row.get("LeadSource"))
    reasons.append(r)

    engagement_pts, r_list = _score_engagement(row)
    reasons.extend(r_list)

    total = min(industry_pts + size_pts + source_pts + engagement_pts, 100)

    if total >= 75:
        tier = "Hot"
    elif total >= 50:
        tier = "Warm"
    else:
        tier = "Cold"

    # ---- v2 dimensions (appended after legacy reasons) ----
    fit = (industry_pts + size_pts) * 5 // 2                      # 0..100 in steps of 25
    intent = round((source_pts + engagement_pts) * 100 / 60)      # 0..100
    authority, auth_reason = _score_authority(text(row, "Title"))
    urgency, urg_reason = _score_urgency(row)
    confidence, missing_fields, conf_reason = _score_data_confidence(row)

    flag_map = hygiene.detect_risk_flags(row)
    flag_codes = sorted(flag_map)

    label, action, needs_review, why = _qualify(
        fit, intent, authority, urgency, confidence, set(flag_codes), missing_fields
    )

    reasons.append(f"[fit] {fit}/100 — industry + company size vs ICP")
    reasons.append(f"[intent] {intent}/100 — lead source + engagement signals")
    reasons.append(f"[authority] {authority}/100 — {auth_reason}")
    reasons.append(f"[urgency] {urgency}/100 — {urg_reason}")
    reasons.append(f"[confidence] {confidence}/100 — {conf_reason}")
    for code in flag_codes:
        reasons.append(f"⚠ [risk] {flag_map[code]}")
    reasons.append(f"[decision] label={label} action={action} — {why}")

    return ScoreResult(
        lead_id=row.get("Id", ""),
        score=total,
        tier=tier,
        reasons=reasons,
        fit_score=fit,
        intent_score=intent,
        authority_score=authority,
        urgency_score=urgency,
        data_confidence_score=confidence,
        qualification_label=label,
        recommended_action=action,
        missing_fields=missing_fields,
        risk_flags=flag_codes,
        needs_human_review=needs_review,
    )
