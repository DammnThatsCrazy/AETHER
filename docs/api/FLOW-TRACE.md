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
last_synced_commit: "4e6fdad"
---

# Flow Trace API Reference

Base path: `/v1/flow-trace`

Feature flag: `FEATURE_FLOW_TRACE=true` required. Returns 404 when disabled.

Every endpoint takes the tenant either in the request body (`tenant_id`, POST
endpoints) or as a required `tenant_id` query parameter (GET endpoints); a
mismatch with the authenticated tenant returns 403.

Graph projection note: trace writes are projected into the universal graph
through the `GraphMutationGateway` (FLOW_TRACE `node_versioned` plus
`PART_OF_FLOW_TRACE` / `HAS_SINK` / `HAS_SOURCE` / `ATTACHED_TO_CASE`
`edge_created` intents); projection failure is logged and never fails the
API call.

---

## POST /v1/flow-trace/trace

Run a BFS traversal from the anchor entity and persist the result.

**Permission**: `fraud:evaluate`

**Request**

```json
{
  "tenant_id": "t1",
  "anchor_entity_id": "e-suspect-001",
  "direction": "downstream",
  "max_hops": 5,
  "min_amount_usd": 100.0,
  "label": "Suspect ring probe"
}
```

- `tenant_id`: required; must match the authenticated tenant
- `direction`: `"upstream"` | `"downstream"` | `"both"` (default `"downstream"`)
- `max_hops`: 1–20, default 6; effective value is capped at the platform limit
  `FLOW_TRACE_MAX_HOPS` (default 10)
- `min_amount_usd`: optional (≥ 0); transfers below this threshold are excluded
- `label`, `metadata`: optional

**Response 200** — the persisted trace record (returned directly, not wrapped
in an envelope):

```json
{
  "id": "ft-xyz789",
  "tenant_id": "t1",
  "anchor_entity_id": "e-suspect-001",
  "direction": "downstream",
  "label": "Suspect ring probe",
  "status": "complete",
  "path_count": 4,
  "node_count": 9,
  "source_nodes": ["e-suspect-001"],
  "sink_nodes": ["e-cash-out-3"],
  "aggregation_points": ["e-consolidator-2"],
  "cycle_detected": true,
  "cycle_nodes": ["e-mule-7"],
  "risk_score": 81.2,
  "pattern_tags": ["layering", "mule_chain"],
  "evidence_refs": [],
  "created_at": "2026-06-21T10:30:00Z",
  "completed_at": "2026-06-21T10:30:01Z",
  "metadata": {}
}
```

Node/path details are not inlined on the trace record; fetch them via the
`/paths`, `/sources`, `/sinks`, and `/cycles` sub-resources.

Pattern tag vocabulary: `layering`, `smurfing`, `structuring`, `round_trip`,
`aggregation`, `dispersion`, `mule_chain`, `cross_chain`, `rapid_movement`,
`dormant_activation`, `high_velocity`, `split_deposit`, `merge_withdrawal`,
`delegation_relay`.

Publishing: emits `FLOW_TRACE_CREATED` and `FLOW_TRACE_COMPLETED` events.

---

## GET /v1/flow-trace

List flow traces for the authenticated tenant.

**Permission**: `fraud:read`

**Query params**: `tenant_id` (required), `limit` (1–200, default 50)

**Response 200** — standard `APIResponse` envelope; `data` is the list of
trace records, count lives in `meta`:

```json
{
  "data": [ { "id": "ft-xyz789", "...": "..." } ],
  "status": "success",
  "timestamp": "2026-06-21T10:30:00Z",
  "meta": { "count": 7, "request_id": "…", "timestamp": "…" }
}
```

---

## GET /v1/flow-trace/{trace_id}

Get a single trace by ID (returned directly, same shape as the POST response).
Returns 404 if the trace does not belong to the tenant.

**Permission**: `fraud:read`

**Query params**: `tenant_id` (required)

---

## GET /v1/flow-trace/{trace_id}/paths

Return the paths discovered in the trace with pattern tags, hop counts, and
risk scores.

**Permission**: `fraud:read`

**Query params**: `tenant_id` (required), `limit` (1–1000, default 100)

**Response 200** — `APIResponse` envelope; `data` is a list of path records:

```json
{
  "data": [
    {
      "id": "path-001",
      "trace_id": "ft-xyz789",
      "path_nodes": ["e1", "e2"],
      "path_edges": ["edge-1"],
      "hop_count": 2,
      "total_amount_usd": 50000.0,
      "risk_score": 71.5,
      "pattern_tags": ["layering", "dispersion"],
      "contains_cycle": false,
      "passes_through_sink": true,
      "passes_through_source": true,
      "discovered_at": "2026-06-21T10:30:00Z",
      "metadata": {}
    }
  ],
  "status": "success",
  "meta": { "count": 4 }
}
```

---

## GET /v1/flow-trace/{trace_id}/sources

Return the identified source (injection) node IDs for the trace.

**Permission**: `fraud:read` — query params: `tenant_id` (required)

`APIResponse` envelope; `data` is a list of entity IDs.

---

## GET /v1/flow-trace/{trace_id}/sinks

Return the identified sink (terminal recipient) node IDs for the trace.

**Permission**: `fraud:read` — query params: `tenant_id` (required)

`APIResponse` envelope; `data` is a list of entity IDs.

---

## GET /v1/flow-trace/{trace_id}/cycles

Return cycle information: whether cycles were detected and which nodes are
involved.

**Permission**: `fraud:read` — query params: `tenant_id` (required)

**Response 200** (returned directly):

```json
{ "trace_id": "ft-xyz789", "cycle_detected": true, "cycle_nodes": ["e-mule-7"] }
```

---

## GET /v1/flow-trace/{trace_id}/timeline

Return a chronological list of lifecycle events on the trace
(`trace_created`, and `trace_completed` when a completion time exists).

**Permission**: `fraud:read` — query params: `tenant_id` (required)

`APIResponse` envelope; `data` is a list of `{event, at, detail}` entries.

---

## POST /v1/flow-trace/{trace_id}/attach

Attach the trace to an investigation case: appends a flow-trace evidence ref
(`uri: aether://flow-trace/{trace_id}`) to the case and projects an
`ATTACHED_TO_CASE` edge. The case must exist and belong to the same tenant.

**Permission**: `fraud:evaluate`

**Request**

```json
{
  "tenant_id": "t1",
  "case_id": "case-999"
}
```

---

## Error Responses

| Status | When |
|---|---|
| 404 | Feature disabled, trace not found / wrong tenant, or attach target case not found |
| 403 | Insufficient permission, or `tenant_id` does not match the authenticated tenant |
| 422 | Invalid request body (bad direction, hops out of range) |
