"""
CRM hygiene layer.

Mirrors the two things SDR interns actually get asked to clean up:
  1. Duplicate leads (same email, or same company + same last name)
  2. Incomplete records — specifically, missing the fields Salesforce
     requires to convert a Lead (Company, LastName, and either
     Email or Phone).

Plus a risk-flag layer (detect_risk_flags) that surfaces suspicious
records — spam, students, competitors, conflicting firmographics, and
prompt-injection-like text — as warnings. Hygiene never deletes or
mutates records; it only reports.
"""

import re
from collections import defaultdict

from parsing import email_domain, parse_float_safe, parse_int_safe, text

REQUIRED_FOR_CONVERSION = ["Company", "LastName"]


def check_completeness(row: dict) -> list[str]:
    issues = []
    for field in REQUIRED_FOR_CONVERSION:
        if not text(row, field):
            issues.append(f"Missing required field: {field}")

    if not text(row, "Email") and not text(row, "Phone"):
        issues.append("Missing both Email and Phone — cannot contact")

    if not text(row, "Title"):
        issues.append("Missing Title — cannot assess seniority/authority")

    if not text(row, "Industry") or not text(row, "NumberOfEmployees"):
        issues.append("Missing firmographic data — scoring will be incomplete")

    return issues


def find_duplicates(rows: list[dict]) -> dict[str, list[str]]:
    """
    Returns {lead_id: [other lead_ids it duplicates]}.
    Matches on: exact email match, OR same company + same last name.
    """
    by_email = defaultdict(list)
    by_company_lastname = defaultdict(list)

    for row in rows:
        email = row.get("Email", "").strip().lower()
        if email:
            by_email[email].append(row["Id"])

        company = row.get("Company", "").strip().lower()
        lastname = row.get("LastName", "").strip().lower()
        if company and lastname:
            by_company_lastname[(company, lastname)].append(row["Id"])

        # Same company appearing more than once is a softer flag —
        # multiple contacts at one account isn't a duplicate, but it's
        # worth surfacing for account-based routing.

    duplicate_map = defaultdict(set)

    for ids in by_email.values():
        if len(ids) > 1:
            for lead_id in ids:
                duplicate_map[lead_id].update(i for i in ids if i != lead_id)

    for ids in by_company_lastname.values():
        if len(ids) > 1:
            for lead_id in ids:
                duplicate_map[lead_id].update(i for i in ids if i != lead_id)

    return {k: sorted(v) for k, v in duplicate_map.items()}


def same_company_clusters(rows: list[dict]) -> dict[str, list[str]]:
    """Flags multiple distinct leads from the same company (routing signal, not a dupe)."""
    by_company = defaultdict(list)
    for row in rows:
        company = row.get("Company", "").strip().lower()
        if company:
            by_company[company].append(row["Id"])
    return {c: ids for c, ids in by_company.items() if len(ids) > 1}


# ---------------------------------------------------------------------------
# Risk-flag detection
#
# Each detector returns a human-readable message or None. Flag codes are
# stable snake_case identifiers: evals and the scoring decision tree match
# on codes; the UI shows messages. Messages deliberately never echo the
# suspicious field content itself, so a prompt-injection payload in a lead
# field can't ride a warning message back into the UI or a research brief.
# ---------------------------------------------------------------------------

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "proton.me", "protonmail.com", "mail.com", "gmx.com",
}

# Fictional names used by the eval suite. A real deployment replaces these
# with its actual competitor list. Exact-match only — never substring — so a
# legitimate lead at a company whose name contains a competitor's name can't
# be flagged by accident.
COMPETITOR_NAMES = {
    "pipeline titan", "leadhawk", "scorewell ai", "quotafox",
}

ACADEMIC_TITLE_TOKENS = {"student", "intern", "professor", "lecturer", "phd", "postdoc"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_JUNK_VALUE_RE = re.compile(
    r"^(test(ing)?\d*|(asdf)+\w?|qwerty\w*|x{3,}|z{3,}|a{3,}|foo|bar|baz|sample|fake|junk|spam|delete( me)?|do not use)$",
    re.IGNORECASE,
)
_REPEATED_CHAR_RE = re.compile(r"^(.)\1+$")

# Narrow, multi-word patterns on purpose: single common words would flag
# legitimate company names. A dataset-wide test asserts zero hits across
# the bundled 40-row mock dataset.
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|context)", re.I),
    re.compile(r"disregard\s+(the\s+|all\s+)?(system|previous|above|prior)", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"</?\s*(system|assistant|user)\s*>", re.I),
    re.compile(r"^\s*(system|assistant)\s*:", re.I | re.M),
    re.compile(r"reveal\s+(your\s+)?(secret|api[\s_-]?key|password|credential|instruction)", re.I),
    re.compile(r"api[\s_-]?key", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.I),
    re.compile(r"(mark|score|rate)\s+this\s+lead\s+as", re.I),
    re.compile(r"disregard\s+(everything|anything|all)\b", re.I),
    re.compile(r"forget\s+(your|all|any|previous|prior|the)\s+(previous\s+|prior\s+)?(instructions|directions|rules|guidelines|training)", re.I),
    re.compile(r"act\s+as\s+(the\s+|an?\s+)?(system|assistant|administrator|admin|ai)\b", re.I),
    re.compile(r"from\s+now\s+on,?\s+(respond|reply|answer|you)", re.I),
    re.compile(r"repeat\s+(everything|all|the\s+text)\s+(above|before)", re.I),
    re.compile(r"(print|output|show|display)\s+(the\s+)?(contents\s+of\s+)?(your\s+)?(system|configuration|hidden|internal)\s*(prompt|instructions|settings)?", re.I),
]

INJECTION_SCAN_FIELDS = [
    "FirstName", "LastName", "Company", "Title",
    "Website", "Email", "Industry", "LeadSource",
]


def _detect_invalid_email(row):
    email = text(row, "Email")
    if email and not EMAIL_RE.match(email):
        return "Email present but does not look like a valid address"
    return None


def _detect_missing_website(row):
    if not text(row, "Website"):
        return "No website on record — company cannot be independently verified"
    return None


def _detect_free_email_domain(row):
    domain = email_domain(text(row, "Email"))
    if domain not in FREE_EMAIL_DOMAINS:
        return None
    employees = parse_int_safe(row.get("NumberOfEmployees"))
    if text(row, "Company") or (employees is not None and employees >= 50):
        return "Personal email domain used with a company record — verify identity"
    return None


def _detect_student_or_academic(row):
    title_words = set(re.findall(r"[a-z]+", text(row, "Title").lower()))
    if title_words & ACADEMIC_TITLE_TOKENS:
        return "Title suggests a student or academic — unlikely to be a buyer"
    domain = email_domain(text(row, "Email"))
    if domain.endswith(".edu") or ".ac." in domain or domain.endswith(".ac"):
        return "Academic email domain — unlikely to be a buyer"
    return None


def _detect_possible_competitor(row):
    company = " ".join(text(row, "Company").lower().split())
    if company and company in COMPETITOR_NAMES:
        return "Company matches known-competitor list — do not share pricing or roadmap"
    return None


def _detect_spam_or_junk(row):
    company = text(row, "Company")
    lastname = text(row, "LastName")
    for value in (company, lastname):
        if value and _JUNK_VALUE_RE.match(value):
            return "Company or name looks like placeholder/junk data"
    # Repeated-char check on Company only, min length 3 — two-letter surnames
    # like "Oo" are real names, not junk.
    if len(company) >= 3 and _REPEATED_CHAR_RE.match(company.lower()):
        return "Company or name looks like placeholder/junk data"
    if company and company.isdigit():
        return "Company or name looks like placeholder/junk data"
    email = text(row, "Email").lower()
    if "@" in email:
        local = email.split("@", 1)[0]
        domain_base = email_domain(email).split(".")[0]
        if _JUNK_VALUE_RE.match(local) and _JUNK_VALUE_RE.match(domain_base):
            return "Email looks like placeholder/junk data"
    return None


def _detect_conflicting_data(row):
    employees = parse_int_safe(row.get("NumberOfEmployees"))
    revenue = parse_float_safe(row.get("AnnualRevenue"))
    if employees is None or revenue is None:
        return None
    if employees > 10_000 and revenue < 1_000_000:
        return "Employee count and annual revenue contradict each other"
    if employees <= 10 and revenue >= 100_000_000:
        return "Employee count and annual revenue contradict each other"
    return None


def _detect_missing_contact_info(row):
    if not text(row, "Email") and not text(row, "Phone"):
        return "No email or phone — lead cannot be contacted"
    return None


def _detect_prompt_injection(row):
    for field in INJECTION_SCAN_FIELDS:
        value = text(row, field)
        if not value:
            continue
        for pattern in INJECTION_PATTERNS:
            if pattern.search(value):
                return f"Prompt-injection-like text found in {field} field — do not trust this record's free text"
    return None


_DETECTORS = [
    ("invalid_email", _detect_invalid_email),
    ("missing_website", _detect_missing_website),
    ("free_email_domain", _detect_free_email_domain),
    ("student_or_academic", _detect_student_or_academic),
    ("possible_competitor", _detect_possible_competitor),
    ("spam_or_junk", _detect_spam_or_junk),
    ("conflicting_data", _detect_conflicting_data),
    ("missing_contact_info", _detect_missing_contact_info),
    ("prompt_injection_suspected", _detect_prompt_injection),
]


def detect_risk_flags(row: dict) -> dict[str, str]:
    """Run every risk detector against one lead row.

    Returns {flag_code: human_message}. Empty dict means no risks found.
    Never raises on malformed values and never mutates the row.
    """
    flags = {}
    for code, detector in _DETECTORS:
        try:
            message = detector(row)
        except Exception:
            # A detector must never take the pipeline down over bad data.
            message = None
        if message:
            flags[code] = message
    return flags
