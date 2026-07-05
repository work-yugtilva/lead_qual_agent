"""Guards the 4-section enrichment contract and graceful degradation."""
import enrichment

SECTION_HEADERS = [
    "1. Company Snapshot",
    "2. Recent Signals",
    "3. Competitive/Tech Context",
    "4. Outreach Angle",
]


def test_prompt_has_exactly_the_four_sections():
    for header in SECTION_HEADERS:
        assert header in enrichment.ENRICHMENT_PROMPT
    assert not any(
        line.strip().startswith("5.")
        for line in enrichment.ENRICHMENT_PROMPT.splitlines()
    )


def test_prompt_forbids_invention():
    assert "Do not invent facts" in enrichment.ENRICHMENT_PROMPT


def test_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert enrichment.is_enrichment_available() is False


def test_enrich_lead_degrades_gracefully_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = enrichment.enrich_lead("X Co", "x.com", "Technology")
    assert "Enrichment disabled" in out
