"""Live Salesforce integration tests.

Skipped entirely unless all SF_* env vars are set (no mocked creds).
Runs against a Developer Edition org only — never production.
Load creds first:  set -a; source .env; set +a
"""
import os

import pytest

REQUIRED = (
    "SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN",
    "SF_CONSUMER_KEY", "SF_CONSUMER_SECRET",
)

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(v) for v in REQUIRED),
    reason="Salesforce credentials not configured in environment",
)

EXPECTED_FIELDS = {
    "Id", "FirstName", "LastName", "Company", "Title", "Email", "Phone",
    "Industry", "NumberOfEmployees", "AnnualRevenue", "LeadSource",
    "Website", "Country",
}


def test_fetch_leads_returns_normalized_expected_fields():
    from salesforce_client import fetch_leads
    rows = fetch_leads()
    assert rows, "Dev org must contain at least one unconverted Lead"
    row = rows[0]
    assert EXPECTED_FIELDS <= set(row)
    assert "attributes" not in row
    assert all(isinstance(v, str) for v in row.values())  # None -> "", ints -> str


def test_rating_picklist_has_hot_warm_cold():
    from salesforce_client import get_rating_picklist_values
    assert {"Hot", "Warm", "Cold"} <= get_rating_picklist_values()


def test_pipeline_tolerates_salesforce_rows_without_behavioral_fields():
    from salesforce_client import fetch_leads
    from hygiene import check_completeness
    from scoring import score_lead
    row = fetch_leads()[0]  # fresh org has no __c fields — must not raise
    assert score_lead(row).tier in {"Hot", "Warm", "Cold"}
    assert isinstance(check_completeness(row), list)


def test_rating_writeback_persists():
    from salesforce_client import fetch_leads, get_connection, update_rating
    lead_id = fetch_leads()[0]["Id"]
    sf = get_connection()
    original = sf.Lead.get(lead_id).get("Rating")
    target = "Hot" if original != "Hot" else "Warm"
    update_rating(lead_id, target)
    try:
        requeried = sf.query(f"SELECT Rating FROM Lead WHERE Id = '{lead_id}'")["records"][0]
        assert requeried["Rating"] == target
    finally:
        sf.Lead.update(lead_id, {"Rating": original})
