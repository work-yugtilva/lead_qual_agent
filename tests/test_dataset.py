"""Shape/quality invariants for the bundled mock dataset."""
import csv

from hygiene import check_completeness, find_duplicates
from scoring import score_lead

EXPECTED_COLUMNS = [
    "Id", "FirstName", "LastName", "Company", "Title", "Email", "Phone",
    "Industry", "NumberOfEmployees", "AnnualRevenue", "LeadSource",
    "Website", "Country", "Requested_Demo__c", "Whitepaper_Downloaded__c",
    "Pages_Visited__c", "Days_Since_Last_Activity__c",
]


def load_rows() -> list[dict]:
    with open("data/mock_leads.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_schema_is_exact_salesforce_field_names():
    with open("data/mock_leads.csv", newline="") as f:
        header = next(csv.reader(f))
    assert header == EXPECTED_COLUMNS


def test_row_count_between_30_and_50():
    assert 30 <= len(load_rows()) <= 50


def test_ids_are_unique():
    ids = [r["Id"] for r in load_rows()]
    assert len(ids) == len(set(ids))


def test_tier_spread_covers_all_three_tiers():
    tiers = [score_lead(r).tier for r in load_rows()]
    assert tiers.count("Hot") >= 6
    assert tiers.count("Warm") >= 10
    assert tiers.count("Cold") >= 10


def test_dataset_has_industries_outside_icp():
    import scoring
    known = scoring.ICP_INDUSTRIES | scoring.ICP_ADJACENT_INDUSTRIES
    industries = {r["Industry"] for r in load_rows() if r["Industry"]}
    assert industries - known, "need out-of-ICP industries in the dataset"


def test_at_least_three_planted_duplicate_pairs():
    dupes = find_duplicates(load_rows())
    assert len(dupes) >= 6  # >=3 pairs, each direction listed


def test_company_lastname_dedup_branch_is_exercised():
    """At least one duplicate pair must have DIFFERENT emails, proving the
    company+lastname branch (not the email branch) caught it."""
    rows = load_rows()
    by_id = {r["Id"]: r for r in rows}
    dupes = find_duplicates(rows)
    assert any(
        by_id[a]["Email"].strip().lower() != by_id[b]["Email"].strip().lower()
        for a, others in dupes.items() for b in others
    )


def test_at_least_five_incomplete_records():
    incomplete = [r["Id"] for r in load_rows() if check_completeness(r)]
    assert len(incomplete) >= 5


def test_hand_computed_spot_checks():
    """Recompute these by hand if ICP constants or rows change."""
    scores = {r["Id"]: score_lead(r) for r in load_rows()}
    assert (scores["00Q011"].score, scores["00Q011"].tier) == (98, "Hot")
    assert (scores["00Q021"].score, scores["00Q021"].tier) == (75, "Hot")   # boundary
    assert (scores["00Q022"].score, scores["00Q022"].tier) == (50, "Warm")  # boundary
    assert (scores["00Q023"].score, scores["00Q023"].tier) == (49, "Cold")  # boundary
    assert (scores["00Q040"].score, scores["00Q040"].tier) == (0, "Cold")
