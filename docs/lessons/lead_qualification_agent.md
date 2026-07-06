# Lessons — lead qualification agent

Durable decisions made while building this. Not a changelog; the git log has
that.

- **Characterization tests are the compatibility contract.** `test_scoring.py`
  and `test_dataset.py` lock exact scores/tiers (00Q011=98/Hot etc.) and only
  assert `len(reasons) >= 4` — so new reason lines are *appended after* the
  legacy ones and the legacy math is never touched. Any future scoring change
  either preserves those anchors or consciously re-baselines them.
- **Sub-scores derive from legacy points where possible.** `fit_score` and
  `intent_score` are linear rescalings of the same industry/size/source/
  engagement points, so the composite score and the sub-scores can never
  disagree about the same signal.
- **Risk flags are codes + messages, separately.** Evals and the decision tree
  match stable snake_case codes; the UI shows human messages. Messages never
  echo suspicious field content, so an injection payload can't ride a warning
  back into the UI or a prompt.
- **Heuristic hits escalate, never auto-disqualify.** Injection/competitor/
  conflicting-data detection is regex-grade; it routes to `needs_review` +
  `human_review`. Only spam and student leads are auto-`not_fit` — those
  false-positive costs are near zero.
- **Competitor list is exact-match and fictional.** Substring matching would
  flag innocent companies (the mock data contains a lead at "Gong"). Real
  deployments replace `COMPETITOR_NAMES` in `hygiene.py`.
- **The enrichment prompt is contract-tested.** Four numbered sections, no
  line starting `5.`, "Do not invent facts", terse-output clauses. All
  security additions are bulleted, never numbered, to keep the contract.
- **Evals run with zero credentials.** They exercise scoring + hygiene only,
  so CI (and an interviewer) can run them cold: `python3 evals/run_evals.py`.
- **Salesforce constraints:** only the standard `Lead.Rating` field is ever
  written; the Hot/Warm/Cold picklist is verified at runtime before writing;
  `needs_review` leads are skipped on write-back; SOQL omits `__c` behavioral
  fields because a fresh Dev org lacks them (scoring tolerates absence).
- **Uploaded-file caches must key on content.** The original `/tmp` path +
  `st.cache_data(path)` combo served stale rows on re-upload. Cache on bytes.
