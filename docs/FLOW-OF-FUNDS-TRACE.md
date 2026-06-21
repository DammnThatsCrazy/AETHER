---
title: Flow of Funds Trace
slug: flow-of-funds-trace
section: concepts
visibility: I
audience: [security, dev-senior, ops]
status: stable
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/flow_trace/
  - Backend Architecture/aether-backend/repositories/repos.py
last_synced_commit: bf87315
---

# Flow of Funds Trace

The Flow of Funds Trace service executes a BFS traversal over the transfer graph to map how money enters, moves through, and exits a set of entities. It identifies sources, sinks, aggregation points, cycle nodes, and assigns pattern tags to each discovered path.

---

## Concept

Given an anchor entity, the traversal engine:

1. Loads all transfers for the tenant from `TransferRepository`
2. Builds an adjacency list (from_entity_id → to_entity_id)
3. Executes iterative BFS up to `max_hops` hops in the requested direction
4. Detects cycles when a visited node is re-encountered
5. Classifies each path with pattern tags
6. Identifies sources (no inbound in the trace), sinks (no outbound in the trace), and aggregation points (high fan-in)
7. Scores each path and the overall trace

---

## Traversal Algorithm

```
BFS from anchor:
  visited_nodes = {anchor}
  visited_edges = set()
  queue = [(anchor, 0, [anchor])]

  while queue:
    current, depth, path = queue.popleft()
    if depth >= max_hops: continue

    for neighbor in adjacency[current]:
      edge_key = (current, neighbor)
      if edge_key in visited_edges: continue
      visited_edges.add(edge_key)

      if neighbor in visited_nodes:
        cycle_detected = True
        cycle_nodes.add(neighbor)
        continue

      visited_nodes.add(neighbor)
      queue.append((neighbor, depth+1, path+[neighbor]))
      if not adjacency[neighbor]:
        sink_nodes.add(neighbor)
```

Upstream direction reverses the adjacency. Both direction runs two passes and merges results.

---

## Pattern Tags (14 values)

| Tag | Meaning |
|---|---|
| `circular` | Path forms a cycle |
| `cycle_member` | Node is part of a detected cycle |
| `split` | Single source fans out to 3+ receivers |
| `merge` | 3+ sources feed into single receiver |
| `fan_out` | High out-degree node |
| `fan_in` | High in-degree node (aggregation point) |
| `layered` | 4+ hop path with intermediate nodes |
| `passes_through_mule` | Path includes a known mule-role entity |
| `passes_through_hub` | Path includes a hub-role entity |
| `rapid_movement` | Transfers within very short time windows |
| `cross_chain` | Path crosses chain boundaries (via wallet links) |
| `single_chain` | All hops on same chain |
| `structural_anomaly` | Graph topology deviation |
| `unknown` | Unclassified pattern |

---

## Sink and Source Identification

- **Source**: Entity with no inbound transfers within the traced subgraph (money origin)
- **Sink**: Entity with no outbound transfers within the traced subgraph (money destination)
- **Aggregation Point**: Entity with in-degree ≥ 3 within the trace

---

## API Example

```bash
# Trace downstream from an entity
curl -X POST /v1/flow-trace/trace \
  -H "Content-Type: application/json" \
  -d '{
    "anchor_entity_id": "e-suspect-001",
    "direction": "downstream",
    "max_hops": 5,
    "min_amount_usd": 100
  }'

# Response
{
  "data": {
    "id": "ft-xyz789",
    "tenant_id": "t1",
    "anchor_entity_id": "e-suspect-001",
    "direction": "downstream",
    "cycle_detected": true,
    "cycle_nodes": ["e-mule-7"],
    "source_nodes": ["e-suspect-001"],
    "sink_nodes": ["e-cash-out-3"],
    "aggregation_points": ["e-consolidator-2"],
    "paths": [...],
    "risk_score": 78.3
  },
  "status": "ok",
  "timestamp": "2026-06-21T..."
}
```

---

## Scoring

### Path Score

```
base = mean(entity_risk_scores_on_path) * 0.4
+ (20.0 if contains_cycle else 0.0)
+ (15.0 if passes_through_mule else 0.0)
+ min(hop_count / max_hops * 10.0, 10.0)
+ log10(max(total_amount_usd, 1)) / log10(10_000_001) * 15.0
```

### Trace Score

```
base = mean(path_risk_scores) * 0.5
+ (20.0 if cycle_detected else 0.0)
+ min(source_count, 5) * 2.0
+ min(sink_count, 5) * 3.0
+ min(aggregation_point_count, 3) * 5.0
+ min(total_path_count, 20) / 20.0 * 10.0
```

---

## Limits

| Parameter | Default | Max |
|---|---|---|
| `max_hops` | 5 | 10 (platform config `FLOW_TRACE_MAX_HOPS`) |
| `min_amount_usd` | 0 | — |
| Paths returned per trace | all | 1000 |
| Nodes per trace | all | 500 |

---

## Feature Flag

```
FEATURE_FLOW_TRACE=true   # Enable /v1/flow-trace/* endpoints
FLOW_TRACE_MAX_HOPS=10    # Override platform max
```

---

## Tenant Isolation

Every transfer lookup is filtered by `tenant_id`. Traces from one tenant cannot traverse into another tenant's transfer graph. All trace artifacts (FlowTrace, FlowTracePath records) are tagged with `tenant_id` at creation and all subsequent reads enforce the same filter.
