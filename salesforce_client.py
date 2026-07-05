"""
Salesforce data source — Phase 2.

Credentials come EXCLUSIVELY from environment variables (see .env.example):
  SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN, SF_CONSUMER_KEY, SF_CONSUMER_SECRET
Never hardcode, print, or log credential values.

If any are unset (or simple-salesforce isn't installed), is_salesforce_configured()
returns False and the app falls back to the bundled CSV — standalone mode is
always preserved.

Note: the SOQL deliberately omits the behavioral __c fields
(Requested_Demo__c etc.) — a fresh Dev org doesn't have them. scoring.py
already tolerates their absence via row.get().
"""

import os

try:
    from simple_salesforce import Salesforce
    _SF_AVAILABLE = True
except ImportError:
    _SF_AVAILABLE = False

REQUIRED_ENV_VARS = (
    "SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN",
    "SF_CONSUMER_KEY", "SF_CONSUMER_SECRET",
)

LEAD_SOQL = (
    "SELECT Id, FirstName, LastName, Company, Title, Email, Phone, "
    "Industry, NumberOfEmployees, AnnualRevenue, LeadSource, Website, Country "
    "FROM Lead WHERE IsConverted = false"
)

_connection = None


def is_salesforce_configured() -> bool:
    return _SF_AVAILABLE and all(os.environ.get(v) for v in REQUIRED_ENV_VARS)


def get_connection() -> "Salesforce":
    """OAuth 2.0 username-password flow via the Connected App.
    Salesforce requires the security token appended to the password for
    this grant (unless the org trusts the caller's IP)."""
    global _connection
    if _connection is None:
        _connection = Salesforce(
            username=os.environ["SF_USERNAME"],
            password=os.environ["SF_PASSWORD"] + os.environ["SF_SECURITY_TOKEN"],
            consumer_key=os.environ["SF_CONSUMER_KEY"],
            consumer_secret=os.environ["SF_CONSUMER_SECRET"],
        )
    return _connection


def _normalize(record: dict) -> dict:
    """Match the CSV row shape: drop metadata, None -> "", everything str."""
    return {
        k: ("" if v is None else str(v))
        for k, v in record.items()
        if k != "attributes"
    }


def fetch_leads() -> list[dict]:
    records = get_connection().query_all(LEAD_SOQL)["records"]
    return [_normalize(r) for r in records]


def get_rating_picklist_values() -> set[str]:
    """Runtime verification that Lead.Rating actually accepts our tiers."""
    fields = get_connection().Lead.describe()["fields"]
    rating = next(f for f in fields if f["name"] == "Rating")
    return {v["value"] for v in rating["picklistValues"] if v["active"]}


def update_rating(lead_id: str, tier: str) -> None:
    get_connection().Lead.update(lead_id, {"Rating": tier})
