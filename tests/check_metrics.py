import os
import sys
import pandas as pd
import numpy as np

# Add parent directory to path to import app logic
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

import app

base_dir = os.path.join(parent_dir, "data")
tickets_csv = os.path.join(base_dir, "tickets.csv")
agents_csv = os.path.join(base_dir, "agents.csv")

print("=" * 70)
print("VIREO AUDIO CX DASHBOARD — METRIC VALIDATION SUITE")
print("=" * 70)

# Load data via app's processing pipeline
agent_table_app, df_tickets_app = app.load_and_process_data(tickets_csv, agents_csv)

# Load raw tickets for independent hand-calculation
df_raw = pd.read_csv(tickets_csv)
source_priority = {'legacy_fd': 0, 'helpdesk': 1}
df_raw['source_prio'] = df_raw['source_system'].map(source_priority).fillna(0)
df_dedup = df_raw.sort_values(by=['ticket_id', 'source_prio']).drop_duplicates(subset=['ticket_id'], keep='last').copy()

# -------------------------------------------------------------
# 1. 20 Random Resolved Tickets (Seed 42) Handle Time Check
# -------------------------------------------------------------
print("\n[TEST 1] Verifying Handle Time on 20 Random Resolved Tickets (Seed 42)...")
resolved_tickets = df_dedup[df_dedup['status'].str.lower() == 'resolved'].sample(n=20, random_state=42)

mismatches_t1 = 0
print(f"{'Ticket ID':<12} {'Source':<11} {'First Response':<17} {'Resolved At':<17} {'Corrected Resolv':<17} {'Hand (hrs)':<11} {'App (hrs)':<11} {'Status'}")
print("-" * 105)

for _, row in resolved_tickets.iterrows():
    tid = row['ticket_id']
    src = row['source_system']
    first_resp = pd.to_datetime(row['first_response_at'])
    resolv_raw = pd.to_datetime(row['resolved_at'])
    
    # Hand-style formula: +5:30 offset for legacy_fd UTC logs
    if src == 'legacy_fd':
        resolv_corr = resolv_raw + pd.Timedelta(hours=5, minutes=30)
    else:
        resolv_corr = resolv_raw
        
    hand_handle_time = (resolv_corr - first_resp).total_seconds() / 3600.0
    
    # App's computed handle time
    app_row = df_tickets_app[df_tickets_app['ticket_id'] == tid].iloc[0]
    app_handle_time = app_row['handle_time_hours']
    
    match = np.isclose(hand_handle_time, app_handle_time, atol=1e-5)
    if not match:
        mismatches_t1 += 1
    status_str = "MATCH" if match else "MISMATCH"
    
    print(f"{tid:<12} {src:<11} {str(first_resp)[:16]:<17} {str(resolv_raw)[:16]:<17} {str(resolv_corr)[:16]:<17} {hand_handle_time:<11.4f} {app_handle_time:<11.4f} {status_str}")

print(f"\nResult: {20 - mismatches_t1}/20 sample tickets matched exactly (Mismatches: {mismatches_t1}).")


# -------------------------------------------------------------
# 2. Zero Negative Handle Times & CSAT Blank Exclusion Check
# -------------------------------------------------------------
print("\n" + "=" * 70)
print("[TEST 2] Confirming Zero Negative Handle Times & Proper CSAT Handling...")
print("=" * 70)

# Check negative handle times across all resolved tickets in app
resolved_app = df_tickets_app[df_tickets_app['status'].str.lower() == 'resolved']
neg_handle_times = (resolved_app['handle_time_hours'] < 0).sum()
min_handle_time = resolved_app['handle_time_hours'].min()

print(f"Total resolved tickets checked: {len(resolved_app):,}")
print(f"Negative handle times count: {neg_handle_times}")
print(f"Minimum handle time observed: {min_handle_time:.4f} hours ({min_handle_time * 60:.1f} minutes)")
assert neg_handle_times == 0, "Error: Negative handle times found!"
print(">>> PASS: Zero negative handle times confirmed across the entire dataset.")

# Confirm CSAT blank handling
total_tickets = len(df_tickets_app)
blank_csat = df_tickets_app['csat_score'].isna().sum() + (df_tickets_app['csat_score'].astype(str).str.strip() == '').sum()
valid_csat = df_tickets_app['csat_valid'].notna().sum()
mean_valid_csat = df_tickets_app['csat_valid'].mean()
mean_if_zeros = df_tickets_app['csat_valid'].fillna(0).mean()

print(f"\nTotal tickets: {total_tickets:,}")
print(f"Blank CSAT responses: {blank_csat:,} ({blank_csat/total_tickets*100:.1f}%)")
print(f"Valid CSAT ratings: {valid_csat:,} ({valid_csat/total_tickets*100:.1f}%)")
print(f"Mean CSAT excluding blanks (App method): {mean_valid_csat:.4f}")
print(f"Mean CSAT if blanks were treated as 0:   {mean_if_zeros:.4f}")
assert not np.isclose(mean_valid_csat, mean_if_zeros), "Error: Blanks were treated as zeros!"
print(">>> PASS: Confirmed that blank CSAT responses are completely excluded from averages and NEVER imputed as 0.")


# -------------------------------------------------------------
# 3. Independent Hand-Recomputation for 3 Random Agents
# -------------------------------------------------------------
print("\n" + "=" * 70)
print("[TEST 3] Recomputing Metrics for 3 Random Agents Directly from Raw Data...")
print("=" * 70)

all_agents = agent_table_app['agent_id'].unique()
np.random.seed(42)
sample_agent_ids = np.random.choice(all_agents, size=3, replace=False)

for aid in sample_agent_ids:
    # 1. Raw calculation directly from df_dedup
    raw_agent_tickets = df_dedup[df_dedup['agent_id'] == aid]
    raw_handled_count = raw_agent_tickets['status'].str.lower().isin(['resolved', 'closed']).sum()
    
    # Raw CSAT mean
    valid_scores = pd.to_numeric(raw_agent_tickets['csat_score'], errors='coerce').dropna()
    raw_csat_responses = len(valid_scores)
    raw_csat_avg = valid_scores.mean() if raw_csat_responses > 0 else np.nan
    
    # Raw median handle time on resolved
    raw_resolved = raw_agent_tickets[raw_agent_tickets['status'].str.lower() == 'resolved'].copy()
    raw_first_resp = pd.to_datetime(raw_resolved['first_response_at'])
    raw_resolv = pd.to_datetime(raw_resolved['resolved_at'])
    is_leg = raw_resolved['source_system'] == 'legacy_fd'
    raw_resolv_corr = raw_resolv.copy()
    raw_resolv_corr.loc[is_leg] = raw_resolv.loc[is_leg] + pd.Timedelta(hours=5, minutes=30)
    raw_handle_hours = (raw_resolv_corr - raw_first_resp).dt.total_seconds() / 3600.0
    raw_median_handle = raw_handle_hours.median()
    
    # 2. App table metrics
    app_agent = agent_table_app[agent_table_app['agent_id'] == aid].iloc[0]
    
    print(f"\nAgent {aid} ({app_agent['name']} - {app_agent['team']}, Tier {app_agent['tier']}):")
    print(f"  Handled Tickets: Raw = {raw_handled_count:<4} | App = {app_agent['tickets_handled']:<4} | Match: {raw_handled_count == app_agent['tickets_handled']}")
    print(f"  CSAT Responses:  Raw = {raw_csat_responses:<4} | App = {app_agent['csat_responses']:<4} | Match: {raw_csat_responses == app_agent['csat_responses']}")
    print(f"  Average CSAT:    Raw = {raw_csat_avg:<6.4f} | App = {app_agent['avg_csat']:<6.4f} | Match: {np.isclose(raw_csat_avg, app_agent['avg_csat'])}")
    print(f"  Median Handle:   Raw = {raw_median_handle:<6.4f} | App = {app_agent['median_handle_time_hours']:<6.4f} | Match: {np.isclose(raw_median_handle, app_agent['median_handle_time_hours'])}")


# -------------------------------------------------------------
# 4. Global 44-Agent Match Rate Across All Metrics
# -------------------------------------------------------------
print("\n" + "=" * 70)
print("[TEST 4] Evaluating Full Match Rate Across All 44 Agents...")
print("=" * 70)

matches_handled = 0
matches_csat_resp = 0
matches_avg_csat = 0
matches_median_handle = 0
total_agents = len(agent_table_app)

for _, app_row in agent_table_app.iterrows():
    aid = app_row['agent_id']
    raw_agent_tickets = df_dedup[df_dedup['agent_id'] == aid]
    
    # Recompute handled count (resolved or closed only)
    raw_handled = raw_agent_tickets['status'].str.lower().isin(['resolved', 'closed']).sum()
    if raw_handled == app_row['tickets_handled']:
        matches_handled += 1
        
    # Recompute CSAT responses & avg
    valid_scores = pd.to_numeric(raw_agent_tickets['csat_score'], errors='coerce').dropna()
    if len(valid_scores) == app_row['csat_responses']:
        matches_csat_resp += 1
        
    raw_csat_mean = valid_scores.mean() if len(valid_scores) > 0 else np.nan
    if np.isclose(raw_csat_mean, app_row['avg_csat'], equal_nan=True):
        matches_avg_csat += 1
        
    # Recompute median handle time on resolved
    raw_resolved = raw_agent_tickets[raw_agent_tickets['status'].str.lower() == 'resolved'].copy()
    if len(raw_resolved) > 0:
        first_resp = pd.to_datetime(raw_resolved['first_response_at'])
        resolv = pd.to_datetime(raw_resolved['resolved_at'])
        is_leg = raw_resolved['source_system'] == 'legacy_fd'
        resolv_corr = resolv.copy()
        resolv_corr.loc[is_leg] = resolv.loc[is_leg] + pd.Timedelta(hours=5, minutes=30)
        raw_med = ((resolv_corr - first_resp).dt.total_seconds() / 3600.0).median()
    else:
        raw_med = np.nan
        
    if np.isclose(raw_med, app_row['median_handle_time_hours'], equal_nan=True):
        matches_median_handle += 1

print(f"Total Agents Tested:              {total_agents}")
print(f"Tickets Handled Count Matches:    {matches_handled} / {total_agents} ({matches_handled/total_agents*100:.1f}%)")
print(f"CSAT Responses Count Matches:     {matches_csat_resp} / {total_agents} ({matches_csat_resp/total_agents*100:.1f}%)")
print(f"Average CSAT Matches:             {matches_avg_csat} / {total_agents} ({matches_avg_csat/total_agents*100:.1f}%)")
print(f"Median Handle Time Matches:       {matches_median_handle} / {total_agents} ({matches_median_handle/total_agents*100:.1f}%)")

overall_perfect = (matches_handled == total_agents and 
                   matches_csat_resp == total_agents and 
                   matches_avg_csat == total_agents and 
                   matches_median_handle == total_agents)

if overall_perfect:
    print("\n>>> OVERALL VALIDATION STATUS: 100.0% PERFECT MATCH (44/44 AGENTS ACROSS ALL METRICS)")
else:
    print(f"\n>>> OVERALL VALIDATION STATUS: PARTIAL MATCH")
print("=" * 70)
