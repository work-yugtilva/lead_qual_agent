"""
Safe parsing helpers for messy CRM values.

CSV exports and hand-entered CRM fields contain None, empty strings,
"N/A", "unknown", "-", "1,200", "500+", and worse. Every helper here
returns a clean value or None — never raises. Leaf module: imports
nothing from this project so scoring and hygiene can both use it.
"""

MISSING_TOKENS = {"", "n/a", "na", "none", "unknown", "-", "null", "tbd", "?"}


def is_missing(value) -> bool:
    """True when a CRM value carries no information."""
    if value is None:
        return True
    return str(value).strip().lower() in MISSING_TOKENS


def parse_int_safe(value):
    """Parse an int out of a messy CRM value. Returns None when it can't.

    Handles None, "", "1,200", "1_200", " 450 ", "500+", "N/A", "unknown",
    "-", floats, and garbage strings.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    s = str(value).strip()
    if s.lower() in MISSING_TOKENS:
        return None
    s = s.replace(",", "").replace("_", "").replace(" ", "")
    if s.endswith("+"):
        s = s[:-1]
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except (ValueError, OverflowError):
            return None


def parse_float_safe(value):
    """Same contract as parse_int_safe but for floats (AnnualRevenue etc.)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.lower() in MISSING_TOKENS:
        return None
    s = s.replace(",", "").replace("_", "").replace(" ", "").rstrip("+")
    s = s.removeprefix("$")
    try:
        return float(s)
    except ValueError:
        return None


def email_domain(email) -> str:
    """Lowercased domain of an email address, or "" if unparseable."""
    s = str(email or "").strip().lower()
    if "@" not in s:
        return ""
    domain = s.rsplit("@", 1)[1]
    return domain if domain else ""


def text(row: dict, key: str) -> str:
    """Safe stripped-string field access — tolerates None values and missing keys."""
    return str(row.get(key) or "").strip()
