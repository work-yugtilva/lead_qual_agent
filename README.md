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
export ANTHROPIC_API_KEY=your_key_here   # optional — enables live account research
streamlit run app.py
```

Without an API key set, the app still runs — scoring and hygiene
checks work standalone. The research brief button will tell you
enrichment is disabled.

## Scoring model

| Factor | Points | Logic |
|---|---|---|
| Industry fit | 20 | ICP match / adjacent / no match |
| Company size fit | 20 | Within target employee range / adjacent / outside |
| Lead source quality | 20 | Referral > Demo Request > Content Download > Web > Cold List |
| Behavioral engagement + recency | 40 | Demo request, content downloads, page views, days since last activity |

Score maps directly to Salesforce's native `Lead.Rating` picklist:
75+ = Hot, 50-74 = Warm, <50 = Cold.

Adjust the ICP constants at the top of `scoring.py` to match a real
target market.

## Phase 2 — wiring to a live Salesforce org

The mock CSV schema uses real Lead object field API names on purpose
(`Company`, `FirstName`, `LastName`, `Industry`, `NumberOfEmployees`,
`LeadSource`, `Rating`, etc.) so this is a data-source swap, not a
rewrite.

1. **Sign up for a free Salesforce Developer Edition org**
   (developer.salesforce.com) — gives you a real Lead object with
   sample data if you want it.
2. **Create a Connected App** in Setup → App Manager, enable OAuth,
   note the Consumer Key/Secret.
3. **Install `simple-salesforce`**: `pip install simple-salesforce`
4. **Swap the data source**: replace `load_leads()` in `app.py` with
   a SOQL query pull:
   ```python
   from simple_salesforce import Salesforce
   sf = Salesforce(username=..., password=..., security_token=..., consumer_key=..., consumer_secret=...)
   records = sf.query("SELECT Id, FirstName, LastName, Company, Title, Email, Industry, NumberOfEmployees, LeadSource, Website FROM Lead WHERE IsConverted = false")["records"]
   ```
5. **Write scores back**: after scoring, `sf.Lead.update(lead_id, {"Rating": tier})` —
   custom fields (`Score__c`, `Reason_Codes__c`) require adding two
   custom fields to the Lead object first (Setup → Object Manager).
6. **Behavioral fields** (`Requested_Demo__c`, etc.) need to be
   created as custom fields on Lead if you want the engagement score
   to run against real data instead of the mock CSV values.

Budget an extra 4-6 hours for this step — most of it is Salesforce
admin config, not code.

## What this demonstrates in an interview

- You understand the Lead object model, not just "AI can do sales stuff"
- The scoring logic is inspectable and defensible — no black box to get caught out on
- The hygiene layer mirrors actual data-quality problems SDR teams deal with (duplicate leads, incomplete records)
- The architecture was built to plug into a real org from day one, not retrofitted
