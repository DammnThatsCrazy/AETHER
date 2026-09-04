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
last_synced_commit: "845b1c14"
reviewed_source_commits:
  - commit: "54eaac5d"
    reason: "Reviewed the staging first-admin bootstrap change; flow-trace behavior and contracts are unaffected."
---

# Flow of Funds Trace

The Flow of Funds Trace service executes a BFS traversal over the transfer graph to map how money enters, moves through, and exits a set of entities. It identifies sources, sinks, aggregation points, cycle nodes, and assigns pattern tags to each discovered path.

---

## Concept

Given an anchor entity, the traversal engine (`FlowTraceEngine`):

1. Expands the frontier hop by hop, fetching each frontier entity's transfers
   from `TransferRepository` on demand (`from_entity_id` /`to_entity_id`
   filtered by `tenant_id`, up to 200 transfers per direction per node)
2. Executes iterative BFS up to `max_hops` hops in the requested direction
   (`downstream` follows outbound transfers, `upstream` inbound, `both` runs
   both expansions from every frontier node)
3. Skips transfers below `min_amount_usd` when set, and never walks the same
   directed edge twice
4. Detects cycles when a transfer lands on an entity already on the current
   path — the cycle members are recorded and a `round_trip`-tagged path is
   emitted
5. Accumulates per-node `total_received_usd` / `total_sent_usd`, then
   identifies sources, sinks, and aggregation points from those flow totals
6. Tags paths with pattern labels and scores each path and the overall trace

---

## Traversal Algorithm

```
BFS from anchor:
  visited_edges = set()
  visited_bfs = {anchor: 0}            # entity → minimum hop reached
  queue = [(anchor, 0, [anchor], 0.0)] # (entity, hop, path, path_amount)

  while queue:
    current, hop, path, amt = queue.popleft()
    if hop >= max_hops: continue

    for transfer in transfers_of(current, direction):   # ≤200/direction
      neighbor = other_end(transfer)
      if transfer.amount < min_amount_usd: continue
      if (current, neighbor) in visited_edges: continue
      visited_edges.add((current, neighbor))
      update neighbor.total_received_usd / current.total_sent_usd

      if neighbor in path:
        cycle_detected = True; record cycle members
        emit path tagged "round_trip" (downstream direction)
        continue

      if hop + 1 <= visited_bfs.get(neighbor, ∞):   # allow shorter re-reach
        visited_bfs[neighbor] = hop + 1
        queue.append((neighbor, hop + 1, path + [neighbor], amt + transfer.amount))
```

When no cycle paths were emitted, one terminal path per discovered node is
built (anchor→node downstream, node→anchor upstream) and tagged.

---

## Pattern Tags

The canonical `PatternTag` vocabulary (14 values): `layering`, `smurfing`,
`structuring`, `round_trip`, `aggregation`, `dispersion`, `mule_chain`,
`cross_chain`, `rapid_movement`, `dormant_activation`, `high_velocity`,
`split_deposit`, `merge_withdrawal`, `delegation_relay`.

Tags currently assigned by the traversal engine:

| Tag | Assigned when |
|---|---|
| `round_trip` | The path contains (or the trace detected) a cycle |
| `mule_chain` | The path's node is an identified sink |
| `dispersion` | The path's node is an identified source that sent > $10,000 |
| `layering` | The node's inflow and outflow balance within 5% (pass-through behavior) |

The remaining vocabulary values are reserved for detector- and backend-side
classification and appear on paths via the shared `FlowTracePath.pattern_tags`
field.

---

## Sink and Source Identification

Identification is **flow-amount based**, not degree based:

- **Source** (injection point): sent > 0 and received = 0, or sent more than
  2× what it received
- **Sink** (final recipient): received > 0 and sent = 0, or received more than
  2× what it sent
- **Aggregation point** (converging flow): both inflow and outflow non-zero
  with a received/sent ratio between 0.5 and 2.0 (pass-through consolidators)

The anchor entity is excluded from source/sink identification.

---

## API Example

```bash
# Trace downstream from an entity (fraud:evaluate permission)
curl -X POST /v1/flow-trace/trace \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "t1",
    "anchor_entity_id": "e-suspect-001",
    "direction": "downstream",
    "max_hops": 5,
    "min_amount_usd": 100
  }'

# Response — the persisted trace record (returned directly, not wrapped)
{
  "id": "ft-xyz789",
  "tenant_id": "t1",
  "anchor_entity_id": "e-suspect-001",
  "direction": "downstream",
  "status": "complete",
  "path_count": 4,
  "node_count": 9,
  "cycle_detected": true,
  "cycle_nodes": ["e-mule-7"],
  "source_nodes": ["e-suspect-001"],
  "sink_nodes": ["e-cash-out-3"],
  "aggregation_points": ["e-consolidator-2"],
  "pattern_tags": ["round_trip", "mule_chain"],
  "risk_score": 78.3,
  "created_at": "2026-06-21T..."
}
```

Paths, sources, sinks, and cycles are fetched via the `/v1/flow-trace/{id}/*`
sub-resources — see `docs/api/FLOW-TRACE.md`.

---

## Scoring

Pure functions in `services/flow_trace/scoring.py`; all scores in [0, 100].

### Path Score (`score_path`)

| Component | Weight | Normalization |
|---|---|---|
| Path depth (hops) | 25% | `min(hop_count / 10, 1)` |
| Total amount | 25% | `min(log1p(amount) / log1p(1_000_000), 1)` |
| Cycle in path | 20% | binary |
| Passes through sink | 15% | binary |
| Passes through source | 10% | binary |
| Pattern breadth | 5% | `min(pattern_count / 5, 1)` |

### Trace Score (`score_trace`)

| Component | Weight | Normalization |
|---|---|---|
| Max path risk | 35% | direct |
| Average path risk | 25% | direct |
| Cycle detected | 20% | binary |
| Structural complexity | 15% | `min((sources + sinks + aggregation) / 20, 1)` |
| Path count | 5% | `min(total_path_count / 50, 1)` |

---

## Limits

| Parameter | Default | Max |
|---|---|---|
| `max_hops` | 6 | request accepts 1–20; effective value capped at `FLOW_TRACE_MAX_HOPS` (default 10) |
| `min_amount_usd` | unset | — |
| Transfers fetched per node per direction | 200 | 200 |
| Paths returned per `GET /{id}/paths` | 100 | 1000 |
| Traces returned per `GET /v1/flow-trace` | 50 | 200 |

---

## Feature Flag

```
FEATURE_FLOW_TRACE=true   # Enable /v1/flow-trace/* endpoints
FLOW_TRACE_MAX_HOPS=10    # Override platform max
```

---

## Tenant Isolation

Every transfer lookup is filtered by `tenant_id`. Traces from one tenant cannot traverse into another tenant's transfer graph. All trace artifacts (FlowTrace, FlowTracePath records) are tagged with `tenant_id` at creation and all subsequent reads enforce the same filter.

## Graph Projection

Trace writes are projected into the universal graph through the
`GraphMutationGateway` (FLOW_TRACE `node_versioned`, plus
`PART_OF_FLOW_TRACE` / `HAS_SINK` / `HAS_SOURCE` / `ATTACHED_TO_CASE`
`edge_created` intents). Projection failures are logged and never fail the API
call.
