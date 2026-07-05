"""
Salesforce data source — Phase 2.

Auth uses the OAuth 2.0 **Client Credentials Flow** (server-to-server): the
Connected App authenticates as itself with its consumer key/secret. No user
password or security token is involved — Salesforce hard-disables the legacy
OAuth username-password flow (and SOAP login) in orgs created Summer '23 or
later, so client credentials is the supported path.

Credentials come EXCLUSIVELY from environment variables (see .env.example):
  SF_CONSUMER_KEY, SF_CONSUMER_SECRET, SF_INSTANCE_URL
Never hardcode, print, or log credential values.

Org setup required (one time, in the Connected App):
  1. OAuth Settings -> check "Enable Client Credentials Flow".
  2. Manage -> Edit Policies -> Client Credentials Flow -> set a Run-As user.
  3. SF_INSTANCE_URL = your My Domain URL (browser address bar in Setup),
     e.g. https://orgfarm-xxxx-dev-ed.develop.my.salesforce.com

If any var is unset (or simple-salesforce isn't installed),
is_salesforce_configured() returns False and the app falls back to the bundled
CSV — standalone mode is always preserved.

Note: the SOQL deliberately omits the behavioral __c fields
(Requested_Demo__c etc.) — a fresh Dev org doesn't have them. scoring.py
already tolerates their absence via row.get().
"""

import os

import requests

try:
    from simple_salesforce import Salesforce
    _SF_AVAILABLE = True
except ImportError:
    _SF_AVAILABLE = False

REQUIRED_ENV_VARS = (
    "SF_CONSUMER_KEY", "SF_CONSUMER_SECRET", "SF_INSTANCE_URL",
)

LEAD_SOQL = (
    "SELECT Id, FirstName, LastName, Company, Title, Email, Phone, "
    "Industry, NumberOfEmployees, AnnualRevenue, LeadSource, Website, Country "
    "FROM Lead WHERE IsConverted = false"
)

_connection = None


def is_salesforce_configured() -> bool:
    return _SF_AVAILABLE and all(os.environ.get(v) for v in REQUIRED_ENV_VARS)


def _instance_url() -> str:
    """Normalize SF_INSTANCE_URL to a scheme-qualified, trailing-slash-free URL."""
    url = os.environ["SF_INSTANCE_URL"].strip().rstrip("/")
    if not url.startswith("https://"):
        url = "https://" + url
    return url


def get_connection() -> "Salesforce":
    """OAuth 2.0 Client Credentials Flow via the Connected App.

    POSTs to the org's My Domain token endpoint (login.salesforce.com does
    not accept this grant) and hands the returned session to simple-salesforce.
    Only error/error_description are surfaced on failure — never secret values.
    """
    global _connection
    if _connection is None:
        resp = requests.post(
            f"{_instance_url()}/services/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": os.environ["SF_CONSUMER_KEY"],
                "client_secret": os.environ["SF_CONSUMER_SECRET"],
            },
            timeout=30,
        )
        if resp.status_code != 200:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise RuntimeError(
                "Salesforce client-credentials auth failed "
                f"({body.get('error', 'http ' + str(resp.status_code))}): "
                f"{body.get('error_description', resp.reason)}"
            )
        tok = resp.json()
        _connection = Salesforce(
            instance_url=tok["instance_url"],
            session_id=tok["access_token"],
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
