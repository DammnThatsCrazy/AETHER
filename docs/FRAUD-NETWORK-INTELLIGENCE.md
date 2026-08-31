---
title: Fraud Network Intelligence
slug: fraud-network-intelligence
section: concepts
visibility: I
audience: [security, architect, dev-senior, ops]
status: stable
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/fraud_networks/
  - Backend Architecture/aether-backend/repositories/repos.py
last_synced_commit: "845b1c14"
reviewed_source_commits:
  - commit: "54eaac5d"
    reason: "Reviewed the staging first-admin bootstrap change; fraud-network behavior and contracts are unaffected."
---

# Fraud Network Intelligence

Fraud Network Intelligence clusters related suspicious entities into named networks, scores risk at the cluster level, provides role classification for each member, and surfaces evidence-backed signals to investigation teams.

---

## Product Overview

The fraud scoring engine (`/v1/fraud/evaluate`) provides per-event risk signals in real time. Fraud Network Intelligence operates at the next layer — it groups entities that share behavioral, device, financial, or delegation links into **fraud networks** and scores the entire cluster as a unit.

Use cases:

- Detect mule rings where funds are routed through intermediate accounts
- Identify synthetic identity clusters sharing devices or IPs
- Spot split-merge layering patterns that evade per-transaction limits
- Surface agentic delegation abuse where AI agents orchestrate coordinated fraud
- Track reward-farming rings exploiting referral campaigns
- Link coordinated actors into investigation cases

---

## Architecture

```
Detection Pipeline
 ┌─────────────────────────────────────────────────────┐
 │  POST /v1/fraud/networks/build                      │
 │                                                     │
 │  1. Hop-expand anchors over transfers, then load    │
 │     wallets, sessions, delegations, reward events,  │
 │     orders + refunds for the expanded entity set    │
 │  2. Run 8 detectors (pure functions, no I/O)        │
 │  3. Build evidence refs from detector results       │
 │  4. Classify member roles (orchestrator/mule/…)     │
 │  5. Score cluster risk (0–100)                      │
 │  6. Score confidence (0–1)                          │
 │  7. Persist to FraudNetworkRepository               │
 │  8. Project to graph via GraphMutationGateway       │
 │     (FRAUD_NETWORK node + MEMBER_OF_FRAUD_NETWORK   │
 │      edges, causality_class=inferred_influence)     │
 │  9. Publish FRAUD_NETWORK_CREATED event             │
 └─────────────────────────────────────────────────────┘
```

---

## Data Model

### FraudNetwork

| Field | Type | Description |
|---|---|---|
| id | string | UUID |
| tenant_id | string | Owning tenant |
| network_type | NetworkType | Category of fraud pattern |
| label | string | Human-readable name |
| status | NetworkStatus | active / suppressed / escalated / closed / under_review |
| risk_score | float | 0–100 cluster risk |
| confidence_score | float | 0–1 evidence confidence |
| member_count | int | Members at last refresh |
| edge_count | int | Edges at last refresh |
| anchor_entity_ids | string[] | Seed entities the build expanded from |
| evidence_refs | EvidenceRef[] | Backing evidence |
| detected_signals | string[] | Detector signal names that fired |
| created_at | ISO8601 | |
| updated_at | ISO8601 | |
| metadata | dict | Free-form |

### NetworkType (14 values)

`synthetic_identity_ring`, `account_takeover_cluster`, `mule_network`,
`card_fraud_ring`, `referral_abuse_ring`, `airdrop_farming_cluster`,
`reward_farming_ring`, `wash_trading_ring`, `layering_network`,
`smurfing_network`, `delegation_abuse_cluster`, `commerce_abuse_ring`,
`coordinated_inauthentic_behavior`, `unknown`

### MemberRole (17 values)

`orchestrator`, `controller`, `mule`, `beneficiary`, `aggregator`, `splitter`,
`recruiter`, `facilitator`, `synthetic_identity`, `compromised_account`,
`cash_out_node`, `injection_point`, `relay`, `dormant`, `observer`, `victim`,
`unknown`

---

## Scoring Formulas

All scoring functions are pure (`services/fraud_networks/scoring.py`); risk in
[0, 100], confidence in [0, 1].

### Entity Risk (`score_entity_risk`)

| Component | Weight | Normalization |
|---|---|---|
| fraud_score (0–100) | 35% | direct |
| transfer volume | 20% | `min(log1p(vol) / log1p(1_000_000), 1)` |
| device sharing | 15% | `min(shared_device_count / 10, 1)` |
| IP sharing | 10% | `min(shared_ip_count / 10, 1)` |
| velocity flag | 10% | binary |
| new account (< 30 days) | 10% | binary |

### Edge Risk (`score_edge_risk`)

Endpoint risk average 30%, transfer frequency 25% (`/100` cap), amount 25%
(log-scaled), circularity bonus 10%, link-type severity 10% (full weight for
`LINKED_BY_DEVICE` / `LINKED_BY_IP` / `MEMBER_OF_FRAUD_NETWORK` / `USES_MULE`,
half otherwise).

### Path Risk (`score_path_risk`)

Average entity risk 35%, path length 20% (`/10` hops cap), cycle 20%, mule
presence 15%, amount 10% (log-scaled).

### Cluster Risk (`score_cluster_risk`)

| Component | Weight | Normalization |
|---|---|---|
| average member risk | 30% | direct (default 50 when empty) |
| average edge risk | 25% | direct (default 50 when empty) |
| cycle density | 20% | `min(cycle_count / 10, 1)` |
| signal breadth | 15% | `min(signal_count / 8, 1)` |
| network type severity | 10% | full weight for `mule_network`, `layering_network`, `smurfing_network`, `delegation_abuse_cluster`, `account_takeover_cluster`, `synthetic_identity_ring`; 60% otherwise |

### Confidence (`score_confidence`)

| Component | Weight | Normalization |
|---|---|---|
| evidence breadth | 30% | `min(evidence_count / 20, 1)` |
| signal overlap | 25% | `min(signal_overlap / 5, 1)` |
| member count | 20% | `min((member_count − 1) / 49, 1)` |
| circular transfer present | 15% | binary |
| device sharing present | 10% | binary |

---

## 8 Cluster Detectors

| Detector | Signal | Input |
|---|---|---|
| `detect_shared_device` | `shared_device` | sessions with device_fingerprint |
| `detect_shared_ip` | `shared_ip` | sessions with ip_address |
| `detect_wallet_cluster` | `shared_wallet` | wallet links (address + chain) |
| `detect_circular_transfers` | `circular_transfer` | transfers (DFS cycle detection) |
| `detect_split_merge` | `split_merge` | transfers (fan-out + fan-in) |
| `detect_reward_farming` | `reward_farming` | reward events by referrer |
| `detect_agentic_delegation_abuse` | `agentic_delegation_abuse` | delegations + attributed_agent_id transfers |
| `detect_commerce_abuse` | `commerce_abuse` | orders + refunds by entity |

All detectors are pure functions: no async, no I/O. They return `list[tuple[signal_name, entity_ids, detail_dict]]`.

---

## Feature Flags

| Flag | Default | Purpose |
|---|---|---|
| `FEATURE_FRAUD_NETWORKS` | false | Enable `/v1/fraud/networks/*` endpoints |
| `FRAUD_ALERT_RISK_THRESHOLD` | 70.0 | Alerting threshold held in `FraudIntelligenceConfig` (reserved — no automatic escalation is wired to it in the network service today) |
| `FRAUD_NETWORK_MAX_DEPTH` | 4 | Max hop depth for member expansion |

---

## Permissions

| Permission | Endpoints |
|---|---|
| `fraud:read` | GET endpoints, list, graph, members, evidence, timeline |
| `fraud:evaluate` | build, refresh, annotate, suppress, escalate, open-investigation, takedown |

All endpoints additionally require the `tenant_id` (body or query) to match
the authenticated tenant.

**Takedown → re-attribution.** `POST /{network_id}/takedown` marks the network
`closed` and invalidates the fraudulent attribution it produced: for each member
identity it calls the shared re-attribution invalidation service
(`services/measurement/reattribution.py`, Reliability Phase-2 Program 3 M3) with
`reason="fraud_takedown"`, superseding each affected active run with a fresh
zero-credit run. Unlike a DSR erasure it retains the touchpoints/conversions as
fraud evidence (no tombstone). The response carries a `reattribution` summary;
partial failures and scope truncation are surfaced there, never dropped.

---

## API Example

```bash
# Build a fraud network from anchor entities (fraud:evaluate permission)
curl -X POST /v1/fraud/networks/build \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "t1",
    "anchor_entity_ids": ["e1", "e2", "e3"],
    "network_type": "mule_network",
    "label": "Mule ring Q2-2026",
    "max_depth": 3
  }'

# Response — the persisted network record (returned directly, not wrapped)
{
  "id": "fn-abc123",
  "tenant_id": "t1",
  "network_type": "mule_network",
  "status": "active",
  "risk_score": 82.4,
  "confidence_score": 0.91,
  "member_count": 3,
  "edge_count": 4,
  "anchor_entity_ids": ["e1", "e2", "e3"],
  "detected_signals": ["circular_transfer"],
  "evidence_refs": ["..."],
  "created_at": "2026-06-21T...",
  "updated_at": "2026-06-21T..."
}
```

`max_depth` (1–10, default 3) is capped at the platform limit
`FRAUD_NETWORK_MAX_DEPTH` (default 4). See `docs/api/FRAUD-NETWORKS.md` for
the full endpoint reference.

---

## Privacy and Governance

- All fraud network records are tenant-scoped. Cross-tenant queries are not possible.
- Evidence refs reference only data already held in the tenant's own transfer and session records.
- No external enrichment sources are consulted during detection.
- Suppressed networks remain stored but do not appear in active queries.
- Operator access to another tenant's fraud networks requires break-glass escalation.
