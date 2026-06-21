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
last_synced_commit: bf87315
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
 │  1. Load transfers + wallets + sessions for tenant  │
 │  2. Run 8 detectors (pure functions, no I/O)        │
 │  3. Build evidence refs from detector results       │
 │  4. Classify member roles (hub/mule/feeder/…)       │
 │  5. Score cluster risk (0–100)                      │
 │  6. Score confidence (0–1)                          │
 │  7. Persist to FraudNetworkRepository               │
 │  8. Project to graph (MEMBER_OF_FRAUD_NETWORK edges)│
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
| status | NetworkStatus | detected / active / escalated / suppressed / closed |
| risk_score | float | 0–100 cluster risk |
| confidence_score | float | 0–1 evidence confidence |
| member_count | int | Members at last refresh |
| evidence_refs | EvidenceRef[] | Backing evidence |
| created_at | ISO8601 | |
| updated_at | ISO8601 | |

### NetworkType (14 values)

`circular_transfer`, `mule_network`, `split_merge`, `shared_device_ring`, `shared_ip_cluster`, `shared_wallet_cluster`, `reward_farming`, `commerce_abuse`, `agentic_delegation_abuse`, `sybil_cluster`, `smurfing`, `layering`, `ponzi_scheme`, `unknown`

### MemberRole (17 values)

`hub`, `mule`, `feeder`, `collector`, `layerer`, `beneficiary`, `orchestrator`, `synthetic`, `dormant`, `complicit_merchant`, `network_bridge`, `cash_out_point`, `referral_farmer`, `commerce_abuser`, `delegation_abuser`, `agent_controller`, `unknown`

---

## Scoring Formulas

### Entity Risk (`score_entity_risk`)

```
base = fraud_score * 0.40
+ log10(max(transfer_volume_usd, 1)) / log10(10_000_001) * 25.0
+ min(shared_device_count, 5) * 5.0
+ min(shared_ip_count, 5) * 3.0
+ (10.0 if velocity_flag else 0.0)
+ (10.0 if account_age_days < 30 else 5.0 if account_age_days < 90 else 0.0)
```

Clamped to [0, 100].

### Cluster Risk (`score_cluster_risk`)

```
base = mean(member_risk_scores) * 0.4 + mean(edge_risk_scores) * 0.3
+ min(cycle_count, 5) * 4.0
+ min(signal_count, 10) * 2.5
+ NETWORK_TYPE_SEVERITY[network_type]
```

Clamped to [0, 100].

### Confidence (`score_confidence`)

```
base = min(evidence_count, 20) / 20.0 * 0.4
+ min(signal_overlap, 5) / 5.0 * 0.3
+ min(member_count, 50) / 50.0 * 0.2
+ 0.05 * has_circular_transfer
+ 0.05 * has_shared_device
```

Clamped to [0, 1].

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
| `FRAUD_ALERT_RISK_THRESHOLD` | 70.0 | Auto-escalate above this score |
| `FRAUD_NETWORK_MAX_DEPTH` | 4 | Max BFS depth for member expansion |

---

## Permissions

| Permission | Endpoints |
|---|---|
| `fraud:read` | GET endpoints, list, evidence, timeline |
| `fraud:write` | build, refresh, annotate |
| `fraud:escalate` | escalate, suppress |
| `investigations:write` | open-investigation |

---

## API Example

```bash
# Build a fraud network from anchor entities
curl -X POST /v1/fraud/networks/build \
  -H "Content-Type: application/json" \
  -d '{
    "anchor_entity_ids": ["e1", "e2", "e3"],
    "network_type": "circular_transfer",
    "label": "Circular ring Q2-2026"
  }'

# Response
{
  "data": {
    "id": "fn-abc123",
    "tenant_id": "t1",
    "network_type": "circular_transfer",
    "status": "active",
    "risk_score": 82.4,
    "confidence_score": 0.91,
    "member_count": 3,
    "evidence_refs": [...]
  },
  "status": "ok",
  "timestamp": "2026-06-21T..."
}
```

---

## Privacy and Governance

- All fraud network records are tenant-scoped. Cross-tenant queries are not possible.
- Evidence refs reference only data already held in the tenant's own transfer and session records.
- No external enrichment sources are consulted during detection.
- Suppressed networks remain stored but do not appear in active queries.
- Operator access to another tenant's fraud networks requires break-glass escalation.
