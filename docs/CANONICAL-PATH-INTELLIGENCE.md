---
title: Canonical Path Intelligence
last_synced_commit: ""
source_files:
  - Backend Architecture/aether-backend/services/operational_intelligence/models.py
  - Backend Architecture/aether-backend/services/operational_intelligence/routes.py
  - Backend Architecture/aether-backend/shared/graph/path_scoring.py
  - packages/shared/operational-intelligence.ts
---

# Canonical Path Intelligence

Path Intelligence (Phase 20) adds canonical ordered-path types, a versioned scoring system, stronger traversal algorithms, a dedicated API surface, traversal snapshot persistence, and async deep-traversal jobs on top of the Phase 1–19 Universal Intelligence Graph.

---

## RelationshipPath Contract

A `RelationshipPath` is the stable unit of graph intelligence output. Every path is uniquely identified by a SHA-256 digest of its ordered node sequence.

```
path_id            SHA-256[:32] of ":".join(ordered_node_ids)
tenant_id          Owning tenant — all downstream reads must re-check this
source_id          Start vertex ID
target_id          End vertex ID
ordered_node_ids   Node IDs in traversal order
ordered_edge_ids   Synthetic edge keys: "{from}:{to}:{type}"
nodes              PathNode[] — each node with its hop index
edges              PathEdge[] — each edge with confidence and causality_class
hop_count          len(nodes) - 1
path_confidence    Scored output (see PathScoreBreakdown formula)
evidence_coverage  Fraction of edges with a source_event_id or evidence ref
classification     Worst-case PathClassification along the path
layer_sequence     Ordered list of RelationshipLayer values (H2H/H2A/A2H/A2A)
score_breakdown    PathScoreBreakdown with all scoring components
as_of              Optional bitemporal as-of timestamp
computed_at        ISO-8601 timestamp of path computation
```

---

## PathScoreBreakdown Formula

Scoring version `"1"` (all new paths carry `scoring_version: "1"`):

```
confidences         = [edge.confidence for edge in edges]
geometric_mean      = exp(mean(log(max(c, 1e-9)) for c in confidences))
hop_penalty         = max(0.0, 1.0 - len(edges) / max_depth * 0.15)
causality_penalty   = sum of per-edge penalties:
                        0.2  for causality_class == "correlation"
                        0.1  for causality_class == "inferred_influence"
overall             = clamp(geometric_mean * hop_penalty * (1 - causality_penalty), 0, 1)
min_edge_confidence = min(confidences)
```

`overall` is the canonical path score used for ranking and filtering.

---

## PathClassification Hierarchy

Classification is always derived from the **worst** (most uncertain) `causality_class` edge in the path. It can never claim stronger causality than the weakest edge.

```
correlated          Weakest — statistical association only
inferred            No direct evidence; derived from structural patterns
attributed          Assigned via a model (e.g. Shapley, Markov)
causal_supported    Strong causal evidence present
observed            Strongest — directly witnessed event chain
mixed               More than one class present (multi-hop paths)
```

`PathExplanation.causal_language_allowed` is `false` for `correlated` paths.

---

## TraversalSnapshot Lifecycle

```
POST /v1/graph/paths (save_snapshot: true)
  → creates TraversalSnapshot{ snapshot_id, path_ids, node_ids, edge_ids, result_digest }

GET  /v1/graph/snapshots/{id}
  → returns snapshot — tenant ownership enforced fail-closed

POST /v1/graph/snapshots/{id}/compare
  → diffs two snapshots: added_node_ids, removed_node_ids, added_edge_ids, removed_edge_ids

POST /v1/investigations/{case_id}/snapshot { snapshot_id }
  → attaches snapshot to investigation case (same-tenant check required)

GET  /v1/investigations/{case_id}/paths
  → returns path_ids from the linked snapshot
```

`result_digest` is SHA-256 of `sorted(node_ids + edge_ids)` and can be used for cache invalidation.

---

## API Catalogue

All endpoints require `_require_read(request, tenant_id)` as their first call.

### Path Query

```
POST /v1/graph/paths
Body: PathQuery
  tenant_id        string
  source_id        string
  target_id        string (optional for neighborhood/multi_source modes)
  mode             "shortest" | "strongest" | "k_shortest" | "temporal" |
                   "neighborhood" | "attribution" | "decision_outcome" |
                   "evidence" | "multi_source"
  k                int [1–10], default 3 (k_shortest only)
  max_depth        int [1–20], default 6
  direction        "in" | "out" | "both"
  filter           GraphQueryFilter (optional)
  as_of            ISO-8601 (optional, bitemporal replay)
  min_confidence   float [0–1], default 0.0
  include_explanation  bool, default false
  save_snapshot    bool, default false

Response: PathQueryResponse
  paths            RelationshipPath[]
  explanations     PathExplanation[]
  snapshot_id      string? (set when save_snapshot: true)
  meta             GraphResultMeta
```

### Node Expansion

```
POST /v1/graph/paths/expand
Body: NodeExpansionRequest { tenant_id, node_id, direction?, filter? }
Response: NodeExpansionResponse { node_id, added_nodes, added_edges, meta }
```

### Path Explanation

```
POST /v1/graph/paths/explain
Body: { tenant_id, path_id }
Response: PathExplanation
  path_id, summary, why_connected, hop_narrative[],
  supporting_evidence[], contradictory_evidence[],
  score_breakdown, classification, causal_language_allowed,
  policy_ids[], computed_at
```

### Async Deep Traversal

```
POST /v1/graph/paths/jobs
Body: PathQuery (same as /paths)
  → If max_depth > 6: queues DeepTraversalJob (status: "queued")
  → Otherwise: redirects to synchronous /paths response

GET  /v1/graph/paths/jobs/{job_id}?tenant_id=...
Response: DeepTraversalJob
  job_id, tenant_id, query, status, progress_pct, partial_path_ids,
  created_at, started_at?, completed_at?, error?, expires_at?
```

Job status flow: `queued → planning → running → partial → complete | failed | cancelled | expired`

### Snapshot Management

```
POST /v1/graph/snapshots
Body: SnapshotCreateRequest { tenant_id, query?, path_ids?, node_ids?, edge_ids?, graph_watermark? }
Response: TraversalSnapshot

GET  /v1/graph/snapshots/{snapshot_id}?tenant_id=...
  → Fail-closed: if snapshot.tenant_id != request.tenant_id → 403

POST /v1/graph/snapshots/{snapshot_id}/compare
Body: { tenantId, anchor, asOf, compareTo }
Response: { added_node_ids, removed_node_ids, unchanged_node_count,
            added_edge_ids, removed_edge_ids, unchanged_edge_count }
```

### Silver Reconciliation (operator-only)

```
POST /v1/graph/reconcile
  → Read-only report: orphaned vertices, duplicate edges,
    missing projections, stale identity versions
```

---

## Tenant Isolation Guarantees

1. `_require_read(request, tenant_id)` is the first call in every route — no bypass.
2. Snapshot ownership is checked explicitly (fail-closed):
   ```python
   if snapshot["tenant_id"] != authenticated_tenant.tenant_id:
       raise ForbiddenError("snapshot tenant mismatch")
   ```
3. All traversal algorithms use the two-set pattern (`visited` + `accepted`) from `traversal.py::bfs()`.
4. Investigation snapshot linkage validates same-tenant ownership before attaching.
5. `PathClassification` never claims stronger causality than the weakest edge in the path.
6. Query budgets are enforced server-side. Clients can only reduce budgets, never increase them beyond `QUERY_BUDGET_DEFAULTS`.

---

## Frontend

- **PathInspector** (`frontend/aether/src/components/graph/path-inspector.tsx`, `frontend/kyber/src/components/graph/path-inspector.tsx`): 4-tab panel (Overview / Hops / Evidence / Score). Classification uses icon + label (not color alone — accessibility requirement).
- **Graph Toolbar** (`frontend/kyber/src/components/graph/graph-toolbar.tsx`): Shortest / Strongest / K-Shortest mode selector and K input render when path mode is active.
- **Graph Page** (`frontend/aether/src/pages/graph/graph-page.tsx`): Two-node path mode calls `POST /v1/graph/paths` — no local BFS. K-path results show tabbed "Path 1 / Path 2 …" with confidence per tab. Save to Investigation wires to `POST /v1/investigations/{id}/snapshot`.
