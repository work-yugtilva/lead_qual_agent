"""Characterization tests locking current hygiene behavior."""
from hygiene import check_completeness, find_duplicates, same_company_clusters


def make_row(**overrides) -> dict:
    row = {
        "Id": "00QTEST", "FirstName": "Test", "LastName": "Lead",
        "Company": "TestCo", "Title": "VP", "Email": "t@example.com",
        "Phone": "555-0100", "Industry": "Technology",
        "NumberOfEmployees": "200",
    }
    row.update(overrides)
    return row


def test_complete_row_has_no_issues():
    assert check_completeness(make_row()) == []

def test_missing_company_flagged():
    assert "Missing required field: Company" in check_completeness(make_row(Company=""))

def test_missing_lastname_flagged():
    assert "Missing required field: LastName" in check_completeness(make_row(LastName=""))

def test_missing_both_email_and_phone_flagged():
    issues = check_completeness(make_row(Email="", Phone=""))
    assert "Missing both Email and Phone — cannot contact" in issues

def test_email_only_is_contactable():
    assert check_completeness(make_row(Phone="")) == []

def test_missing_title_flagged():
    issues = check_completeness(make_row(Title=""))
    assert any("Missing Title" in i for i in issues)

def test_missing_firmographics_flagged():
    assert any("firmographic" in i for i in check_completeness(make_row(Industry="")))
    assert any("firmographic" in i for i in check_completeness(make_row(NumberOfEmployees="")))


def test_email_match_is_case_insensitive_duplicate():
    rows = [make_row(Id="A", Email="Dana@X.com", Company="One Co", LastName="Aa"),
            make_row(Id="B", Email="dana@x.com", Company="Two Co", LastName="Bb")]
    dupes = find_duplicates(rows)
    assert dupes == {"A": ["B"], "B": ["A"]}


def test_company_lastname_match_with_different_emails_is_duplicate():
    rows = [make_row(Id="A", Email="james@sable.com", Company="Sablewood", LastName="Whitfield"),
            make_row(Id="B", Email="jim@other.com", Company="sablewood", LastName="WHITFIELD")]
    dupes = find_duplicates(rows)
    assert dupes == {"A": ["B"], "B": ["A"]}

def test_blank_company_or_lastname_never_matches():
    rows = [make_row(Id="A", Email="a@a.com", Company="", LastName="Smith"),
            make_row(Id="B", Email="b@b.com", Company="", LastName="Smith")]
    assert find_duplicates(rows) == {}

def test_same_company_different_lastname_is_not_duplicate():
    rows = [make_row(Id="A", Email="a@a.com", Company="Ferro", LastName="Reyes"),
            make_row(Id="B", Email="b@b.com", Company="Ferro", LastName="Wachowski")]
    assert find_duplicates(rows) == {}
    assert same_company_clusters(rows) == {"ferro": ["A", "B"]}


def test_bundled_dataset_planted_email_dupe():
    import csv
    with open("data/mock_leads.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    dupes = find_duplicates(rows)
    assert "00Q010" in dupes.get("00Q002", [])
    assert "00Q002" in dupes.get("00Q010", [])
