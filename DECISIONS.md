# DECISIONS.md — Vireo Audio CSAT Dashboard

This document records the empirical findings from inspecting the Vireo Audio support dataset, along with all architectural, analytical, and data-cleaning decisions made for the CX CSAT Dashboard.

---

## 1. Initial Data Inspection Findings

### 1.1 Dataset Inventory & Row Counts
- **`tickets.csv`**: 11,750 rows.
  - `source_system`: `helpdesk` (8,376 tickets, 71.3%), `legacy_fd` (3,374 tickets, 28.7%).
  - Statuses: `resolved` (10,138), `closed` (1,045), `pending` (232), `open` (335).
- **`agents.csv`**: 44 rows representing 44 unique `agent_id`s (A3001–A3044).
  - Tiers: Tier 1 (38 agents across Frontline Chat, Email, Voice, Logistics, Billing, Returns), Tier 2 (6 agents in Escalations & Warranty).
- **`orders.csv`**: 15,225 rows.
- **`customers.csv`**: 10,000 rows.
- **`products.csv`**: 16 rows.
- **Operating Policy Attribution**:
  - Support operating policy explicitly dictates that **Tier 1 (frontline) and Tier 2 (Escalations & Warranty) must not be compared on volume metrics**, as their workflows, escalation paths, and case complexities are fundamentally different.
  - Other analytical choices (median handle time, filtering on resolved status, hardware share thresholds, peer grouping) are **our own decisions** based on data characteristics, documented below with their rationale.

---

### 1.2 Date Ranges & Migration Cutover
- **Legacy Freshdesk (`legacy_fd`)**:
  - `created_at`: 2025-01-01 08:22 to 2025-09-14 02:22
  - `resolved_at`: 2025-01-01 03:05 to 2025-09-25 16:07
- **Current Helpdesk (`helpdesk`)**:
  - `created_at`: 2025-09-14 07:30 to 2026-06-30 21:54
  - `resolved_at`: 2025-09-14 08:51 to 2026-07-10 21:35
- **Cutover Date**: September 14, 2025 at ~07:30 IST.

---

### 1.3 Blank Rates & Data Quality
- **`csat_score`**:
  - 6,554 blanks (55.8% non-response rate).
  - 5,196 valid scores (44.2% response rate).
  - Score distribution: 5: 748 (14.4%), 4: 1,632 (31.4%), 3: 1,695 (32.6%), 2: 811 (15.6%), 1: 310 (6.0%).
- **`first_response_at`**: 0 blanks (100% populated across all rows).
- **`resolved_at`**: 567 blanks (4.8%), strictly corresponding to open (335) and pending (232) tickets.

---

### 1.4 Timestamps and Negative Handle Times (Legacy UTC Bug)
- **Definition**: Handle time = `resolved_at` − `first_response_at`.
- **Raw computation**:
  - `helpdesk` tickets: 0 negative handle times; mean = 29.37 hours, median = 0.50 hours, min = 0.083 hours (5 minutes).
  - `legacy_fd` tickets: **2,309 out of 3,189 resolved tickets (72.4%) showed negative handle times**, dropping down to −5.42 hours.
- **Root Cause**: Freshdesk `resolved_at` timestamps were reconstructed from UTC logs, while helpdesk `first_response_at` timestamps were in Indian Standard Time (IST = UTC + 5:30). When a ticket was resolved in under 5.5 hours, subtracting IST `first_response_at` from UTC `resolved_at` produced a negative interval.
- **Decision: UTC Offset Correction**: For all `legacy_fd` records, `resolved_at` is adjusted by adding **+5 hours and 30 minutes (`pd.Timedelta(hours=5, minutes=30)`)**.
- **Sanity Check Post-Correction**:
  - `legacy_fd` negative handle times: **0** (minimum handle time is exactly 0.083 hours / 5 minutes).
  - `legacy_fd` median = 0.43 hours (aligns cleanly with current helpdesk median of 0.50 hours).

---

### 1.5 Duplicate Analysis & Re-import Checks
- **Normalised `ticket_id` Check (stripped, upper-cased)**:
  - Total duplicates found: **0**. Legacy IDs span `TK-240001`–`TK-244217`; Helpdesk IDs span `TK-244218`–`TK-254694`.
- **Proximity Duplicate Check on `(customer_id, product_sku, channel)` within $\pm 6$ hours**:
  - Across source systems (`helpdesk` vs `legacy_fd`): **0 duplicate tickets found**.
  - Within `legacy_fd`: **3 pairs** (6 tickets). Manual audit shows these represent distinct customer issues submitted within hours (e.g. inquiry about watch pairing followed by invoice download request).
  - Within `helpdesk`: **13 pairs** (26 tickets). Manual audit shows distinct inquiries submitted in close sequence.
- **Decision: Multi-source Deduplication Rule**:
  - If a user uploads datasets where re-imported tickets exist under both `helpdesk` and `legacy_fd`, the **`helpdesk` copy is designated canonical** and the `legacy_fd` copy is dropped.

---

### 1.6 Agent Roster Discrepancies & Disambiguation
- **Duplicate Display Name**:
  - Two distinct agents share the name `"Kavya Pandey"`:
    - **A3006**: Indore site, Chat Frontline team, Morning shift, Tier 1.
    - **A3029**: Bengaluru site, Logistics team, Morning shift, Tier 1.
  - **Decision: Join Key**: All joins between tickets and agents strictly use `agent_id`. Name is never used as a join key.
- **Decision: Multiple Roster Entries**:
  - Sorted by `from_date` ascending, taking the latest active record per `agent_id` to establish canonical team and tier.

---

## 2. Discarded Approaches (What Was Tried and Discarded)

1. **Discarded: Imputing Blank CSAT as 0 or Mean**
   - *Reason*: Blank CSAT represents non-response, not a customer satisfaction rating of 0. Imputing 0 would artificially drag agent CSAT down to ~1.5. Excluded completely from numerator and denominator.
2. **Discarded: Joining on Agent Name**
   - *Reason*: A3006 and A3029 are both named Kavya Pandey in different sites and teams. Merging on name conflates chat support and logistics performance.
3. **Discarded: Deduplicating on `(customer_id, order_id)`**
   - *Reason*: 3,794 tickets share customer and order IDs. Many customers legitimately reach out multiple times across different months regarding an order (e.g. shipping query in January, warranty query in May). Deduplicating by order ID would drop 2,123 legitimate customer support tickets.
4. **Discarded: 5-Hour Offset for Legacy Logs**
   - *Reason*: Testing a 5-hour offset left hundreds of residual negative handle times. Exactly 5 hours 30 minutes (+5:30) is the IST/UTC delta, which resolves 100% of negative handle times.
5. **Discarded: Using Mean Handle Time Across All Tickets**
   - *Reason*: Mean handle time is heavily skewed by multi-day outlier investigations and auto-closed tickets with 72h inactivity timeouts. Shifted to **median handle time on status=resolved tickets only**.
6. **Discarded: Hardcoding Agent IDs for Hardware Triage Rota**
   - *Reason*: Hardcoding specific IDs (`A3004`, `A3006`, etc.) or identifying agents by low CSAT is brittle and conflates queue effects with identity. Shifted to dynamic category-based hardware share computation.
7. **Discarded: Flat Single-List Ranking**
   - *Reason*: Flat rankings unfairly penalize Tier 2 warranty specialists and frontline hardware triage agents who face defective products and angry customers by design. Replaced by peer group rankings.

---

## 3. Revisions from First Review

1. **Decision: Handle Time Metric**:
   - Changed from mean to **median** handle time, calculated **strictly on tickets with `status == 'resolved'`**. Auto-closed tickets (`status == 'closed'`) are excluded because they include an arbitrary 72-hour customer wait window.
2. **Decision: Dynamic Hardware Share**:
   - Hardware-related categories defined as `Warranty & Repair`, `Charging & Battery`, `Audio Quality`.
   - Tier 1 agents with $\ge 40\%$ hardware share dynamically tagged as Hardware Triage Rota.
3. **Decision: Peer Group Ranking**:
   - Segmented into Tier 1 Hardware Rota, Tier 1 General Frontline, and Tier 2 Escalations.
4. **Decision: 95% Confidence Intervals**:
   - $\text{CI}_{95\%} = \bar{x} \pm 1.96 \cdot \frac{s}{\sqrt{n}}$ computed for each agent and compared to team average.

---

## 4. Revisions from Second Review

### 4.1 Explicit Decision Labeling & Policy Scope
- **Policy Scope**: Re-verified that Vireo's support operating policy dictates **separate ranking for Tier 1 and Tier 2**.
- **Own Choices Labeled as Decisions**:
  - *Decision*: Median handle time chosen to prevent right-skew from outlier investigations.
  - *Decision*: Status resolved-only chosen because closed tickets include a 72-hour auto-close wait.
  - *Decision*: Tickets handled defined as `status in ['resolved', 'closed']` only (11,183 tickets), excluding open/pending.
  - *Decision*: Tier 2 handle time reported in **days** (median ~3.2–5.7 days) rather than hours.

### 4.2 Proximity Duplicate Analysis Results
- Re-tested duplicates with normalised `ticket_id` (strip, upper) and proximity check on `(customer_id, product_sku, channel)` created within $\pm 6$ hours:
  - Across source systems: **0 duplicates**.
  - Within `legacy_fd`: **3 pairs** (all distinct customer inquiries).
  - Within `helpdesk`: **13 pairs** (all distinct customer inquiries).
- *Deduplication Rule*: Keep helpdesk copy as canonical if cross-system collisions occur.

### 4.3 Within-Team Benchmark Columns
- Added **`CSAT vs Team (diff)`** ($\text{Avg CSAT} - \text{Team Mean CSAT}$).
- Added **`Median handle time vs team median`** ($\text{Median Handle Time} - \text{Team Median Handle Time}$).
- Added explicit clarification: *Handle times and CSAT differences are only meaningful when compared within an agent's own team and queue type.*

### 4.4 Hardware Category CSAT Impact Across Peer Groups
Empirical breakdown of CSAT on hardware categories (`Warranty & Repair`, `Charging & Battery`, `Audio Quality`) versus non-hardware categories:

| Peer Group | Ticket Type | Ticket Count | Mean CSAT |
| :--- | :--- | :---: | :---: |
| **Tier 1 — Hardware Triage Rota** | Non-Hardware Tickets | 294 | **3.48** |
| **Tier 1 — Hardware Triage Rota** | Hardware Tickets | 215 | **2.37** |
| **Tier 1 — General Frontline** | Non-Hardware Tickets | 3,538 | **3.49** |
| **Tier 1 — General Frontline** | Hardware Tickets | 565 | **3.33** |
| **Tier 2 (Escalations & Warranty)** | Non-Hardware Tickets | 73 | **2.58** |
| **Tier 2 (Escalations & Warranty)** | Hardware Tickets | 511 | **2.58** |

**Critical Insight**: Tier 1 Hardware Triage Rota agents score **3.48** on non-hardware tickets—virtually identical to the rest of frontline (3.49). Low scores are concentrated on hardware tickets. Queue difficulty alone does not explain the gap (priority and transfers are similar). A likely cause is the Pulse 2 earbud defect (24% replacement rate vs ~7% for other products). Cause not fully proven.

#### Detailed Comparison on Hardware Tickets (Tier 1 Rota vs. Tier 1 General Frontline):
For tickets specifically within the hardware categories (`Warranty & Repair`, `Charging & Battery`, `Audio Quality`):
- **Average CSAT**:
  - Tier 1 Rota: **2.372** (n = 215 responses across 488 tickets)
  - Tier 1 General Frontline: **3.335** (n = 565 responses across 1,302 tickets)
- **Average Transfers**:
  - Tier 1 Rota: **0.084** transfers/ticket (Rota agents resolve directly on frontline)
  - Tier 1 General Frontline: **0.134** transfers/ticket
- **High Priority Ticket Share**:
  - Tier 1 Rota: **8.40%** (41 of 488 tickets)
  - Tier 1 General Frontline: **8.83%** (115 of 1,302 tickets)
- **Channel Distribution**:
  - Tier 1 Rota: **58.61% Chat** (286), **19.88% Email** (97), **12.70% Social** (62), **8.81% Voice** (43)
  - Tier 1 General Frontline: **37.56% Chat** (489), **36.10% Email** (470), **17.82% Voice** (232), **8.53% Social** (111)
  *(Rota is predominantly frontline live chat handling angry real-time customers)*
- **Average CSAT by Hardware Category**:
  - **Warranty & Repair**: Rota = **1.867** (n=30) vs General = **2.667** (n=9)
  - **Charging & Battery**: Rota = **2.273** (n=132) vs General = **3.288** (n=330)
  - **Audio Quality**: Rota = **2.906** (n=53) vs General = **3.429** (n=226)

### 4.5 Bottom Ten Statistical Significance
- Displayed `Peer Group` and `CI vs Team` in the Bottom Ten panel.
- Documented that **5 of the bottom ten agents are statistically distinguishable from their team average** (the other 5 overlap their team average and are marked `Not clearly different`).

### 4.6 Top 5 Caveat
- Added caveat under Top 5: *Top-five scores are closely clustered and may be statistically tied with ranks 6 to 10 due to overlapping confidence intervals.*

### 4.7 Slider Default Guarantee
- Fixed sidebar slider with a default threshold of **50**.

---

## 5. Validation

An automated independent verification suite ([tests/check_metrics.py](tests/check_metrics.py)) was executed directly against raw CSV data and compared to `app.py` outputs.

### 5.1 Sample Ticket Handle Time Recomputation (20 Random Resolved Tickets, Seed 42)
- Recomputed handle time by hand using formula `(resolved_at + 5h30m if legacy_fd else resolved_at) - first_response_at`.
- **Result**: **20 / 20 sample tickets (100.0%) matched the app's handle time calculation exactly** (0 mismatches).

### 5.2 Negative Handle Times & CSAT Blank Handling
- **Negative Handle Times**: **0 negative handle times** across all 10,138 resolved tickets in the dataset (minimum handle time observed = 0.0833 hours / 5.0 minutes).
- **CSAT Non-Response Handling**: Confirmed that 6,554 blank CSAT responses (55.8%) are completely excluded from CSAT calculation (app mean CSAT = 3.3266, whereas if blanks were treated as 0 it would collapse to 1.4711).

### 5.3 Independent Hand-Recomputation for 3 Random Agents (Seed 42)
Recomputing tickets handled count (`status in ['resolved', 'closed']`), CSAT responses count, average CSAT, and median handle time on resolved tickets directly from raw CSV records:
1. **Agent A3032 (Kunal Jain — Billing, Tier 1)**:
   - Handled Tickets: Raw = 370 | App = 370 (Match: True)
   - CSAT Responses: Raw = 169 | App = 169 (Match: True)
   - Average CSAT: Raw = 3.4320 | App = 3.4320 (Match: True)
   - Median Handle Time: Raw = 0.3667 hrs | App = 0.3667 hrs (Match: True)
2. **Agent A3007 (Siddharth Trivedi — Chat Frontline, Tier 1)**:
   - Handled Tickets: Raw = 261 | App = 261 (Match: True)
   - CSAT Responses: Raw = 120 | App = 120 (Match: True)
   - Average CSAT: Raw = 3.0083 | App = 3.0083 (Match: True)
   - Median Handle Time: Raw = 0.4500 hrs | App = 0.4500 hrs (Match: True)
3. **Agent A3022 (Manpreet Yadav — Email Frontline, Tier 1)**:
   - Handled Tickets: Raw = 218 | App = 218 (Match: True)
   - CSAT Responses: Raw = 97 | App = 97 (Match: True)
   - Average CSAT: Raw = 3.5361 | App = 3.5361 (Match: True)
   - Median Handle Time: Raw = 0.3833 hrs | App = 0.3833 hrs (Match: True)

### 5.4 Global 44-Agent Verification & Match Rate
Full verification across all 44 agents in the roster:
- **Tickets Handled Match Rate**: **44 / 44 (100.0%)**
- **CSAT Responses Match Rate**: **44 / 44 (100.0%)**
- **Average CSAT Match Rate**: **44 / 44 (100.0%)**
- **Median Handle Time Match Rate**: **44 / 44 (100.0%)**
- **Overall Verification Status**: **100.0% Perfect Match across all 44 agents and all metrics**.

---

## 6. Pulse 2 finding

Empirical investigation into product replacement patterns, warranty claim volumes, and policy compliance costs identified the **Pulse 2 wireless earbuds (`VA-EB-PL2`)** as the primary driver of customer dissatisfaction and hardware defect volume:

- **Disproportionate Replacement Share**: Pulse 2 (`VA-EB-PL2`) accounts for **1,166 of 1,896 total replacements (61%)** across all products in the catalog.
- **Replacement Rate per Unit Sold**: Pulse 2 has a **24.08% replacement rate per unit sold**, compared to **about 6.8% for all other products**.
- **Defective Manufacturing Lots**: Batches **`PL2-2510`**, **`PL2-2511`**, and **`PL2-2512`** show severe hardware failure rates of **32%–37%**.
- **Temporal Spike**: The monthly replacement rate rose sharply from **about 10% to about 25% (Jan–Apr 2026)**.
- **Replacement Cost Arithmetic**: Under support operating policy, replacement cost is computed as **unit cost + Rs 340** (averaging **about Rs 1,800**, not Rs 2,500).
- **Dual Policy Breach (Refund AND Replacement)**: **131 orders received both a refund and a replacement** (prohibited under operating policy Section 5), totaling up to **Rs 5.9 lakh** that requires immediate Finance audit and review.
- **SLA Breach Penalties**: SLA breach credits total **Rs 3.72 lakh** across the dataset, with a remarkably flat **~9% breach rate across all shifts** (Morning, Evening, Night).

