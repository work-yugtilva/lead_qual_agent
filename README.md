# Inbound Lead Qualification + Scoring Agent

Automates the workflow an SDR intern does manually in week one: score
inbound leads, decide what to do with each one, flag CRM hygiene and
risk issues, and generate an account research brief — before a rep
ever touches the record.

Every lead gets a 0–100 score, a Hot/Warm/Cold tier (write-back-ready
for Salesforce `Lead.Rating`), five explainable sub-scores, a
**qualification label**, and a **recommended action** — with suspicious
records (prompt injection, competitors, conflicting data) routed to a
human instead of an automated verdict.

## Why rules-based scoring, not ML

There's no historical conversion data to train a model on. A
deterministic, weighted scoring system is fully transparent — every
point is traceable to a named rule (`scoring.py`) — and it's what
most real SDR tooling actually runs before there's enough labeled
data to justify anything predictive. The same property makes the
system evaluable: `evals/` pins 18 decision behaviors and runs with no
credentials.

## Architecture

```
data/mock_leads.csv    → 40 mock leads, real Salesforce Lead field API names
parsing.py             → safe parsing for messy CRM values ("1,200", "N/A", None)
hygiene.py             → duplicates, completeness, 9 risk-flag detectors
scoring.py             → composite score + 5 sub-scores + decision tree
enrichment.py          → account research via Anthropic API + web search (hardened)
salesforce_client.py   → OAuth client-credentials; Lead query + Rating write-back
app.py                 → Streamlit dashboard tying it together
evals/                 → 18 offline eval cases + runner
```

See `docs/architecture.md` for the module graph and the full decision
tree, and `docs/security_review.md` for the threat model.

## Scoring model

**Composite score (0–100)** — maps to `Lead.Rating`: 75+ = Hot,
50–74 = Warm, <50 = Cold.

| Factor | Points | Logic |
|---|---|---|
| Industry fit | 20 | ICP match / adjacent / no match |
| Company size fit | 20 | Within target employee range / adjacent / outside |
| Lead source quality | 20 | Referral > Demo Request > Content Download > Web > Cold List |
| Behavioral engagement + recency | 40 | Demo request, content downloads, page views, days since last activity |

**Sub-scores (each 0–100, all explainable in the lead detail view):**

| Dimension | Signal |
|---|---|
| Fit | Industry + company size vs ICP |
| Intent | Lead source + engagement behavior |
| Authority | Title seniority (exec 100 → VP 85 → director 70 → manager 50 → IC 30 → student 10) |
| Urgency | Demo request + activity recency |
| Data confidence | Field presence/validity (email, phone, title, firmographics…) |

The ICP constants at the top of `scoring.py` hold the confirmed
targeting values (Technology + Financial Services primary; Healthcare +
Retail adjacent; 100–1500 employees, 50–3000 adjacent).

## Qualification labels and recommended actions

| Label | Meaning | Typical action |
|---|---|---|
| `qualified` | Strong fit + intent + authority + confidence | `route_to_sales` |
| `warm` | Good fit, missing one ingredient | `send_personalized_outreach` or `research_more` |
| `nurture` | Plausible future lead, low buying intent | `nurture_sequence` or `research_more` |
| `not_fit` | Outside ICP, spam, or student | `do_not_contact` |
| `needs_review` | Suspicious or too incomplete to trust | `human_review` |

Safety rails run before opportunity sorting: prompt-injection,
competitor, and conflicting-data flags always escalate to
`needs_review` (heuristics may be wrong — a human decides); leads
flagged for review are **excluded from Salesforce write-back**.

## Setup

```bash
pip install -r requirements.txt        # app
pip install -r requirements-dev.txt    # + pytest, for tests/evals
cp .env.example .env         # then fill in your keys (file is gitignored)
set -a; source .env; set +a  # load env vars for this shell
```

All credentials come from environment variables only — see
`.env.example` for the full list. Everything is optional: without
`ANTHROPIC_API_KEY` the research-brief button reports enrichment is
disabled; without the `SF_*` variables the app runs standalone on the
bundled 40-row mock dataset.

**Environment variables:** `ANTHROPIC_API_KEY` (enrichment),
`SF_CONSUMER_KEY` / `SF_CONSUMER_SECRET` / `SF_INSTANCE_URL`
(Salesforce; all three required to enable live mode).

## Running

```bash
streamlit run app.py             # the dashboard
python3 -m pytest tests/ -q      # tests (Salesforce tests skip without creds)
python3 evals/run_evals.py       # 18 offline eval cases; exit 1 on any failure
```

The evals run the real scoring + hygiene pipeline against adversarial
and boundary cases (injection payloads, competitors, spam, missing
fields, conflicting firmographics) and check labels, score ranges,
review routing, required reasons, and forbidden output. No network, no
credentials.

## Salesforce integration

The app pulls unconverted Leads from a live org via `salesforce_client.py`
(simple-salesforce, OAuth 2.0 **Client Credentials Flow** through a Connected
App) and can write each lead's tier back to the standard `Lead.Rating`
picklist. Client credentials is a server-to-server flow — the app
authenticates as the Connected App itself, with no user password or security
token. The legacy OAuth username-password flow (and SOAP login) is
hard-disabled in orgs created Summer '23 or later, which is why this flow is
used.

**Connected App setup** (one time): in OAuth Settings check **Enable Client
Credentials Flow**, then Manage → Edit Policies → Client Credentials Flow → set
a **Run-As user**.

**Data-source order in the app:** uploaded CSV → Salesforce (when all three
`SF_*` vars are set) → bundled mock CSV. Standalone mode always works.

**Write-back:** the "Write tiers to Lead.Rating" button appears in
Salesforce mode. It verifies at runtime that the Rating picklist
actually contains Hot/Warm/Cold before writing anything, and skips any
lead flagged `needs_review` (the UI reports how many were skipped). No
custom fields are created — `Score__c`/`Reason_Codes__c` were
deliberately skipped (schema changes on the org are a human decision).

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

## Security notes

- Lead fields are treated as hostile input end to end: risk detectors
  flag injection-like text, `enrich_lead` refuses to send flagged
  content to the model, and the enrichment prompt wraps lead data in
  `<lead_data>` tags with explicit untrusted-data rules.
- API keys and Salesforce credentials are env-only; error paths return
  static messages (never exception bodies, never secrets).
- Risk-flag messages never echo suspicious field content back into the
  UI or prompts.
- Full review in `docs/security_review.md`.

## Known limitations

- Injection/spam/competitor detection is regex-grade and English-only —
  it's a warning layer, not a guarantee; the hardened prompt is the
  real defense.
- `COMPETITOR_NAMES` in `hygiene.py` is a fictional placeholder set.
- No auth on the Streamlit app itself — run locally or behind a proxy.
- Scoring weights are hand-set, not learned; no conversion feedback loop.
- Urgency detection is limited to demo requests + recency (the Lead
  schema has no free-text notes field to mine for urgent language).

## Roadmap

1. Activity-history integration (Tasks/Events) for real engagement data.
2. Feedback loop: record SDR accept/reject per label to tune thresholds.
3. Owner assignment + round-robin routing on `route_to_sales`.
4. Batch enrichment with caching instead of per-lead button clicks.
5. Lockfile + CI workflow running tests and evals on every push.

## What this demonstrates in an interview

- You understand the Lead object model, not just "AI can do sales stuff"
- The scoring logic is inspectable and defensible — no black box to get caught out on
- The decisions are evaluated, not vibes: 18 adversarial/boundary evals run offline and are enforced by the test suite
- Hostile input is handled where it actually enters (CRM fields → LLM prompt)
- The architecture was built to plug into a real org from day one, not retrofitted
