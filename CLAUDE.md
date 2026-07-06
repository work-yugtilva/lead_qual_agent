# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python3 -m pytest -q                       # full suite (Salesforce tests skip without SF_* creds — expected)
python3 -m pytest tests/test_scoring_v2.py -q          # one file
python3 -m pytest -q -k test_authority_buckets          # one test
python3 evals/run_evals.py                 # 18 offline eval cases; exit 1 on any failure; no creds/network
streamlit run app.py                       # dashboard; works with zero credentials on the bundled mock CSV
pip install -r requirements-dev.txt        # app deps + pytest
```

Run tests AND evals after touching `scoring.py`, `hygiene.py`, or `enrichment.py` — the suite is a behavioral contract, not just coverage.

## Architecture

Import graph (acyclic): `app.py → scoring.py → hygiene.py → parsing.py`; `app.py` also imports `hygiene.py`, `enrichment.py`, and `salesforce_client.py` directly. `evals/run_evals.py` exercises scoring + hygiene only.

`scoring.score_lead()` has two layers in one function:

- **Legacy composite (0–100)**: industry 20 + size 20 + source 20 + engagement 40; tier Hot ≥75 / Warm ≥50 / Cold. This is the Salesforce `Lead.Rating` write-back value.
- **v2 layer**: `fit_score`/`intent_score` are linear rescalings of the same legacy points (they can never disagree with the composite); `authority`/`urgency`/`data_confidence` are independent 0–100 sub-scores; `_qualify()` is the decision tree producing `qualification_label` + `recommended_action` + `needs_human_review`. Safety rails run before opportunity sorting: injection/competitor/conflicting-data flags → `needs_review`; spam/student → `not_fit`.

Risk flags: `hygiene.detect_risk_flags(row)` returns `{snake_case_code: message}`. Evals and the decision tree match **codes**; the UI shows **messages**; messages never echo field content (anti-re-injection).

## Hard constraints (violating these breaks tests)

- **Legacy scoring is a locked characterization contract.** `tests/test_dataset.py` pins exact anchors (00Q011=98/Hot, 00Q021=75/Hot, 00Q022=50/Warm, 00Q023=49/Cold, 00Q040=0/Cold); `tests/test_scoring.py` pins tier boundaries and factor math. Never change legacy point values, reason strings, or their order. New reason lines are appended after the legacy ones; the `[decision]` line stays last.
- **`enrichment.ENRICHMENT_PROMPT` is contract-tested**: the four numbered section headers must remain, no line may start with `5.`, and the literals "Do not invent facts" / "ONLY the four numbered sections" / "no preamble" must stay. Add any new prompt text as bullets, never numbered items.
- **`data/mock_leads.csv` must trigger zero serious risk flags** (guard test in `tests/test_risk_flags.py`). Rows 00Q011/00Q031 are at "Gong" and must stay `qualified` — `hygiene.COMPETITOR_NAMES` is fictional and exact-match only; never add entries that collide with mock data.
- **Salesforce**: only the standard `Lead.Rating` field is ever written, the Hot/Warm/Cold picklist is verified at runtime first, and `needs_review` leads are skipped on write-back. Never create custom fields.
- **Lead-derived strings rendered in `app.py` go through `md_escape()`** (Markdown link/image injection is the live UI vector; HTML is already escaped by Streamlit). `enrich_lead` refuses injection-flagged inputs before any API call.

## Conventions

- `parsing.py` is a leaf module (stdlib only). Use `parse_int_safe`/`parse_float_safe`/`text()` on row values instead of `int()`/`.strip()` — CRM values include `None`, `"1,200"`, `"N/A"`, `"-"`, and the pipeline must never raise on them.
- New risk detector: append `(code, fn)` to `hygiene._DETECTORS`, message must not echo field content; add an eval case plus a false-positive guard.
- New eval case: append to `evals/lead_qualification_cases.json` — the runner and `tests/test_evals.py` pick it up automatically. `must_include_risk_flags` matches codes exactly; `must_include_reasons` is a case-insensitive substring of the joined reasons.
- Decision thresholds live only in `scoring._qualify`; ICP targeting constants at the top of `scoring.py`.
- `conftest.py` + `pytest.ini` make the suite location-independent (chdir to repo root per test); tests may open `data/mock_leads.csv` relatively.
