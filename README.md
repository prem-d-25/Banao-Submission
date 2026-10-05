# Vireo Audio CSAT Dashboard

A Streamlit dashboard for Vireo's Head of CX (Priya) displaying CSAT per agent, handle time per agent, highlighting the bottom ten, and marking the top five (Diwali bonus), with separate peer group views, statistical confidence intervals, and data assumptions.

For a full breakdown of the data findings, empirical calculations, and business rationale, see [DECISIONS.md](DECISIONS.md).

## Setup and Run Instructions

A reviewer can run the dashboard with:

```bash
# 1. Create a virtual environment
python -m venv .venv

# 2. Activate the virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
.venv\Scripts\activate.bat
# On macOS/Linux:
source .venv/bin/activate

# 3. Install requirements
pip install -r requirements.txt

# 4. Launch the dashboard
streamlit run app.py

# 5. (Optional) Run automated metric validation tests
python tests/check_metrics.py
```

## Features
- **Automatic Loading**: Loads `data/tickets.csv` and `data/agents.csv` automatically on launch.
- **Per-Agent Metrics**: Agent ID, Name, Team, Tier, Peer Group, Avg CSAT, 95% CI, CI vs Team, CSAT vs Team (diff), CSAT Responses, Median Handle Time, Handle Time vs Team (diff), Tickets Handled, Hardware Share (%), Status, and Queue Note.
- **Median Handle Time**: Calculated strictly on `status = 'resolved'` tickets to eliminate distortions from auto-closed tickets with 72h wait windows. Tier 2 handle time is shown in days.
- **Hardware Share & Dynamic Rota Detection**: Computes hardware ticket share dynamically (no hardcoded IDs or CSAT bias); tags agents with high hardware share.
- **Peer Group Rankings**: Evaluates Tier 1 Hardware Rota, Tier 1 General Frontline, and Tier 2 Escalations independently to prevent unfair comparisons.
- **95% Confidence Intervals**: Displays 95% CSAT confidence intervals and flags agents whose performance overlaps the team average as "Not clearly different".
- **Top 5 & Bottom 10 Highlighting**: Clear visual badges marking Diwali bonus top performers and training-review bottom performers, including statistical indistinguishability callouts and top-5 tie caveats.
- **Assumptions Panel**: Complete in-app summary of data cleaning rules, UTC-IST offset correction, deduplication, hardware queue impact metrics, and calculations.

## AI Use Disclosure
- **Tools**: Antigravity plus Claude chat for planning and review
- **Cost**: [I will fill]
- **Discarded Approaches**: See [DECISIONS.md Section 2](DECISIONS.md#2-discarded-approaches-what-was-tried-and-discarded).
