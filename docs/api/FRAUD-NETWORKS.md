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
last_synced_commit: bf87315
---

# Fraud Networks API Reference

Base path: `/v1/fraud/networks`

Feature flag: `FEATURE_FRAUD_NETWORKS=true` required. Returns 404 when disabled.

---

## POST /v1/fraud/networks/build

Run the full detection pipeline for a set of anchor entities and persist a new fraud network.

**Permission**: `fraud:write`

**Request**

```json
{
  "anchor_entity_ids": ["e1", "e2"],
  "network_type": "circular_transfer",
  "label": "Q2 ring",
  "notes": "Detected via anomaly alert"
}
```

**Response 200**

```json
{
  "data": {
    "id": "fn-abc123",
    "tenant_id": "t1",
    "network_type": "circular_transfer",
    "label": "Q2 ring",
    "status": "active",
    "risk_score": 82.4,
    "confidence_score": 0.91,
    "member_count": 3,
    "evidence_refs": [
      { "id": "ev-001", "type": "TRANSFER_RECORD", "source": "fraud_networks", "confidence": 0.9 }
    ],
    "created_at": "2026-06-21T10:00:00Z",
    "updated_at": "2026-06-21T10:00:00Z"
  },
  "status": "ok",
  "timestamp": "2026-06-21T10:00:00Z"
}
```

---

## GET /v1/fraud/networks

List networks for the authenticated tenant.

**Permission**: `fraud:read`

**Query params**: `status`, `limit`

**Response 200**

```json
{
  "data": {
    "networks": [...],
    "count": 12,
    "tenant_id": "t1"
  }
}
```

---

## GET /v1/fraud/networks/{network_id}

Get a single network by ID. Returns 404 if the network does not belong to the tenant.

**Permission**: `fraud:read`

---

## GET /v1/fraud/networks/{network_id}/graph

Returns a Cytoscape-ready graph payload with nodes and edges for the network.

**Permission**: `fraud:read`

**Response 200**

```json
{
  "data": {
    "network_id": "fn-abc123",
    "nodes": [
      { "id": "e1", "entity_id": "e1", "role": "hub", "risk_score": 85.0 }
    ],
    "edges": [
      { "id": "edge-001", "from": "e1", "to": "e2", "link_type": "MEMBER_OF_FRAUD_NETWORK", "risk_score": 72.0 }
    ]
  }
}
```

---

## GET /v1/fraud/networks/{network_id}/members

List all members of the network with roles and risk scores.

**Permission**: `fraud:read`

---

## GET /v1/fraud/networks/{network_id}/evidence

Return all evidence refs associated with the network.

**Permission**: `fraud:read`

---

## GET /v1/fraud/networks/{network_id}/timeline

Return a chronological list of events on the network (created, refreshed, escalated, suppressed, annotated).

**Permission**: `fraud:read`

---

## POST /v1/fraud/networks/{network_id}/refresh

Re-run the detection pipeline on existing anchor entities and update risk scores, member list, and evidence.

**Permission**: `fraud:write`

---

## POST /v1/fraud/networks/{network_id}/open-investigation

Create a new investigation case from this network or attach it to an existing one.

**Permission**: `investigations:write`

**Request**

```json
{
  "title": "Circular ring investigation",
  "notes": "Escalating to compliance team"
}
```

---

## POST /v1/fraud/networks/{network_id}/annotate

Append a text annotation to the network timeline.

**Permission**: `fraud:write`

**Request**

```json
{
  "body": "Reviewed by analyst team — confirmed mule activity",
  "author_id": "analyst-42"
}
```

---

## POST /v1/fraud/networks/{network_id}/suppress

Mark the network as suppressed (false positive or resolved).

**Permission**: `fraud:escalate`

**Request**

```json
{
  "reason": "False positive — entities are affiliated payment processors"
}
```

---

## POST /v1/fraud/networks/{network_id}/escalate

Mark the network as escalated for immediate review.

**Permission**: `fraud:escalate`

**Response 200**: Returns updated network with `status: "escalated"`.

---

## Error Responses

| Status | When |
|---|---|
| 404 | Feature disabled or network not found / wrong tenant |
| 403 | Insufficient permission |
| 422 | Invalid request body |
