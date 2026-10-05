# AGENT.md — Vireo Audio CSAT dashboard

## Goal
A small Streamlit dashboard for Vireo's Head of CX (Priya). It shows CSAT per agent,
handle time per agent, flags the bottom ten, and marks the top five. Nothing else.
Keep it simple. Do not over-engineer.

## Stack and run instructions
- Python 3.10+, pandas, streamlit. Add plotly only if a chart really needs it.
- Create a virtual environment (`.venv`) and a `requirements.txt` with pinned-minimum versions.
- A reviewer must be able to run it with:
    python -m venv .venv
    (activate it)
    pip install -r requirements.txt
    streamlit run app.py
- Write a short README.md with exactly those steps.

## Data
- Default: load tickets.csv and agents.csv from the `data/` folder automatically.
- Sidebar: optional file uploaders for tickets.csv and agents.csv. If a file is uploaded, u
se
  it instead of the default. The app must work with no clicks on first load.
- Source of truth for definitions: data/support-policy.pdf and data/README.txt.
  Read them and the email thread before coding.

## Required features (and ONLY these)
1. Per-agent table: agent_id, name, team, tier, avg CSAT, number of CSAT responses,
   avg handle time, tickets handled.
2. Bottom ten by CSAT highlighted.
3. Top five by CSAT marked (Diwali bonus).
4. An "Assumptions" section on the page that lists the decisions made.
5. A note/tag on agents in Tier 2 or the hardware triage rota: "Difficult queue, compare with care".

## Rules (these come from traps in the data — follow them)
- Join agents on `agent_id`, never on name (two agents share a display name).
- A blank csat_score means no response. Exclude from averages. Never treat as 0.
- Handle time = first_response_at to resolved_at. Exclude tickets with no resolution or no first response.
- Dedupe tickets that appear under both source_system values (legacy re-imports). Decide and document the rule.
- Legacy (legacy_fd) resolved_at was reconstructed from UTC logs; helpdesk timestamps are IST.
  Check the data, correct the offset for legacy tickets, and document it. Sanity check: handle times must not be negative.
- Roster has multiple rows per agent. Pick a simple documented way to get one team/tier per agent.
- Rank only agents with at least N CSAT responses (make N a sidebar slider, default 20). Show others as "insufficient data".
- Rank Tier 1 and Tier 2 separately; policy says do not compare them on volume metrics.
- Ignore junk IVR transcripts in customer_message. That is a phone-system fault, not agent-related.

## Out of scope — do NOT build
Refund/replacement analysis, lot-code analysis, cost modelling, per-ticket LLM calls,
login, database, deployment, or extra pages.

## Process
1. Inspect the data first. Print row counts, duplicates, date ranges, negative handle times, blank rates.
2. Write what you found and every decision into DECISIONS.md (what was unclear, what was chosen, why).
3. Then build app.py. Keep it to one file if possible.
4. Run it and confirm it loads with no errors before saying you are done.
5. Keep a running list in DECISIONS.md of anything you tried and discarded.