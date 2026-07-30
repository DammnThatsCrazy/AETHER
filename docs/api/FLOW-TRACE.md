---
title: Flow Trace API Reference
slug: api/flow-trace
section: api
visibility: I
audience: [dev-senior, security, architect]
status: stable
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/flow_trace/routes.py
  - Backend Architecture/aether-backend/services/flow_trace/traversal.py
last_synced_commit: "3283497"
---

# Flow Trace API Reference

Base path: `/v1/flow-trace`

Feature flag: `FEATURE_FLOW_TRACE=true` required. Returns 404 when disabled.

---

## POST /v1/flow-trace/trace

Run a BFS traversal from the anchor entity and persist the result.

**Permission**: `fraud:write`

**Request**

```json
{
  "anchor_entity_id": "e-suspect-001",
  "direction": "downstream",
  "max_hops": 5,
  "min_amount_usd": 100.0
}
```

- `direction`: `"upstream"` | `"downstream"` | `"both"`
- `max_hops`: 1–10 (platform max configurable via `FLOW_TRACE_MAX_HOPS`)
- `min_amount_usd`: optional filter; transfers below this threshold are excluded

**Response 200**

```json
{
  "data": {
    "id": "ft-xyz789",
    "tenant_id": "t1",
    "anchor_entity_id": "e-suspect-001",
    "direction": "downstream",
    "max_hops": 5,
    "cycle_detected": true,
    "cycle_nodes": ["e-mule-7"],
    "source_nodes": ["e-suspect-001"],
    "sink_nodes": ["e-cash-out-3"],
    "aggregation_points": ["e-consolidator-2"],
    "nodes": [
      { "entity_id": "e-suspect-001", "kind": "source", "risk_score": 78.0, "depth": 0 },
      { "entity_id": "e-mule-7", "kind": "intermediary", "risk_score": 65.0, "depth": 1 }
    ],
    "paths": [...],
    "risk_score": 81.2,
    "created_at": "2026-06-21T10:30:00Z"
  },
  "status": "ok",
  "timestamp": "2026-06-21T10:30:00Z"
}
```

---

## GET /v1/flow-trace

List flow traces for the authenticated tenant.

**Permission**: `fraud:read`

**Query params**: `limit`

**Response 200**

```json
{
  "data": {
    "traces": [...],
    "count": 7,
    "tenant_id": "t1"
  }
}
```

---

## GET /v1/flow-trace/{trace_id}

Get a single trace by ID. Returns 404 if the trace does not belong to the tenant.

**Permission**: `fraud:read`

---

## GET /v1/flow-trace/{trace_id}/paths

Return all paths discovered in the trace with pattern tags, hop counts, and risk scores.

**Permission**: `fraud:read`

**Response 200**

```json
{
  "data": {
    "trace_id": "ft-xyz789",
    "paths": [
      {
        "id": "path-001",
        "nodes": [
          { "entity_id": "e1", "depth": 0 },
          { "entity_id": "e2", "depth": 1 }
        ],
        "pattern_tags": ["layered", "fan_out"],
        "hop_count": 2,
        "total_amount_usd": 50000.0,
        "risk_score": 71.5
      }
    ]
  }
}
```

---

## GET /v1/flow-trace/{trace_id}/sources

Return the list of source nodes (entities with no inbound edges in the trace).

**Permission**: `fraud:read`

---

## GET /v1/flow-trace/{trace_id}/sinks

Return the list of sink nodes (entities with no outbound edges in the trace).

**Permission**: `fraud:read`

---

## GET /v1/flow-trace/{trace_id}/cycles

Return cycle information: whether cycles were detected and which nodes are involved.

**Permission**: `fraud:read`

---

## GET /v1/flow-trace/{trace_id}/timeline

Return a chronological list of events on the trace.

**Permission**: `fraud:read`

---

## POST /v1/flow-trace/{trace_id}/attach

Attach the trace to an investigation case.

**Permission**: `investigations:write`

**Request**

```json
{
  "case_id": "case-999",
  "notes": "Money movement trace supporting mule ring hypothesis"
}
```

---

## Error Responses

| Status | When |
|---|---|
| 404 | Feature disabled or trace not found / wrong tenant |
| 403 | Insufficient permission |
| 422 | Invalid request body (bad direction, hops out of range) |
