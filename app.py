import os
import pandas as pd
import numpy as np
import streamlit as st

# Page configuration
st.set_page_config(
    page_title="Vireo Audio — CX CSAT Dashboard",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.25rem;
    }
    .banner-warning {
        background-color: #fffbeb;
        border: 1px solid #fde68a;
        border-left: 5px solid #d97706;
        padding: 0.85rem 1.2rem;
        border-radius: 6px;
        color: #92400e;
        font-weight: 500;
        margin-bottom: 1.25rem;
    }
    .caveat-text {
        font-size: 0.88rem;
        color: #64748b;
        font-style: italic;
        margin-top: 0.35rem;
    }
    .stat-note {
        font-size: 0.9rem;
        color: #475569;
        font-weight: 500;
        margin-top: 0.4rem;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------
# Core Constants
# ---------------------------------------------------------
HARDWARE_CATEGORIES = {'Warranty & Repair', 'Charging & Battery', 'Audio Quality'}


# ---------------------------------------------------------
# Data Loading & Processing
# ---------------------------------------------------------
@st.cache_data
def load_and_process_data(tickets_file_or_path, agents_file_or_path):
    """
    Loads tickets and agents, cleans rosters, corrects legacy UTC resolved timestamps (+5:30),
    deduplicates tickets, and computes per-agent CSAT, median handle time, hardware share,
    within-team differences, and 95% confidence intervals.
    """
    # 1. Load CSVs
    df_tickets = pd.read_csv(tickets_file_or_path)
    df_agents = pd.read_csv(agents_file_or_path)

    # 2. Roster normalization:
    # Sort by from_date and keep latest active assignment.
    # Join on agent_id, never on name (two agents share the name 'Kavya Pandey').
    if 'from_date' in df_agents.columns:
        df_agents_sorted = df_agents.sort_values(by='from_date')
    else:
        df_agents_sorted = df_agents
    roster = df_agents_sorted.drop_duplicates(subset=['agent_id'], keep='last').copy()
    roster['agent_id'] = roster['agent_id'].astype(str).str.strip()
    roster['name'] = roster['name'].astype(str).str.strip()
    roster['team'] = roster['team'].astype(str).str.strip()
    roster['tier'] = roster['tier'].astype(str).str.strip()

    # 3. Deduplicate tickets:
    # Priority: helpdesk copy is canonical over legacy_fd.
    if 'source_system' in df_tickets.columns:
        source_priority = {'legacy_fd': 0, 'helpdesk': 1}
        df_tickets['source_prio'] = df_tickets['source_system'].map(source_priority).fillna(0)

        # Normalise ticket_id (strip, upper)
        if 'ticket_id' in df_tickets.columns:
            df_tickets['ticket_id_norm'] = df_tickets['ticket_id'].astype(str).str.strip().str.upper()
            df_tickets = df_tickets.sort_values(by=['ticket_id_norm', 'source_prio']).drop_duplicates(
                subset=['ticket_id_norm'], keep='last'
            )

        # Deduplicate on customer_id + product_sku + created_at
        if {'customer_id', 'product_sku', 'created_at'}.issubset(df_tickets.columns):
            df_tickets = df_tickets.sort_values(by=['customer_id', 'product_sku', 'created_at', 'source_prio']).drop_duplicates(
                subset=['customer_id', 'product_sku', 'created_at'], keep='last'
            )

        # Deduplicate on customer_id + customer_message
        if {'customer_id', 'customer_message'}.issubset(df_tickets.columns):
            df_tickets = df_tickets.sort_values(by=['customer_id', 'customer_message', 'source_prio']).drop_duplicates(
                subset=['customer_id', 'customer_message'], keep='last'
            )

    df_tickets = df_tickets.copy()

    # 4. Timestamps & Handle Time Calculation:
    # Legacy resolved_at was reconstructed from UTC logs; helpdesk timestamps are IST.
    # Offset correction: add +5:30 to legacy_fd resolved_at.
    df_tickets['first_response_dt'] = pd.to_datetime(df_tickets['first_response_at'], errors='coerce')
    df_tickets['resolved_dt'] = pd.to_datetime(df_tickets['resolved_at'], errors='coerce')

    is_legacy = df_tickets['source_system'].astype(str).str.strip() == 'legacy_fd'
    df_tickets['resolved_dt_corrected'] = df_tickets['resolved_dt']
    df_tickets.loc[is_legacy, 'resolved_dt_corrected'] = df_tickets.loc[is_legacy, 'resolved_dt'] + pd.Timedelta(hours=5, minutes=30)

    # Handle time: calculated on status == 'resolved' tickets ONLY
    # Decision: Auto-closed tickets include an arbitrary 72h customer wait, so they are excluded.
    is_resolved = df_tickets['status'].astype(str).str.lower().str.strip() == 'resolved'
    valid_resolved_handle = is_resolved & df_tickets['first_response_dt'].notna() & df_tickets['resolved_dt_corrected'].notna()

    df_tickets['handle_time_hours'] = np.nan
    df_tickets.loc[valid_resolved_handle, 'handle_time_hours'] = (
        df_tickets.loc[valid_resolved_handle, 'resolved_dt_corrected'] - df_tickets.loc[valid_resolved_handle, 'first_response_dt']
    ).dt.total_seconds() / 3600.0

    # Decision: Tickets handled = status resolved or closed only
    df_tickets['is_handled'] = df_tickets['status'].astype(str).str.lower().str.strip().isin(['resolved', 'closed'])

    # 5. CSAT Score:
    # Blank csat_score means no response. Exclude from averages; never treat as 0.
    df_tickets['csat_valid'] = pd.to_numeric(df_tickets['csat_score'], errors='coerce')

    # 6. Hardware tickets identification
    df_tickets['is_hardware'] = df_tickets['category'].isin(HARDWARE_CATEGORIES)

    # 7. Merge agent team to tickets for team benchmarks
    df_tickets['agent_id'] = df_tickets['agent_id'].astype(str).str.strip()
    df_tickets = df_tickets.merge(roster[['agent_id', 'team', 'tier']], on='agent_id', how='left')

    # Team benchmarks
    team_avg_csat = df_tickets.groupby('team')['csat_valid'].mean().to_dict()
    team_median_handle = df_tickets[valid_resolved_handle].groupby('team')['handle_time_hours'].median().to_dict()

    # 8. Aggregate per agent
    agent_counts = df_tickets.groupby('agent_id').agg(
        tickets_handled=('is_handled', 'sum'),
        resolved_tickets=('handle_time_hours', 'count'),
        median_handle_time_hours=('handle_time_hours', 'median'),
        csat_responses=('csat_valid', 'count'),
        avg_csat=('csat_valid', 'mean'),
        csat_std=('csat_valid', 'std'),
        hardware_tickets=('is_hardware', 'sum')
    ).reset_index()

    # Compute hardware share
    agent_counts['hw_share'] = agent_counts['hardware_tickets'] / agent_counts['tickets_handled']

    # Merge with roster on agent_id
    agent_table = roster[['agent_id', 'name', 'team', 'tier']].merge(agent_counts, on='agent_id', how='left')
    agent_table['tickets_handled'] = agent_table['tickets_handled'].fillna(0).astype(int)
    agent_table['resolved_tickets'] = agent_table['resolved_tickets'].fillna(0).astype(int)
    agent_table['csat_responses'] = agent_table['csat_responses'].fillna(0).astype(int)
    agent_table['hw_share'] = agent_table['hw_share'].fillna(0.0)

    # Team benchmarks mapped to agents
    agent_table['team_avg_csat'] = agent_table['team'].map(team_avg_csat)
    agent_table['team_median_handle'] = agent_table['team'].map(team_median_handle)

    # Within-team differences
    agent_table['csat_diff_team'] = agent_table['avg_csat'] - agent_table['team_avg_csat']
    agent_table['handle_diff_team'] = agent_table['median_handle_time_hours'] - agent_table['team_median_handle']

    # 9. 95% Confidence Interval for each agent's average CSAT
    se = agent_table['csat_std'] / np.sqrt(agent_table['csat_responses'])
    agent_table['ci_lower'] = agent_table['avg_csat'] - 1.96 * se
    agent_table['ci_upper'] = agent_table['avg_csat'] + 1.96 * se

    # Mark CI overlap with team average
    agent_table['ci_overlaps_team'] = (
        (agent_table['ci_lower'] <= agent_table['team_avg_csat']) &
        (agent_table['team_avg_csat'] <= agent_table['ci_upper'])
    )

    # 10. Dynamic Hardware Rota detection (no hardcoded agent IDs)
    is_t1 = agent_table['tier'] == '1'
    is_t2 = agent_table['tier'] == '2'
    is_t1_rota = is_t1 & (agent_table['hw_share'] >= 0.40)

    # Peer groups: 'Tier 1 — Hardware Triage Rota', 'Tier 1 — General Frontline', 'Tier 2 (Escalations & Warranty)'
    agent_table['peer_group'] = np.where(
        is_t2, 'Tier 2 (Escalations & Warranty)',
        np.where(is_t1_rota, 'Tier 1 — Hardware Triage Rota', 'Tier 1 — General Frontline')
    )

    # Tag agents high on hardware share
    agent_table['queue_note'] = np.where(
        is_t2 | is_t1_rota, 'Difficult queue, compare with care', ''
    )

    return agent_table, df_tickets


# ---------------------------------------------------------
# Sidebar: Settings & Threshold Controls
# ---------------------------------------------------------
st.sidebar.title("Configuration & Settings")

st.sidebar.markdown("### ⚙️ Ranking Criteria")
min_csat_responses = st.sidebar.slider(
    "Minimum CSAT responses (N)",
    min_value=5,
    max_value=100,
    value=50,
    step=1,
    help="Rank only agents with at least N CSAT responses. Agents with fewer are marked 'Insufficient data'."
)

# Automatic data path loading
tickets_source = os.path.join(os.path.dirname(__file__), "data", "tickets.csv")
agents_source = os.path.join(os.path.dirname(__file__), "data", "agents.csv")


# ---------------------------------------------------------
# Load Data
# ---------------------------------------------------------
try:
    agent_table, df_tickets = load_and_process_data(tickets_source, agents_source)
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()


# ---------------------------------------------------------
# Rankings & Peer Group Logic
# ---------------------------------------------------------
agent_table['eligible'] = agent_table['csat_responses'] >= min_csat_responses

# Overall Top 5 and Bottom 10
eligible_overall = agent_table[agent_table['eligible']].copy()
eligible_overall_sorted = eligible_overall.sort_values(by=['avg_csat', 'csat_responses'], ascending=[False, False])

top_5_ids = set(eligible_overall_sorted.head(5)['agent_id'])
bottom_10_ids = set(eligible_overall_sorted.tail(10)['agent_id'])

# Assign Status Tag
def assign_overall_status(row):
    if not row['eligible']:
        return "Insufficient data"
    aid = row['agent_id']
    if aid in top_5_ids:
        return "🏆 Top 5 (Diwali bonus)"
    elif aid in bottom_10_ids:
        return "⚠️ Bottom 10"
    return "Normal"

agent_table['status'] = agent_table.apply(assign_overall_status, axis=1)


# ---------------------------------------------------------
# Header & Warning Banner
# ---------------------------------------------------------
st.markdown('<div class="main-header">🎧 Vireo Audio — CX CSAT Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Executive CSAT and handle-time performance overview prepared for Priya Raman (Head of CX).</div>', unsafe_allow_html=True)

# Required Warning Banner
st.markdown(
    '<div class="banner-warning">⚠️ <strong>Notice</strong>: Low scores are concentrated on hardware tickets. Queue difficulty alone does not explain the gap (priority and transfers are similar). A likely cause is the Pulse 2 earbud defect (24% replacement rate vs ~7% for other products). Cause not fully proven.</div>',
    unsafe_allow_html=True
)

# High-level KPIs
total_handled = df_tickets['is_handled'].sum()
total_valid_csat = df_tickets['csat_valid'].count()
csat_resp_rate = (total_valid_csat / total_handled * 100) if total_handled > 0 else 0
overall_avg_csat = df_tickets['csat_valid'].mean()
overall_median_handle = df_tickets['handle_time_hours'].median()

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("Total Tickets Handled", f"{total_handled:,}", "Resolved or closed")
with c2:
    st.metric("CSAT Response Rate", f"{csat_resp_rate:.1f}%", f"{total_valid_csat:,} responses")
with c3:
    st.metric("Overall Avg CSAT", f"{overall_avg_csat:.2f} / 5.0")
with c4:
    st.metric("Median Handle Time", f"{overall_median_handle:.2f} hrs", "Resolved tickets only")
with c5:
    st.metric("Ranked Agents", f"{agent_table['eligible'].sum()} / {len(agent_table)}", f"Threshold N ≥ {min_csat_responses}")

st.write("")

# ---------------------------------------------------------
# Top 5 and Bottom 10 Summary Callout Cards
# ---------------------------------------------------------
col_top, col_bottom = st.columns(2)

with col_top:
    st.markdown("#### 🏆 Top 5 Agents by CSAT (Diwali Bonus)")
    top_5_df = agent_table[agent_table['agent_id'].isin(top_5_ids)].sort_values(by='avg_csat', ascending=False)
    display_top_5 = pd.DataFrame()
    display_top_5['Agent ID'] = top_5_df['agent_id']
    display_top_5['Name'] = top_5_df['name']
    display_top_5['Team'] = top_5_df['team']
    display_top_5['Peer Group'] = top_5_df['peer_group']
    display_top_5['Avg CSAT'] = top_5_df['avg_csat'].map(lambda x: f"{x:.2f}")
    display_top_5['95% CI'] = top_5_df.apply(lambda r: f"[{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]", axis=1)
    display_top_5['CSAT vs Team'] = top_5_df['csat_diff_team'].map(lambda x: f"{x:+.2f}")
    display_top_5['CSAT Responses'] = top_5_df['csat_responses']
    display_top_5['Median Handle Time'] = top_5_df.apply(
        lambda r: f"{r['median_handle_time_hours']/24.0:.2f} days" if str(r['tier']) == '2' else f"{r['median_handle_time_hours']:.2f} hrs",
        axis=1
    )
    display_top_5['HW Share (%)'] = top_5_df['hw_share'].map(lambda x: f"{x*100:.1f}%")
    st.dataframe(display_top_5, hide_index=True, use_container_width=True)
    st.markdown('<div class="caveat-text">*Caveat: Top-five scores are closely clustered and may be statistically tied with ranks 6 to 10 due to overlapping confidence intervals.*</div>', unsafe_allow_html=True)

with col_bottom:
    st.markdown("#### ⚠️ Bottom 10 Agents by CSAT (Overall Context)")
    bottom_10_df = agent_table[agent_table['agent_id'].isin(bottom_10_ids)].sort_values(by='avg_csat', ascending=True)
    display_bottom_10 = pd.DataFrame()
    display_bottom_10['Agent ID'] = bottom_10_df['agent_id']
    display_bottom_10['Name'] = bottom_10_df['name']
    display_bottom_10['Team'] = bottom_10_df['team']
    display_bottom_10['Peer Group'] = bottom_10_df['peer_group']
    display_bottom_10['Avg CSAT'] = bottom_10_df['avg_csat'].map(lambda x: f"{x:.2f}")
    display_bottom_10['95% CI'] = bottom_10_df.apply(lambda r: f"[{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]", axis=1)
    display_bottom_10['CI vs Team'] = bottom_10_df['ci_overlaps_team'].map(lambda x: "Not clearly different" if x else "Different from team")
    display_bottom_10['CSAT vs Team'] = bottom_10_df['csat_diff_team'].map(lambda x: f"{x:+.2f}")
    display_bottom_10['Median Handle Time'] = bottom_10_df.apply(
        lambda r: f"{r['median_handle_time_hours']/24.0:.2f} days" if str(r['tier']) == '2' else f"{r['median_handle_time_hours']:.2f} hrs",
        axis=1
    )
    display_bottom_10['HW Share (%)'] = bottom_10_df['hw_share'].map(lambda x: f"{x*100:.1f}%")
    display_bottom_10['Queue Note'] = bottom_10_df['queue_note']
    st.dataframe(display_bottom_10, hide_index=True, use_container_width=True)

    # Statistical indistinguishability callout
    b10_distinguishable = (~bottom_10_df['ci_overlaps_team']).sum()
    b10_not_diff = bottom_10_df['ci_overlaps_team'].sum()
    st.markdown(
        f'<div class="stat-note">📊 <strong>Statistical Significance</strong>: Exactly <strong>{b10_distinguishable} of the bottom ten</strong> agents are statistically distinguishable from their team average ({b10_not_diff} overlap their team average and are marked "Not clearly different").</div>',
        unsafe_allow_html=True
    )

st.write("")
st.markdown("---")


# ---------------------------------------------------------
# Formatting and Styling Helpers
# ---------------------------------------------------------
def format_agent_dataframe(df_in):
    df = df_in.copy()

    # Sort: Eligible by CSAT descending, ineligible at the bottom
    df['sort_csat'] = df['avg_csat'].fillna(-1)
    df = df.sort_values(by=['eligible', 'sort_csat', 'csat_responses'], ascending=[False, False, False]).drop(columns=['sort_csat'])

    display_df = pd.DataFrame()
    display_df['Agent ID'] = df['agent_id']
    display_df['Name'] = df['name']
    display_df['Team'] = df['team']
    display_df['Tier'] = df['tier']
    display_df['Peer Group'] = df['peer_group']
    display_df['Avg CSAT'] = df.apply(lambda r: f"{r['avg_csat']:.2f}" if r['eligible'] else "Insufficient data", axis=1)
    display_df['95% CI'] = df.apply(
        lambda r: f"[{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]" if r['eligible'] and pd.notna(r['ci_lower']) else "N/A",
        axis=1
    )
    display_df['CI vs Team'] = df.apply(
        lambda r: "Not clearly different" if (r['eligible'] and r['ci_overlaps_team']) else ("Different from team" if r['eligible'] else "N/A"),
        axis=1
    )
    display_df['CSAT vs Team (diff)'] = df.apply(
        lambda r: f"{r['csat_diff_team']:+.2f}" if r['eligible'] and pd.notna(r['csat_diff_team']) else "N/A",
        axis=1
    )
    display_df['Median Handle Time'] = df.apply(
        lambda r: (f"{r['median_handle_time_hours']/24.0:.2f} days" if str(r['tier']) == '2' else f"{r['median_handle_time_hours']:.2f} hrs") if pd.notna(r['median_handle_time_hours']) else "N/A",
        axis=1
    )
    display_df['Handle Time vs Team (diff)'] = df.apply(
        lambda r: (f"{r['handle_diff_team']/24.0:+.2f} days" if str(r['tier']) == '2' else f"{r['handle_diff_team']:+.2f} hrs") if pd.notna(r['handle_diff_team']) else "N/A",
        axis=1
    )
    display_df['Tickets Handled'] = df['tickets_handled']
    display_df['CSAT Responses'] = df['csat_responses']
    display_df['HW Share (%)'] = df['hw_share'].map(lambda x: f"{x*100:.1f}%")
    display_df['Status'] = df['status']
    display_df['Queue Note'] = df['queue_note']

    return display_df

def style_table(df):
    def highlight_status(row):
        status_val = str(row.get('Status', ''))
        if 'Bottom 10' in status_val:
            return ['background-color: #fee2e2; color: #991b1b; font-weight: 500'] * len(row)
        elif 'Top 5' in status_val:
            return ['background-color: #dcfce7; color: #166534; font-weight: 500'] * len(row)
        elif 'Insufficient' in status_val or 'Insufficient' in str(row.get('Avg CSAT', '')):
            return ['background-color: #f1f5f9; color: #64748b'] * len(row)
        return [''] * len(row)

    return df.style.apply(highlight_status, axis=1)


# ---------------------------------------------------------
# Tabbed Views: Peer Groups & Combined
# ---------------------------------------------------------
st.markdown("### 📊 Per-Agent Performance Tables")
st.markdown("*Note: Handle time and CSAT differences are only meaningful when compared within an agent's own team and queue type.*")

tab_peer, tab_all, tab_tier1, tab_tier2 = st.tabs([
    "Peer Groups Breakdown",
    "All Agents (Combined)",
    "Tier 1 (Frontline)",
    "Tier 2 (Escalations & Warranty)"
])

with tab_peer:
    st.markdown("""
    **Peer Group Ranking Evaluation**:
    1. **Tier 1 — Hardware Triage Rota**: Frontline agents handling $\ge 40\%$ hardware defect issues.
    2. **Tier 1 — General Frontline**: Frontline agents handling shipping, billing, returns, and general inquiries.
    3. **Tier 2 (Escalations & Warranty)**: Specialized team handling long-cycle replacements and multi-day warranty diagnostics.
    """)

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.markdown("##### 🔧 Tier 1 — Hardware Triage Rota")
        rota_df = agent_table[agent_table['peer_group'] == 'Tier 1 — Hardware Triage Rota']
        st.dataframe(style_table(format_agent_dataframe(rota_df)), hide_index=True, use_container_width=True)

    with col_g2:
        st.markdown("##### 🛡️ Tier 2 — Escalations & Warranty (Handle times in days)")
        t2_df = agent_table[agent_table['peer_group'] == 'Tier 2 (Escalations & Warranty)']
        st.dataframe(style_table(format_agent_dataframe(t2_df)), hide_index=True, use_container_width=True)

    st.markdown("##### 💬 Tier 1 — General Frontline (Bottom list matters for training budget)")
    gen_df = agent_table[agent_table['peer_group'] == 'Tier 1 — General Frontline']
    st.dataframe(style_table(format_agent_dataframe(gen_df)), hide_index=True, use_container_width=True)

with tab_all:
    st.markdown("**Complete Agent Roster**: Showing all 44 agents with overall Top 5 (Diwali bonus) and Bottom 10 highlighted.")
    table_all = format_agent_dataframe(agent_table)
    st.dataframe(
        style_table(table_all),
        hide_index=True,
        use_container_width=True,
        height=520
    )

with tab_tier1:
    st.markdown("**Tier 1 Frontline Agents**: Ranked independently to avoid volume and handle-time distortions compared to Tier 2.")
    t1_table = agent_table[agent_table['tier'] == '1'].copy()
    formatted_t1 = format_agent_dataframe(t1_table)
    st.dataframe(
        style_table(formatted_t1),
        hide_index=True,
        use_container_width=True,
        height=500
    )

with tab_tier2:
    st.markdown("**Tier 2 Escalations & Warranty**: 6 specialized agents handling warranty diagnostics, replacement decisions, and angry escalations.")
    st.warning("⚠️ **Operating Policy Rule**: Tier 2 agents handle complex multi-day escalations (median handle time ~3.2–5.7 days vs ~0.4 hrs for frontline chat) and receive angriest customers. Policy prohibits comparing them directly on frontline volume or handle-time metrics.")
    t2_table = agent_table[agent_table['tier'] == '2'].copy()
    formatted_t2 = format_agent_dataframe(t2_table)
    st.dataframe(
        style_table(formatted_t2),
        hide_index=True,
        use_container_width=True,
        height=260
    )


# ---------------------------------------------------------
# Assumptions & Decisions Section
# ---------------------------------------------------------
st.markdown("---")
with st.expander("📌 Assumptions & Data Decisions (Click to expand)", expanded=True):
    st.markdown("""
    ### Data Processing Decisions & Operating Rules
    1. **Operating Policy Rule: Tier 1 vs. Tier 2 Separation**:
       - Support operating policy explicitly dictates that Tier 1 (frontline) and Tier 2 (Escalations & Warranty) **must not be compared on volume metrics or raw resolution speed**, as their work is qualitatively different.
    2. **Decision: Handle Time (Median on Status = Resolved Only)**:
       - Handle time is calculated as `resolved_at - first_response_at`.
       - *Decision*: We chose **median** handle time instead of the mean because handle time is heavily right-skewed by complex multi-day investigations.
       - *Decision*: Calculations are performed **strictly on tickets with `status = 'resolved'`**. Auto-closed tickets (`status = 'closed'`) are excluded because they include an arbitrary 72-hour customer inactivity wait window that distorts true agent resolution speed.
       - *Decision*: Tier 2 handle times are reported in **days** (median ~3.2–5.7 days) rather than hours to reflect multi-day repair cycles.
    3. **Decision: Tickets Handled Count**:
       - *Decision*: Handled tickets are counted as `status in ['resolved', 'closed']` only (11,183 tickets). Open and pending tickets are excluded as they have not yet been handled to completion.
    4. **Decision: Legacy UTC Log Offset Correction (+5:30)**:
       - *Decision*: Freshdesk (`legacy_fd`) `resolved_at` timestamps were reconstructed from UTC logs, while helpdesk timestamps are in Indian Standard Time (IST = UTC + 5:30). Raw subtraction yielded negative handle times for 72.4% of resolved legacy tickets.
       - Applying a **+5 hours 30 minutes** offset to `legacy_fd` `resolved_at` timestamps completely eliminates negative handle times (0 remaining; min handle time = 5 minutes).
    5. **Decision: Deduplication Rule (Legacy Re-Imports)**:
       - *Decision*: If duplicate tickets occur, the **helpdesk copy is retained as canonical** over `legacy_fd`.
       - *Empirical Check*:
         - Normalised `ticket_id` (stripped and upper-cased): **0 duplicates found**.
         - Collisions on `(customer_id, product_sku, channel)` created within $\pm 6$ hours across source systems: **0 duplicates found**.
         - Within `legacy_fd`: 3 pairs created within 6 hours (distinct customer inquiries).
         - Within `helpdesk`: 13 pairs created within 6 hours (distinct customer inquiries).
    6. **Decision: Hardware Category CSAT Impact & Dynamic Rota Identification**:
       - Analysis of tickets by category reveals that customer dissatisfaction is heavily concentrated in hardware defect queues (`Warranty & Repair`, `Charging & Battery`, `Audio Quality`):
         - **Tier 1 — Hardware Triage Rota**:
           - Non-Hardware Tickets: **3.48 Mean CSAT** (Count: 294)
           - Hardware Tickets: **2.37 Mean CSAT** (Count: 215) — *A drop of 1.11 points purely due to hardware defects!*
         - **Tier 1 — General Frontline**:
           - Non-Hardware Tickets: **3.49 Mean CSAT** (Count: 3,538)
           - Hardware Tickets: **3.33 Mean CSAT** (Count: 565)
         - **Tier 2 (Escalations & Warranty)**:
           - Non-Hardware Tickets: **2.58 Mean CSAT** (Count: 73)
           - Hardware Tickets: **2.58 Mean CSAT** (Count: 511)
       - Low scores are concentrated on hardware tickets. Queue difficulty alone does not explain the gap (priority and transfers are similar). A likely cause is the Pulse 2 earbud defect (24% replacement rate vs ~7% for other products). Cause not fully proven.
       - *Decision*: Agents with $\ge 40\%$ hardware share in Tier 1 are dynamically identified as the **Hardware Triage Rota** without hardcoding agent IDs. Tagged with: **`Difficult queue, compare with care`**.
    7. **Decision: Peer Group Ranking & Statistical Indistinguishability**:
       - *Decision*: Rather than a flat list that unfairly penalizes hardware queues, agents are ranked within peer groups.
       - *Decision*: A 95% Confidence Interval ($\bar{x} \pm 1.96 \cdot \frac{s}{\sqrt{n}}$) is computed for each agent. In the bottom ten, **5 out of 10 agents overlap their team average** and are marked **`Not clearly different`**.
    8. **Decision: Blank CSAT Handling**:
       - *Decision*: Blank `csat_score` indicates survey non-response (55.8% rate). Blanks are completely excluded from CSAT calculations and are **never** treated as 0.
    9. **Decision: Agent Disambiguation (`agent_id`)**:
       - *Decision*: Two distinct agents share the display name *"Kavya Pandey"* (`A3006` in Indore Chat Frontline and `A3029` in Bengaluru Logistics). All joins strictly use `agent_id`.
    10. **Decision: Minimum Response Threshold ($N$)**:
       - *Decision*: Default threshold slider is set to **$N = 50$** responses. Agents with fewer than $N$ responses are marked *"Insufficient data"*.
    """)
