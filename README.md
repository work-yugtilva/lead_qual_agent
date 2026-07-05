# Inbound Lead Qualification + Scoring Agent

Automates the workflow an SDR intern does manually in week one: score
inbound leads, flag CRM hygiene issues, and generate an account
research brief — before a rep ever touches the record.

## Why rules-based scoring, not ML

There's no historical conversion data to train a model on. A
deterministic, weighted scoring system is fully transparent — every
point is traceable to a named rule (`scoring.py`) — and it's what
most real SDR tooling actually runs before there's enough labeled
data to justify anything predictive.

## Architecture

```
data/mock_leads.csv   → mock leads, using real Salesforce Lead field API names
scoring.py             → rules-based scoring engine (100 pts, 4 weighted factors)
hygiene.py              → duplicate detection + field completeness checks
enrichment.py           → account research via Anthropic API + web search
app.py                  → Streamlit dashboard tying it together
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env         # then fill in your keys (file is gitignored)
set -a; source .env; set +a  # load env vars for this shell
python3 -m pytest tests/ -q  # sanity checks (Salesforce tests skip without creds)
streamlit run app.py
```

All credentials come from environment variables only — see
`.env.example` for the full list. Everything is optional: without
`ANTHROPIC_API_KEY` the research-brief button reports enrichment is
disabled; without the `SF_*` variables the app runs standalone on the
bundled 40-row mock dataset (`data/mock_leads.csv`).

## Scoring model

| Factor | Points | Logic |
|---|---|---|
| Industry fit | 20 | ICP match / adjacent / no match |
| Company size fit | 20 | Within target employee range / adjacent / outside |
| Lead source quality | 20 | Referral > Demo Request > Content Download > Web > Cold List |
| Behavioral engagement + recency | 40 | Demo request, content downloads, page views, days since last activity |

Score maps directly to Salesforce's native `Lead.Rating` picklist:
75+ = Hot, 50-74 = Warm, <50 = Cold.

The ICP constants at the top of `scoring.py` hold the confirmed
targeting values (Technology + Financial Services primary; Healthcare +
Retail adjacent; 100-1500 employees, 50-3000 adjacent).

## Salesforce integration (Phase 2 — implemented)

The app pulls unconverted Leads from a live org via `salesforce_client.py`
(simple-salesforce, OAuth username-password flow through a Connected App)
and can write each lead's tier back to the standard `Lead.Rating` picklist.

**Environment variables** (put them in `.env` — never committed):
`SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`, `SF_CONSUMER_KEY`,
`SF_CONSUMER_SECRET`, plus `ANTHROPIC_API_KEY` for enrichment.

**Data-source order in the app:** uploaded CSV → Salesforce (when all
`SF_*` vars are set) → bundled mock CSV. Standalone mode always works.

**Write-back:** the "Write tiers to Lead.Rating" button appears in
Salesforce mode. It verifies at runtime that the Rating picklist
actually contains Hot/Warm/Cold before writing anything. No custom
fields are created — `Score__c`/`Reason_Codes__c` were deliberately
skipped (schema changes on the org are a human decision).

**Behavioral fields:** the SOQL deliberately omits the
`Requested_Demo__c`-style custom fields — a fresh Developer Edition org
doesn't have them, and scoring tolerates their absence (those factors
score 0). Create them on Lead if you want engagement scoring against
live data.

**Integration tests** (run against a real Dev org; they skip cleanly
when credentials are absent):

```bash
set -a; source .env; set +a
python3 -m pytest tests/test_salesforce_integration.py -q
```

The suite proves a round-trip query returns the expected fields and
that a Rating write-back actually persists (update → re-query → assert
→ restore).

## What this demonstrates in an interview

- You understand the Lead object model, not just "AI can do sales stuff"
- The scoring logic is inspectable and defensible — no black box to get caught out on
- The hygiene layer mirrors actual data-quality problems SDR teams deal with (duplicate leads, incomplete records)
- The architecture was built to plug into a real org from day one, not retrofitted
