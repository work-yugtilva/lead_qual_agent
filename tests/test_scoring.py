"""Characterization tests locking current scoring behavior.

Industry/size expectations derive from scoring's own ICP constants so
retuning the ICP does not invalidate these tests. Source scores,
engagement math, and tier thresholds are fixed by spec.
"""
import pytest

import scoring
from scoring import score_lead


def _icp_industry() -> str:
    return sorted(scoring.ICP_INDUSTRIES)[0]


def _adjacent_industry() -> str:
    if not scoring.ICP_ADJACENT_INDUSTRIES:
        pytest.skip("no adjacent industries configured")
    return sorted(scoring.ICP_ADJACENT_INDUSTRIES)[0]


def _in_range_size() -> int:
    lo, hi = scoring.ICP_EMPLOYEE_RANGE
    return (lo + hi) // 2


def _adjacent_size() -> int:
    lo, hi = scoring.ICP_EMPLOYEE_RANGE
    alo, ahi = scoring.ICP_EMPLOYEE_ADJACENT
    if alo < lo:
        return lo - 1
    if ahi > hi:
        return hi + 1
    pytest.skip("adjacent employee band identical to primary band")


def _out_of_range_size() -> int:
    return scoring.ICP_EMPLOYEE_ADJACENT[1] + 1


def make_row(**overrides) -> dict:
    row = {
        "Id": "00QTEST",
        "FirstName": "Test", "LastName": "Lead", "Company": "TestCo",
        "Title": "VP", "Email": "t@example.com", "Phone": "555-0100",
        "Industry": "", "NumberOfEmployees": "", "AnnualRevenue": "",
        "LeadSource": "", "Website": "", "Country": "USA",
        "Requested_Demo__c": "FALSE", "Whitepaper_Downloaded__c": "FALSE",
        "Pages_Visited__c": "0", "Days_Since_Last_Activity__c": "",
    }
    row.update(overrides)
    return row


def test_constants_sane():
    """Guard for user-supplied ICP values (re-run after ICP tuning)."""
    assert scoring.ICP_INDUSTRIES, "primary ICP industries must be non-empty"
    assert not (scoring.ICP_INDUSTRIES & scoring.ICP_ADJACENT_INDUSTRIES)
    lo, hi = scoring.ICP_EMPLOYEE_RANGE
    alo, ahi = scoring.ICP_EMPLOYEE_ADJACENT
    assert lo <= hi and alo <= ahi
    assert alo <= lo and ahi >= hi, "adjacent band must contain primary band"
    assert "Nonexistent Industry XYZ" not in (
        scoring.ICP_INDUSTRIES | scoring.ICP_ADJACENT_INDUSTRIES
    )


# ---- industry factor (20 pts) ----

def test_icp_industry_scores_20():
    assert score_lead(make_row(Industry=_icp_industry())).score == 20

def test_adjacent_industry_scores_10():
    assert score_lead(make_row(Industry=_adjacent_industry())).score == 10

def test_unknown_industry_scores_0():
    assert score_lead(make_row(Industry="Nonexistent Industry XYZ")).score == 0

def test_blank_industry_scores_0():
    assert score_lead(make_row(Industry="")).score == 0


# ---- company size factor (20 pts) ----

def test_size_in_range_scores_20():
    assert score_lead(make_row(NumberOfEmployees=str(_in_range_size()))).score == 20

def test_size_adjacent_scores_10():
    assert score_lead(make_row(NumberOfEmployees=str(_adjacent_size()))).score == 10

def test_size_out_of_range_scores_0():
    assert score_lead(make_row(NumberOfEmployees=str(_out_of_range_size()))).score == 0

def test_size_blank_scores_0():
    assert score_lead(make_row(NumberOfEmployees="")).score == 0


# ---- lead source factor (20 pts, fixed table) ----

@pytest.mark.parametrize("source,pts", [
    ("Referral", 20), ("Demo Request", 18), ("Content Download", 12),
    ("Web", 6), ("Cold List", 0), ("Some Unknown Source", 0), ("", 0),
])
def test_source_scores(source, pts):
    assert score_lead(make_row(LeadSource=source)).score == pts


# ---- engagement factor (40 pts, fixed math) ----

def test_demo_request_adds_10():
    assert score_lead(make_row(Requested_Demo__c="TRUE")).score == 10

def test_demo_flag_is_case_insensitive():
    assert score_lead(make_row(Requested_Demo__c="true")).score == 10

def test_whitepaper_adds_5():
    assert score_lead(make_row(Whitepaper_Downloaded__c="TRUE")).score == 5

def test_pages_visited_capped_at_10():
    assert score_lead(make_row(Pages_Visited__c="25")).score == 10
    assert score_lead(make_row(Pages_Visited__c="7")).score == 7

@pytest.mark.parametrize("days,pts", [
    ("1", 15), ("2", 15), ("3", 10), ("7", 10),
    ("8", 5), ("30", 5), ("31", 0), ("", 0),
])
def test_recency_buckets(days, pts):
    assert score_lead(make_row(Days_Since_Last_Activity__c=days)).score == pts

def test_max_engagement_is_40():
    row = make_row(Requested_Demo__c="TRUE", Whitepaper_Downloaded__c="TRUE",
                   Pages_Visited__c="10", Days_Since_Last_Activity__c="1")
    assert score_lead(row).score == 40


# ---- totals and tiers ----

def _base_hot_row(pages: str) -> dict:
    # ICP industry (20) + in-range size (20) + Referral (20) + demo (10) + pages
    return make_row(Industry=_icp_industry(),
                    NumberOfEmployees=str(_in_range_size()),
                    LeadSource="Referral", Requested_Demo__c="TRUE",
                    Pages_Visited__c=pages, Days_Since_Last_Activity__c="")

def test_perfect_lead_scores_exactly_100_and_is_hot():
    row = make_row(Industry=_icp_industry(),
                   NumberOfEmployees=str(_in_range_size()),
                   LeadSource="Referral", Requested_Demo__c="TRUE",
                   Whitepaper_Downloaded__c="TRUE", Pages_Visited__c="10",
                   Days_Since_Last_Activity__c="1")
    result = score_lead(row)
    assert result.score == 100 and result.tier == "Hot"

def test_75_is_hot_and_74_is_warm():
    assert score_lead(_base_hot_row("5")).score == 75
    assert score_lead(_base_hot_row("5")).tier == "Hot"
    assert score_lead(_base_hot_row("4")).score == 74
    assert score_lead(_base_hot_row("4")).tier == "Warm"

def _base_warm_row(pages: str) -> dict:
    # adjacent industry (10) + adjacent size (10) + Content Download (12)
    # + whitepaper (5) + pages + days 7 (+10)
    return make_row(Industry=_adjacent_industry(),
                    NumberOfEmployees=str(_adjacent_size()),
                    LeadSource="Content Download",
                    Whitepaper_Downloaded__c="TRUE",
                    Pages_Visited__c=pages, Days_Since_Last_Activity__c="7")

def test_50_is_warm_and_49_is_cold():
    assert score_lead(_base_warm_row("3")).score == 50
    assert score_lead(_base_warm_row("3")).tier == "Warm"
    assert score_lead(_base_warm_row("2")).score == 49
    assert score_lead(_base_warm_row("2")).tier == "Cold"

def test_zero_engagement_lead_is_cold_with_reasons():
    result = score_lead(make_row(Id="00QZERO"))
    assert result.score == 0 and result.tier == "Cold"
    assert result.lead_id == "00QZERO"
    assert len(result.reasons) >= 4
