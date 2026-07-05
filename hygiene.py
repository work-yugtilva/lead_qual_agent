"""
CRM hygiene layer.

Mirrors the two things SDR interns actually get asked to clean up:
  1. Duplicate leads (same email, or same company + fuzzy name match)
  2. Incomplete records — specifically, missing the fields Salesforce
     requires to convert a Lead (Company, LastName, and either
     Email or Phone).
"""

from collections import defaultdict

REQUIRED_FOR_CONVERSION = ["Company", "LastName"]


def check_completeness(row: dict) -> list[str]:
    issues = []
    for field in REQUIRED_FOR_CONVERSION:
        if not row.get(field, "").strip():
            issues.append(f"Missing required field: {field}")

    if not row.get("Email", "").strip() and not row.get("Phone", "").strip():
        issues.append("Missing both Email and Phone — cannot contact")

    if not row.get("Title", "").strip():
        issues.append("Missing Title — cannot assess seniority/authority")

    if not row.get("Industry", "").strip() or not row.get("NumberOfEmployees", "").strip():
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
