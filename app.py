"""
Inbound Lead Qualification + Scoring Agent — dashboard.

Run with: streamlit run app.py

Loads a CSV of leads (Salesforce Lead field names), scores each one,
flags CRM hygiene issues, and lets you drill into an AI-generated
account research brief per lead.
"""

import csv
import streamlit as st
import pandas as pd

from scoring import score_lead
from hygiene import check_completeness, find_duplicates, same_company_clusters
from enrichment import enrich_lead, is_enrichment_available

st.set_page_config(page_title="Lead Qualification Agent", layout="wide")


@st.cache_data
def load_leads(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run_pipeline(rows: list[dict]):
    results = []
    for row in rows:
        score_result = score_lead(row)
        issues = check_completeness(row)
        results.append({
            "Id": row["Id"],
            "Name": f"{row.get('FirstName','')} {row.get('LastName','')}".strip() or "(missing name)",
            "Company": row.get("Company", ""),
            "Title": row.get("Title", ""),
            "Industry": row.get("Industry", ""),
            "Score": score_result.score,
            "Tier": score_result.tier,
            "Reasons": score_result.reasons,
            "Hygiene Issues": issues,
        })
    return results


st.title("Inbound Lead Qualification + Scoring Agent")
st.caption("Rules-based scoring · CRM hygiene checks · AI account research briefs")

uploaded = st.file_uploader("Upload a lead CSV (Salesforce Lead field names)", type="csv")
data_path = None
if uploaded:
    data_path = "/tmp/uploaded_leads.csv"
    with open(data_path, "wb") as f:
        f.write(uploaded.getbuffer())
else:
    data_path = "data/mock_leads.csv"
    st.info("Using bundled mock dataset. Upload your own CSV to override.")

rows = load_leads(data_path)
results = run_pipeline(rows)

df = pd.DataFrame([{
    "Id": r["Id"], "Name": r["Name"], "Company": r["Company"],
    "Title": r["Title"], "Industry": r["Industry"],
    "Score": r["Score"], "Tier": r["Tier"],
    "Hygiene Flags": len(r["Hygiene Issues"]),
} for r in results]).sort_values("Score", ascending=False)

col1, col2, col3 = st.columns(3)
col1.metric("Total Leads", len(results))
col2.metric("Hot Leads", sum(1 for r in results if r["Tier"] == "Hot"))
col3.metric("Hygiene Flags", sum(len(r["Hygiene Issues"]) for r in results))

st.subheader("Scored Leads")
st.dataframe(df, use_container_width=True, hide_index=True)

st.subheader("Duplicate Detection")
dupes = find_duplicates(rows)
if dupes:
    for lead_id, others in dupes.items():
        st.warning(f"Lead {lead_id} duplicates: {', '.join(others)}")
else:
    st.success("No duplicates found.")

clusters = same_company_clusters(rows)
if clusters:
    with st.expander("Multiple contacts at the same account (routing signal, not a dupe)"):
        for company, ids in clusters.items():
            st.write(f"**{company}**: {', '.join(ids)}")

st.subheader("Lead Detail")
selected_id = st.selectbox("Select a lead", [r["Id"] for r in results])
lead = next(r for r in results if r["Id"] == selected_id)
raw_row = next(r for r in rows if r["Id"] == selected_id)

left, right = st.columns(2)

with left:
    st.markdown(f"### {lead['Name']} — {lead['Company']}")
    st.markdown(f"**Score:** {lead['Score']}/100 &nbsp;&nbsp; **Tier:** {lead['Tier']}")
    st.markdown("**Scoring rationale:**")
    for reason in lead["Reasons"]:
        st.write(reason)

    if lead["Hygiene Issues"]:
        st.markdown("**Hygiene issues:**")
        for issue in lead["Hygiene Issues"]:
            st.write(f"⚠️ {issue}")
    else:
        st.markdown("**Hygiene:** ✅ Record complete")

with right:
    st.markdown("### Account Research Brief")
    if not is_enrichment_available():
        st.warning("Set ANTHROPIC_API_KEY to enable live research.")
    if st.button("Generate research brief", key=f"enrich_{selected_id}"):
        with st.spinner("Researching account..."):
            brief = enrich_lead(
                raw_row.get("Company", ""),
                raw_row.get("Website", ""),
                raw_row.get("Industry", ""),
            )
        st.markdown(brief)
