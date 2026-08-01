---
title: Fraud Networks API Reference
slug: api/fraud-networks
section: api
visibility: I
audience: [dev-senior, security, architect]
status: stable
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/fraud_networks/routes.py
last_synced_commit: "41c79d4"
---

# Fraud Networks API Reference

Base path: `/v1/fraud/networks`

Feature flag: `FEATURE_FRAUD_NETWORKS=true` required. Returns 404 when disabled.

Every endpoint takes the tenant either in the request body (`tenant_id`) or as
a required `tenant_id` query parameter; a mismatch with the authenticated
tenant returns 403.

Permissions: read endpoints require `fraud:read`; all mutating endpoints
(build, refresh, open-investigation, annotate, suppress, escalate) require
`fraud:evaluate`.

Graph projection note: network writes are projected into the universal graph
through the `GraphMutationGateway` (FRAUD_NETWORK `node_versioned`,
`MEMBER_OF_FRAUD_NETWORK` edges with `causality_class=inferred_influence`,
and `ATTACHED_TO_CASE` on open-investigation); projection failure is logged
and never fails the API call.

---

## POST /v1/fraud/networks/build

Run the full detection pipeline for a set of anchor entities and persist a new
fraud network. Entities are expanded hop-by-hop over the transfer ledger, then
all detectors run (shared device, shared IP, wallet cluster, circular
transfers, split/merge, reward farming, agentic delegation abuse, commerce
abuse) and members are assigned roles.

**Permission**: `fraud:evaluate`

**Request**

```json
{
  "tenant_id": "t1",
  "anchor_entity_ids": ["e1", "e2"],
  "network_type": "mule_network",
  "max_depth": 3,
  "min_confidence": 0.4,
  "label": "Q2 ring"
}
```

- `tenant_id`: required; must match the authenticated tenant
- `anchor_entity_ids`: required, at least one entry
- `network_type`: optional, one of `synthetic_identity_ring`,
  `account_takeover_cluster`, `mule_network`, `card_fraud_ring`,
  `referral_abuse_ring`, `airdrop_farming_cluster`, `reward_farming_ring`,
  `wash_trading_ring`, `layering_network`, `smurfing_network`,
  `delegation_abuse_cluster`, `commerce_abuse_ring`,
  `coordinated_inauthentic_behavior`, `unknown`
- `max_depth`: 1–10, default 3; effective value is capped at the platform
  limit `FRAUD_NETWORK_MAX_DEPTH` (default 4)
- `min_confidence`: 0.0–1.0, default 0.4
- `label`, `metadata`: optional

**Response 200** — the persisted network record (returned directly, not
wrapped in an envelope):

```json
{
  "id": "fn-abc123",
  "tenant_id": "t1",
  "label": "Q2 ring",
  "network_type": "mule_network",
  "status": "active",
  "risk_score": 82.4,
  "confidence_score": 0.91,
  "member_count": 3,
  "edge_count": 4,
  "anchor_entity_ids": ["e1", "e2"],
  "evidence_refs": [
    {
      "id": "ev-001",
      "type": "transaction",
      "source": "aether.fraud.detector.circular_transfers",
      "confidence": 0.9,
      "uri": "aether://fraud-networks/fn-abc123/evidence?signal=circular_transfer&entities=e1,e2"
    }
  ],
  "detected_signals": ["circular_transfer"],
  "created_at": "2026-06-21T10:00:00Z",
  "updated_at": "2026-06-21T10:00:00Z",
  "metadata": {}
}
```

Publishing: emits a `FRAUD_NETWORK_CREATED` event.

---

## GET /v1/fraud/networks

List networks for the authenticated tenant.

**Permission**: `fraud:read`

**Query params**: `tenant_id` (required), `status` (optional), `limit`
(1–200, default 50)

**Response 200** — standard `APIResponse` envelope; `data` is the list of
network records, count lives in `meta`:

```json
{
  "data": [ { "id": "fn-abc123", "...": "..." } ],
  "status": "success",
  "timestamp": "2026-06-21T10:00:00Z",
  "meta": { "count": 12, "request_id": "…", "timestamp": "…" }
}
```

---

## GET /v1/fraud/networks/{network_id}

Get a single network by ID (returned directly, same shape as the build
response). Returns 404 if the network does not belong to the tenant.

**Permission**: `fraud:read` — query params: `tenant_id` (required)

---

## GET /v1/fraud/networks/{network_id}/graph

Returns a Cytoscape-ready graph payload with nodes and edges for the network.

**Permission**: `fraud:read` — query params: `tenant_id` (required)

**Response 200** (returned directly):

```json
{
  "network_id": "fn-abc123",
  "nodes": [
    {
      "id": "e1", "label": "e1", "entity_type": "user", "role": "mule",
      "risk_score": 85.0, "confidence": 0.8, "is_anchor": true, "metadata": {}
    }
  ],
  "edges": [
    {
      "id": "edge-001", "source": "e1", "target": "e2",
      "edge_type": "TRANSFERRED", "risk_score": 72.0,
      "transfer_count": 3, "metadata": {}
    }
  ],
  "node_count": 1,
  "edge_count": 1,
  "computed_at": "2026-06-21T10:05:00Z"
}
```

---

## GET /v1/fraud/networks/{network_id}/members

List all members of the network with roles and risk scores.

**Permission**: `fraud:read` — query params: `tenant_id` (required)

`APIResponse` envelope; `data` is a list of member records
(`id`, `network_id`, `tenant_id`, `entity_id`, `entity_type`, `role`,
`risk_score`, `confidence`, `in_degree`, `out_degree`, `evidence_refs`,
`joined_at`, `metadata`). Role vocabulary: `orchestrator`, `controller`,
`mule`, `beneficiary`, `aggregator`, `splitter`, `recruiter`, `facilitator`,
`synthetic_identity`, `compromised_account`, `cash_out_node`,
`injection_point`, `relay`, `dormant`, `observer`, `victim`, `unknown`.

---

## GET /v1/fraud/networks/{network_id}/evidence

Return all evidence refs associated with the network.

**Permission**: `fraud:read` — query params: `tenant_id` (required)

`APIResponse` envelope; `data` is a list of evidence refs.

---

## GET /v1/fraud/networks/{network_id}/timeline

Return a chronological list of state-change events on the network
(`network_created`, plus `network_suppressed` / `network_escalated` /
`network_closed` when the network has left `active`).

**Permission**: `fraud:read` — query params: `tenant_id` (required), `limit`
(1–500, default 50)

`APIResponse` envelope; `data` is a list of `{event, at, detail}` entries.

---

## POST /v1/fraud/networks/{network_id}/refresh

Re-run the detection pipeline on the existing anchor entities and update risk
scores, member list, and evidence.

**Permission**: `fraud:evaluate` — query params: `tenant_id` (required); no
request body.

---

## POST /v1/fraud/networks/{network_id}/open-investigation

Create a new investigation case from this network (subjects capped at the
first 20 members; network evidence is copied onto the case). Emits
`INVESTIGATION_CASE_CREATED`.

**Permission**: `fraud:evaluate`

**Request**

```json
{
  "tenant_id": "t1",
  "title": "Circular ring investigation",
  "created_by": "analyst-42"
}
```

- `title` is optional; a default is derived from the network type and ID.
- `created_by` is required.

**Response 200**

```json
{ "case_id": "case-999", "title": "Circular ring investigation", "status": "open", "created_at": "…" }
```

---

## POST /v1/fraud/networks/{network_id}/annotate

Append a text annotation to the network. Returns the updated network record.

**Permission**: `fraud:evaluate`

**Request**

```json
{
  "tenant_id": "t1",
  "body": "Reviewed by analyst team — confirmed mule activity",
  "author_id": "analyst-42"
}
```

---

## POST /v1/fraud/networks/{network_id}/suppress

Mark the network as suppressed (analyst reviewed, no action needed). Returns
the updated network with `status: "suppressed"`.

**Permission**: `fraud:evaluate`

**Request**

```json
{
  "tenant_id": "t1",
  "reason": "False positive — entities are affiliated payment processors"
}
```

---

## POST /v1/fraud/networks/{network_id}/escalate

Mark the network as escalated for senior analyst or compliance review.

**Permission**: `fraud:evaluate`

**Request**: `{ "tenant_id": "t1", "reason": "…" }` (`reason` optional)

**Response 200**: Returns the updated network with `status: "escalated"`.

---

## Error Responses

| Status | When |
|---|---|
| 404 | Feature disabled or network not found / wrong tenant |
| 403 | Insufficient permission, or `tenant_id` does not match the authenticated tenant |
| 422 | Invalid request body |
