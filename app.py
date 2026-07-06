"""
Inbound Lead Qualification + Scoring Agent — dashboard.

Run with: streamlit run app.py

Loads leads (uploaded CSV, live Salesforce, or the bundled mock CSV),
scores each one across five dimensions, assigns a qualification label
and recommended action, flags CRM hygiene and risk issues, and lets
you drill into an AI-generated account research brief per lead.
"""

import csv
import io
import os

import streamlit as st
import pandas as pd

from scoring import score_lead
from hygiene import (
    check_completeness, detect_risk_flags,
    find_duplicates, same_company_clusters,
)
from enrichment import enrich_lead, is_enrichment_available
from salesforce_client import (
    is_salesforce_configured, fetch_leads as sf_fetch_leads,
    update_rating, get_rating_picklist_values,
)

st.set_page_config(page_title="Lead Qualification Agent", layout="wide")


@st.cache_data
def load_leads(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@st.cache_data
def load_leads_from_bytes(data: bytes) -> list[dict]:
    # Bytes are the cache key, so re-uploading a different file with the
    # same name can never serve stale rows.
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


@st.cache_data(ttl=300)
def load_leads_from_salesforce() -> list[dict]:
    return sf_fetch_leads()


_MD_SPECIALS = set("\\`*_{}[]()#+!|<>")


def md_escape(value) -> str:
    """Neutralize Markdown so lead-controlled text renders as literal text.

    Streamlit escapes HTML by default, but Markdown links/images still render —
    a hostile Company like "![x](https://evil/beacon)" would auto-fetch an
    attacker URL when a rep opens the lead. Escape before any st.markdown/
    st.write interpolation of lead-derived strings.
    """
    return "".join("\\" + ch if ch in _MD_SPECIALS else ch for ch in str(value))


def normalize_rows(rows: list[dict]) -> list[dict]:
    """Coerce every value to a string and guarantee a stable, unique Id."""
    normalized = []
    for i, row in enumerate(rows):
        clean = {k: ("" if v is None else str(v)) for k, v in row.items() if k is not None}
        if not clean.get("Id", "").strip():
            clean["Id"] = f"ROW-{i + 1:03d}"
        normalized.append(clean)
    return normalized


def _error_stub(row: dict, index: int, exc: Exception) -> dict:
    return {
        "Id": row.get("Id") or f"ROW-{index + 1:03d}",
        "Name": "(row failed)", "Company": row.get("Company", ""),
        "Title": row.get("Title", ""), "Industry": row.get("Industry", ""),
        "Score": 0, "Tier": "Cold",
        "Qualification Label": "needs_review", "Recommended Action": "human_review",
        "Needs Review": True,
        "Fit": 0, "Intent": 0, "Authority": 0, "Urgency": 0, "Data Confidence": 0,
        "Reasons": [f"Pipeline error on this row: {type(exc).__name__}: {exc}"],
        "Missing Fields": [], "Risk Flags": {}, "Hygiene Issues": [],
    }


def run_pipeline(rows: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Score every row. One bad row surfaces its error and never stops the rest."""
    results, errors = [], []
    for i, row in enumerate(rows):
        try:
            s = score_lead(row)
            results.append({
                "Id": row["Id"],
                "Name": f"{row.get('FirstName', '')} {row.get('LastName', '')}".strip() or "(missing name)",
                "Company": row.get("Company", ""),
                "Title": row.get("Title", ""),
                "Industry": row.get("Industry", ""),
                "Score": s.score, "Tier": s.tier,
                "Qualification Label": s.qualification_label,
                "Recommended Action": s.recommended_action,
                "Needs Review": s.needs_human_review,
                "Fit": s.fit_score, "Intent": s.intent_score,
                "Authority": s.authority_score, "Urgency": s.urgency_score,
                "Data Confidence": s.data_confidence_score,
                "Reasons": s.reasons,
                "Missing Fields": s.missing_fields,
                "Risk Flags": detect_risk_flags(row),
                "Hygiene Issues": check_completeness(row),
            })
        except Exception as e:
            errors.append((row.get("Id", f"row {i + 1}"), f"{type(e).__name__}: {e}"))
            results.append(_error_stub(row, i, e))
    return results, errors


st.title("Inbound Lead Qualification + Scoring Agent")
st.caption("Rules-based scoring · qualification labels · CRM hygiene · AI account research briefs")

uploaded = st.file_uploader("Upload a lead CSV (Salesforce Lead field names)", type="csv")
if uploaded:
    rows = load_leads_from_bytes(bytes(uploaded.getbuffer()))
    source = "csv"
    st.info("Using uploaded CSV.")
elif is_salesforce_configured():
    rows = load_leads_from_salesforce()
    source = "salesforce"
    st.info(f"Connected to Salesforce — {len(rows)} unconverted leads loaded.")
else:
    rows = load_leads(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mock_leads.csv"))
    source = "csv"
    st.info("Using bundled mock dataset. Upload a CSV or set SF_* env vars to override.")

rows = normalize_rows(rows)
results, row_errors = run_pipeline(rows)

if row_errors:
    st.warning(
        f"{len(row_errors)} row(s) failed scoring and were marked needs_review: "
        + ", ".join(f"{md_escape(rid)} ({md_escape(msg)})" for rid, msg in row_errors)
    )

df = pd.DataFrame([{
    "Id": r["Id"], "Name": r["Name"], "Company": r["Company"], "Title": r["Title"],
    "Score": r["Score"], "Tier": r["Tier"],
    "Qualification Label": r["Qualification Label"],
    "Recommended Action": r["Recommended Action"],
    "Needs Review": r["Needs Review"],
    "Fit": r["Fit"], "Intent": r["Intent"], "Authority": r["Authority"],
    "Urgency": r["Urgency"], "Data Confidence": r["Data Confidence"],
    "Hygiene Flags": len(r["Hygiene Issues"]) + len(r["Risk Flags"]),
} for r in results]).sort_values("Score", ascending=False)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Leads", len(results))
col2.metric("Qualified", sum(1 for r in results if r["Qualification Label"] == "qualified"))
col3.metric("Hot Leads", sum(1 for r in results if r["Tier"] == "Hot"))
col4.metric("Needs Review", sum(1 for r in results if r["Needs Review"]))
col5.metric("Hygiene Flags", sum(len(r["Hygiene Issues"]) + len(r["Risk Flags"]) for r in results))

st.subheader("Scored Leads")
st.dataframe(df, use_container_width=True, hide_index=True)

if source == "salesforce":
    st.subheader("Salesforce Write-back")
    clean = [r for r in results if not r["Needs Review"]]
    flagged = [r for r in results if r["Needs Review"]]
    if flagged:
        st.warning(
            f"{len(flagged)} lead(s) are flagged for human review and will be "
            f"skipped: {', '.join(r['Id'] for r in flagged)}"
        )
    if st.button("Write tiers to Lead.Rating"):
        try:
            picklist = get_rating_picklist_values()
        except Exception as e:
            picklist = None
            st.error(
                f"Could not verify the Lead.Rating picklist "
                f"({type(e).__name__}) — nothing written."
            )
        if picklist is not None:
            missing = {"Hot", "Warm", "Cold"} - picklist
            if missing:
                st.error(f"Lead.Rating picklist missing values {missing} — nothing written.")
            else:
                updated, failed = 0, []
                with st.spinner("Updating Lead.Rating..."):
                    for r in clean:
                        try:
                            update_rating(r["Id"], r["Tier"])
                            updated += 1
                        except Exception as e:
                            failed.append((r["Id"], type(e).__name__))
                st.success(f"Updated Rating on {updated} leads.")
                if failed:
                    st.error(
                        f"Failed to update {len(failed)} lead(s): "
                        + ", ".join(f"{md_escape(i)} ({n})" for i, n in failed)
                    )
                if flagged:
                    st.warning(f"Skipped {len(flagged)} lead(s) flagged for human review.")

st.subheader("Duplicate Detection")
dupes = find_duplicates(rows)
if dupes:
    for lead_id, others in dupes.items():
        st.warning(f"Lead {md_escape(lead_id)} duplicates: {md_escape(', '.join(others))}")
else:
    st.success("No duplicates found.")

clusters = same_company_clusters(rows)
if clusters:
    with st.expander("Multiple contacts at the same account (routing signal, not a dupe)"):
        for company, ids in clusters.items():
            st.write(f"**{md_escape(company)}**: {md_escape(', '.join(ids))}")

st.subheader("Lead Detail")
selected_id = st.selectbox("Select a lead", [r["Id"] for r in results])
lead = next(r for r in results if r["Id"] == selected_id)
raw_row = next(r for r in rows if r["Id"] == selected_id)

left, right = st.columns(2)

with left:
    st.markdown(f"### {md_escape(lead['Name'])} — {md_escape(lead['Company'])}")
    st.markdown(
        f"**Score:** {lead['Score']}/100 &nbsp;&nbsp; **Tier:** {lead['Tier']} &nbsp;&nbsp; "
        f"**Label:** `{lead['Qualification Label']}` &nbsp;&nbsp; "
        f"**Action:** `{lead['Recommended Action']}`"
    )
    if lead["Needs Review"]:
        st.error(
            "This lead needs human review before any automated outreach or "
            "write-back — see the risk flags and decision rationale below."
        )

    st.markdown("**Scoring rationale:**")
    for reason in lead["Reasons"]:
        st.write(md_escape(reason))

    if lead["Missing Fields"]:
        st.markdown(f"**Missing fields:** {', '.join(lead['Missing Fields'])}")

    if lead["Risk Flags"]:
        st.markdown("**Risk flags:**")
        for code, message in lead["Risk Flags"].items():
            st.write(f"🚩 `{code}` — {message}")

    if lead["Hygiene Issues"]:
        st.markdown("**Hygiene issues:**")
        for issue in lead["Hygiene Issues"]:
            st.write(f"⚠️ {issue}")
    elif not lead["Risk Flags"]:
        st.markdown("**Hygiene:** ✅ Record complete")

with right:
    st.markdown("### Account Research Brief")
    if not is_enrichment_available():
        st.warning("Set ANTHROPIC_API_KEY to enable live research.")
    if "prompt_injection_suspected" in lead["Risk Flags"]:
        st.error(
            "Prompt-injection-like text detected in this lead's fields. "
            "Enrichment will refuse to send this record to the model."
        )
    if st.button("Generate research brief", key=f"enrich_{selected_id}"):
        with st.spinner("Researching account..."):
            brief = enrich_lead(
                raw_row.get("Company", ""),
                raw_row.get("Website", ""),
                raw_row.get("Industry", ""),
            )
        st.text(brief)
