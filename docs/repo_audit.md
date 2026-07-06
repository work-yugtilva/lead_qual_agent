# Repo Audit — lead_qual_agent

Audit performed 2026-07-05 against commit `bdbea69` (before the v2 upgrade in
this session). Each gap notes whether the session addressed it.

## 1. What the app does

Streamlit dashboard for inbound lead qualification. Loads leads from an
uploaded CSV, a live Salesforce org (OAuth client-credentials), or a bundled
40-row mock CSV. Scores each lead 0–100 with a deterministic four-factor
model (industry 20, company size 20, lead source 20, engagement+recency 40),
maps the score to Salesforce's native `Lead.Rating` picklist (Hot ≥75,
Warm ≥50, Cold <50), flags hygiene issues (incomplete records, duplicates,
same-company clusters), and generates an AI account-research brief per lead
via the Anthropic API with web search.

## 2. Already strong

- Deterministic, explainable scoring — every point traceable to a named rule.
- Characterization tests locking exact scores, tiers, and boundary behavior
  (75/74, 50/49) plus hand-computed anchors in the mock dataset.
- Live Salesforce integration done right for a demo: OAuth client-credentials
  (not the dead username/password flow), runtime picklist verification, no
  custom fields, round-trip write-back test that restores state.
- Graceful degradation: app runs with no credentials at all.
- Mock dataset deliberately planted with duplicates, incomplete rows, and
  boundary scores that the tests exercise.

## 3. What was missing

| Gap | Addressed this session |
|---|---|
| No qualification decision (score only — no label, no next action) | ✅ 5 labels + 6 recommended actions + decision tree |
| No authority/urgency/data-confidence dimensions | ✅ three new 0–100 sub-scores |
| `int(employees)` crashes on `"1,200"` / `"N/A"` | ✅ `parsing.py` safe helpers |
| No risk detection (spam, students, competitors, injection) | ✅ 9 detectors in `hygiene.py` |
| No prompt-injection defense in the enrichment prompt | ✅ hardened prompt + pre-screen refusal |
| No error handling around the Anthropic call — API failure crashed the UI | ✅ typed exception handling, clean messages |
| Upload cache bug: fixed `/tmp` path + path-keyed cache served stale rows | ✅ bytes-keyed cache |
| One bad row killed the whole pipeline | ✅ per-row try/except with error surfacing |
| Missing `Id` broke duplicates + detail view | ✅ stable `ROW-nnn` fallback ids |
| Write-back wrote every lead, including suspicious ones | ✅ needs_review leads skipped with a warning |
| No evals | ✅ 18-case offline eval suite + runner |
| pytest and requests undeclared | ✅ `requirements-dev.txt`, `requests` pinned |
| No docs beyond README | ✅ audit, architecture, security review, lessons |

## 4. Product gaps (pre-upgrade)

- Score without a verdict: an SDR still had to decide what to *do* with a 62.
- No guardrail between "model scored it" and "wrote it into the CRM".
- No treatment of junk/hostile input, which is most of real inbound.

## 5. Engineering gaps (pre-upgrade)

- Brittle parsing (crash on the first real-world CSV export).
- No error handling anywhere in `app.py` or `enrichment.py`.
- Test tooling undeclared; no dev-dependency story; no conftest.

## 6. Security risks (pre-upgrade)

- Lead fields flowed unfiltered into an LLM prompt with web-search enabled —
  classic indirect prompt-injection surface.
- API errors could bubble raw exception content into the UI.
- No detection of hostile text stored in the CRM.
- (Not a gap: `.env` was already gitignored and credentials were env-only.)

## 7. Agent/evaluation gaps (pre-upgrade)

- No eval harness; nothing pinned the *decisions* (only the arithmetic).
- No adversarial cases (injection, spam, competitor, conflicting data).
- No needs-human-review escape hatch — every lead got an automated verdict.

## 8. Improvement order used

1. `parsing.py` — safe parsing (everything else depends on it).
2. `hygiene.py` — risk-flag detectors (scoring consumes them).
3. `scoring.py` — sub-scores, labels, actions, decision tree.
4. `enrichment.py` — prompt hardening + error handling.
5. `app.py` — richer UI, resilience, safe write-back.
6. `evals/` — 18 offline cases + runner.
7. Tests + dev setup.
8. Docs.

Rationale: bottom-up along the import graph, keeping every intermediate
state green against the characterization tests.
