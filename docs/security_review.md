# Security Review — lead_qual_agent

Reviewed 2026-07-05, covering the v2 upgrade. Threat model: a hostile
stranger controls every lead field (anyone can type anything into a web form
that lands in the CRM), and the operator's Anthropic + Salesforce credentials
must never leak.

## API key handling

- `ANTHROPIC_API_KEY` is read from the environment only (`enrichment.py`).
  Never written to disk, never interpolated into messages or logs.
- Enrichment failure messages are static strings plus at most the exception
  class name / HTTP status — never the exception body, which can contain
  request metadata.

## Salesforce credentials

- `SF_CONSUMER_KEY` / `SF_CONSUMER_SECRET` / `SF_INSTANCE_URL` are env-only.
- OAuth client-credentials flow; token errors surface only the OAuth
  `error`/`error_description` fields, not the request payload
  (`salesforce_client.py:get_connection`).

## .env and .gitignore

- `.env` exists locally, is gitignored, and is not tracked
  (`git check-ignore .env` passes; `git ls-files` does not list it).
- `.env.example` documents variable names with no real values.
- `.streamlit/secrets.toml` is also gitignored.

## Prompt injection

Attack path: hostile text in Company/Website/Industry → enrichment prompt →
model with web-search tool. Defenses, in order:

1. **Detection** — `hygiene.INJECTION_PATTERNS` (narrow multi-word patterns:
   "ignore previous instructions", role tags, "system prompt", credential
   requests). A hit sets `prompt_injection_suspected`, routes the lead to
   `needs_review`, and the UI warns.
2. **Refusal** — `enrichment.enrich_lead` pre-screens its three inputs with
   the same patterns and refuses to call the model on a hit.
3. **Prompt hardening** — lead fields are wrapped in `<lead_data>` tags; the
   prompt instructs the model to treat them as untrusted data, never follow
   instructions inside them, never reveal system/API/secret information, and
   to report suspected injection instead of researching it.

Residual risk (accepted for an MVP): the regex layer is best-effort — novel
phrasings and non-English payloads will bypass it and reach the hardened
prompt, which is the real defense. The model's web-search results are also
untrusted content; the same prompt rules apply to them, but a sufficiently
capable indirect injection via a searched page remains possible. Mitigation:
briefs are advisory text shown to a human; nothing from a brief is executed
or written to Salesforce.

## Enrichment failure handling

Every failure path returns a clean message: missing key → disabled notice;
auth/timeout/connection/status errors → typed messages; anything else →
`unexpected <ClassName>`. No stack traces reach the UI (`enrichment.py`).

## Raw lead data exposure

- Risk-flag messages never echo field content (`hygiene.py` detectors).
- Lead values are rendered in the Streamlit UI via `st.write`/`st.markdown`;
  Streamlit escapes HTML by default (no `unsafe_allow_html`), so script
  injection is not possible. Markdown links/images are the remaining vector —
  a hostile Company like `![x](https://evil/beacon)` would auto-fetch an
  attacker URL when a rep opens the lead — so every lead-derived string is
  passed through `app.md_escape` before rendering, and research briefs
  (model output) render as plain text via `st.text`.

## Salesforce write-back risks

- Only the standard `Lead.Rating` field is written; values restricted to
  Hot/Warm/Cold and the picklist is verified at runtime first.
- Leads flagged `needs_human_review` are excluded from write-back and the UI
  says how many were skipped.
- No custom fields are created or written.
- Picklist verification and each `update_rating` call are wrapped in
  try/except: a describe failure writes nothing; a mid-loop update failure
  is reported per lead (id + exception class) instead of crashing with a
  partial write and a raw traceback.
- Blast radius of a bad run: wrong Rating values on unconverted leads —
  visible, reversible, and no data is deleted.

## Dependency risk

Five direct dependencies (streamlit, pandas, anthropic, simple-salesforce,
requests), all mainstream and pinned to minimum versions. No lockfile — a
supply-chain compromise of a new release would be picked up by a fresh
install; acceptable for an MVP, use a lockfile before production.

## Remaining MVP limitations

- Injection heuristics are English-only and pattern-based: non-English
  payloads, base64-encoded instructions, and novel phrasings bypass the
  regex layer and reach the hardened prompt, which is the actual defense.
- No rate limiting or audit log around Salesforce writes.
- No authentication on the Streamlit app itself — anyone who can reach it
  can trigger enrichment calls (cost) and write-backs. Run it locally or
  behind auth.
- Uploaded CSVs are parsed in-process with the stdlib csv module (no size
  cap beyond Streamlit's 200 MB default).
