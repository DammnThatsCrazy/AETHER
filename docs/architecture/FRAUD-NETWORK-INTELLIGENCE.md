---
title: Fraud Network Intelligence
slug: fraud-network-intelligence
section: concepts
visibility: I
audience: [security, architect, dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/intelligence/fraud_networks/
  - services/api/repositories/repos.py
reviewed_source_commits:
  - commit: "54eaac5d"
    reason: "Reviewed the staging first-admin bootstrap change; fraud-network behavior and contracts are unaffected."
  - commit: "f63d631"
    reason: "Reviewed f63d631 (DSR completeness): repositories/repos.py only gains the additive BaseRepository.delete_for_tenant_where DSR-erasure primitive used by the consent.erasure job; no repository this doc describes changed behavior, so no body change was required."
source_hashes:
  "services/api/intelligence/fraud_networks/": "sha256:07bdba9019053a0b624c232e43b96d9ef9fa4ff72c8b5a6c3ad45a9556a4c596"
  "services/api/repositories/repos.py": "sha256:1784df01b61c04f087c80397c3eab3b7167aef930bf199b7a82da4bfdc18dbf4"
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
 │  8. Best-effort persist evidence-backed agentic     │
 │     delegation signals to tenant-scoped Risk360     │
 │  9. Project to graph via GraphMutationGateway       │
 │     (FRAUD_NETWORK node + MEMBER_OF_FRAUD_NETWORK   │
 │      edges, causality_class=inferred_influence)     │
 │ 10. Publish FRAUD_NETWORK_CREATED event             │
 └─────────────────────────────────────────────────────┘
```

The Risk360 handoff resolves source agent identifiers through explicit
tenant-owned identity bindings before persisting assessments under canonical
Agent entities. It retains detector and binding evidence, leaves inferred
signals classified as inferred, and omits ambiguous, truncated, unresolved, or
cross-tenant mappings. It does not turn a delegation match into authority or
proof of execution. The tenant-owned identity binding must have one consistent,
valid timezone-aware `identity_bound_at` at or before the detector observation
time; missing, malformed, conflicting, or future binding times are omitted to
prevent retroactive attribution.

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

All scoring functions are pure (`services/api/intelligence/fraud_networks/scoring.py`); risk in
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

### Fleet hypotheses (agent swarms)

`fleet_hypothesis.py` / `fleet_routes.py` answer "do these agents share a
controlling operator?" for an orchestrator that spawned many sub-agents. They
are separate from the eight detectors above and do not create a fraud network.

- Evidence is graded `observed` (spawn tree, canonical principal delegation) or
  `inferred` (spawn burst, shared MCP endpoint host, identical tool sequence,
  overlapping wallet/account targets), each with source event references.
- Without an observed principal, confidence is capped at 0.55. With a canonical
  non-spawn delegation to the orchestrator it is capped at 0.90. A delegation
  proves authority was granted, not intent; `principal_is_not_the_actor` is
  always listed as a competing explanation.
- Competing explanations are generated from the evidence (shared third-party
  infrastructure, same vendor template, legitimate parallel workflow, no human
  principal observed).
- Status starts `unconfirmed` or `needs_review` (fleet of 5+, or any member with
  a Risk360 signal, and confidence >= 0.35). Only `POST .../review` can set
  `confirmed_by_reviewer` or `rejected_by_reviewer`; confirming needs an
  observed principal and a written reason. A rebuild keeps a review only while
  the evidence fingerprint (root, evidence types, linked principals) is
  unchanged; if the evidence or person link changed since the reviewer decided,
  the decision is recorded as `superseded` in `review_history` and the hypothesis
  returns to the builder's status for a fresh review.
- A person link is only ever made to a grantor the canonical identity authority
  resolves to an active `human` subject (merge tombstones followed; the
  surviving id is recorded). Agents, organizations and unresolved ids are not
  principals. Evidence event references come from the spawn edges traversed into
  the selected lineage, and a hypothesis built from a capped read carries
  `source_truncation`.
- Writes are compare-and-set on `revision` (first write is insert-if-absent), so
  concurrent reviews and rebuilds cannot overwrite one another, and `created_at`
  is preserved across both.
- Routes (under `FEATURE_FRAUD_NETWORKS`): `POST /v1/fraud/fleet-hypotheses/build`
  (`fraud:evaluate`), `GET /v1/fraud/fleet-hypotheses[/{id}]` (`fraud:read`),
  `POST /v1/fraud/fleet-hypotheses/{id}/review` (`fraud:evaluate`).
- **Fraud360 projection** (flag `AETHER_FRAUD360_ENABLED`; `fleet_fraud360.py`).
  Build and review mirror the hypothesis into a Fraud360 `FraudHypothesis`
  (`agent_abuse` pattern) on the *canonical* Agent entity; an unresolved or
  ambiguous identity writes nothing. `claim_state` is `attributed` with a
  delegation-backed person link, otherwise `inferred`. States move through
  `FraudHypothesisStateMachine`: unconfirmed -> candidate, needs_review ->
  under_evaluation, reviewer-confirmed -> investigating, reviewer-rejected ->
  rejected (grounded in the review record). A reviewer confirming "common
  operator" is not confirmation of fraud, so the projection never reaches
  Fraud360 `confirmed`. A record an analyst has moved elsewhere is left alone
  (`state_diverged`). The response carries `fraud360` with the projection status.
- Not done: a Risk360 assessment for a hypothesis, and egress/IP evidence (Silver
  agent facts carry no source address; MCP endpoint host is the only
  infrastructure signal).

---

## Feature Flags

| Flag | Default | Purpose |
|---|---|---|
| `FEATURE_FRAUD_NETWORKS` | false | Enable `/v1/fraud/networks/*` endpoints |
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
(`services/api/journeys/measurement/reattribution.py`, Reliability Phase-2 Program 3 M3) with
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
`FRAUD_NETWORK_MAX_DEPTH` (default 4). See `docs/reference/api/FRAUD-NETWORKS.md` for
the full endpoint reference.

---

## Privacy and Governance

- All fraud network records are tenant-scoped. Cross-tenant queries are not possible.
- Evidence refs reference only data already held in the tenant's own transfer and session records.
- No external enrichment sources are consulted during detection.
- Suppressed networks remain stored but do not appear in active queries.
- Operator access to another tenant's fraud networks requires break-glass escalation.
