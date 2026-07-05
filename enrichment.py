"""
Account research enrichment.

Deliberately capped to 4 signal categories — this is the module that
turns into an unbounded scraping project if you let it. Don't add a
5th category without cutting one.

  1. Company snapshot   (what they do, size/stage)
  2. Recent signals      (funding, news, leadership changes)
  3. Tech/competitive context (only if discoverable, not guessed)
  4. Outreach angle       (one sentence a rep could actually use)

Requires ANTHROPIC_API_KEY as an environment variable. If it's not
set, the app still runs — enrichment is just disabled and the score
+ hygiene output still works standalone.
"""

import os

try:
    import anthropic
    _CLIENT_AVAILABLE = True
except ImportError:
    _CLIENT_AVAILABLE = False

ENRICHMENT_PROMPT = """You are researching a B2B sales lead's company for an SDR account brief.

Company: {company}
Website: {website}
Industry: {industry}

Produce a brief with exactly these 4 sections, each 1-2 sentences, no fluff:
1. Company Snapshot — what they do, approximate size/stage
2. Recent Signals — funding, news, leadership changes (only if you find real, current info — say "nothing notable found" if not)
3. Competitive/Tech Context — only if genuinely discoverable, otherwise say "not available"
4. Outreach Angle — one concrete, specific sentence a rep could open a call with

Do not invent facts. If you can't find something, say so explicitly rather than guessing.
"""


def is_enrichment_available() -> bool:
    return _CLIENT_AVAILABLE and bool(os.environ.get("ANTHROPIC_API_KEY"))


def enrich_lead(company: str, website: str, industry: str) -> str:
    if not is_enrichment_available():
        return (
            "Enrichment disabled — set ANTHROPIC_API_KEY to enable live "
            "account research via web search."
        )

    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": ENRICHMENT_PROMPT.format(
                company=company, website=website, industry=industry or "unknown"
            ),
        }],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_blocks) if text_blocks else "No enrichment result returned."
