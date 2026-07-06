# Architecture — lead_qual_agent

## Module graph

```
app.py ──▶ scoring.py ──▶ hygiene.py ──▶ parsing.py
   │            │
   │            └─(risk flags feed the decision tree)
   ├──▶ hygiene.py (completeness, duplicates, risk flags for the UI)
   ├──▶ enrichment.py ──▶ hygiene.py (injection patterns)
   └──▶ salesforce_client.py
evals/run_evals.py ──▶ scoring.py, hygiene.py   (offline, no creds)
```

Acyclic. `parsing.py` is a leaf (stdlib only). `hygiene.py` imports only
`parsing`. `scoring.py` imports both. `app.py` orchestrates.

## Data flow

1. **Load** — uploaded CSV bytes, Salesforce SOQL (`fetch_leads`, values
   normalized to strings), or `data/mock_leads.csv`. `app.normalize_rows`
   coerces every value to `str` and invents stable `ROW-nnn` ids when `Id`
   is blank.
2. **Score** — `scoring.score_lead(row)` per row, inside a per-row
   try/except (one bad row → stub result + warning, rest continue).
3. **Display** — table of score/tier/label/action/sub-scores, metrics,
   duplicate + cluster warnings, per-lead detail with full rationale.
4. **Act** — optional `Lead.Rating` write-back (clean leads only) and
   optional per-lead research brief via the Anthropic API.

## Scoring model

Two layers, one function:

- **Legacy composite (0–100)** — industry 20 + size 20 + source 20 +
  engagement 40; tier Hot ≥75 / Warm ≥50 / Cold. Locked by
  characterization tests; write-back target.
- **v2 dimensions (each 0–100)** —
  - `fit_score` = (industry + size points) × 2.5
  - `intent_score` = (source + engagement points) ÷ 60 × 100
  - `authority_score` = title keyword buckets (exec 100, VP/head 85,
    director 70, manager 50, IC 30, consultant 25, student 10, unknown 40)
  - `urgency_score` = demo request (+50) + activity recency (+50/+35/+15)
  - `data_confidence_score` = weighted field presence/validity (email 20,
    title 15, company 15, phone/lastname/website/industry/employees 10 each)

## Decision tree (scoring._qualify)

```
1  injection | conflicting | competitor flag ─▶ needs_review / human_review
2  spam | student flag                       ─▶ not_fit / do_not_contact
3  confidence < 40:  high intent or urgency  ─▶ needs_review / human_review
                     otherwise               ─▶ nurture / research_more
4  no email & no phone                       ─▶ nurture / research_more
5  fit≥75 ∧ authority≥60 ∧ strong intent     ─▶ qualified / route_to_sales
6-8 fit/intent combinations                  ─▶ warm / send_personalized_outreach
     (warm + missing firmographics          ─▶ action downgraded to research_more)
9  fit<30 ∧ intent≥60                        ─▶ nurture / research_more
10 fit≥50 ∨ intent≥35                        ─▶ nurture / nurture_sequence
11 otherwise                                 ─▶ not_fit / do_not_contact
```

Ordering is the design: safety rails first (1–4), then opportunity sorting
(5–11). Heuristic detections escalate to a human; only near-zero-false-
positive categories (spam, students) auto-disqualify.

## Extension points

- `hygiene.COMPETITOR_NAMES` — replace the fictional set per deployment.
- ICP constants at the top of `scoring.py`.
- Decision thresholds live only in `_qualify` — one place to tune.
- New risk detectors: add `(_code, detector)` to `hygiene._DETECTORS`.
- New eval cases: append to `evals/lead_qualification_cases.json`; the
  runner and `tests/test_evals.py` pick them up automatically.
