"""Safe-parse helpers must never raise on messy CRM values."""
import pytest

from parsing import email_domain, is_missing, parse_float_safe, parse_int_safe, text


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("", None),
    ("1,200", 1200),
    ("1_200", 1200),
    (" 450 ", 450),
    ("500+", 500),
    ("N/A", None),
    ("n/a", None),
    ("unknown", None),
    ("-", None),
    ("null", None),
    ("abc", None),
    ("1200.0", 1200),
    ("0", 0),
    ("-5", -5),
    (42, 42),
    (3.7, 3),
    (True, 1),
])
def test_parse_int_safe(value, expected):
    assert parse_int_safe(value) == expected


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("", None),
    ("$1,200.50", 1200.5),
    ("N/A", None),
    ("50000000", 50000000.0),
    ("garbage", None),
    (12, 12.0),
])
def test_parse_float_safe(value, expected):
    assert parse_float_safe(value) == expected


@pytest.mark.parametrize("value,expected", [
    (None, True),
    ("", True),
    ("  ", True),
    (" N/A ", True),
    ("unknown", True),
    ("-", True),
    ("?", True),
    ("Acme", False),
    ("0", False),
])
def test_is_missing(value, expected):
    assert is_missing(value) is expected


@pytest.mark.parametrize("value,expected", [
    ("Ana.Torres@Brightloop.IO", "brightloop.io"),
    ("no-at-sign", ""),
    (None, ""),
    ("", ""),
    ("dangling@", ""),
])
def test_email_domain(value, expected):
    assert email_domain(value) == expected


def test_text_tolerates_none_values_and_missing_keys():
    assert text({"Company": None}, "Company") == ""
    assert text({}, "Company") == ""
    assert text({"Company": "  Acme  "}, "Company") == "Acme"
    assert text({"NumberOfEmployees": 450}, "NumberOfEmployees") == "450"
