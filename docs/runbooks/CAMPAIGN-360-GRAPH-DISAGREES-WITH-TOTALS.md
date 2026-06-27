---
title: Runbook — Graph Results Disagree With Campaign Totals
slug: runbooks/campaign-360-graph-disagrees
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/campaign/exploration.py
  - Backend Architecture/aether-backend/services/campaign/routes.py
last_synced_commit: e279268
---

# Runbook — Graph Results Disagree With Campaign Totals

## Alert condition

The Campaign 360 Graph tab shows fewer entities (nodes) than the Overview tab's
population counts indicate, OR the graph shows nodes/edges that are not reflected
in the population or cluster lists.

## What it means

This discrepancy is usually expected behavior due to graph truncation or query
budget limits. It becomes a real issue when the graph consistently shows
zero campaign-linked entities despite the overview showing non-zero population
counts.

---

## Case 1: Graph shows fewer nodes than expected (expected behavior)

The graph enforces hard limits: `max_nodes ≤ 500`, `max_edges ≤ 1500`,
`depth ≤ 3`. When these are hit, the response returns `truncated: true` with
a `truncation_reason`.

**Diagnosis:**
```bash
curl -X POST "$API_BASE/v1/campaigns/$CAMPAIGN_ID/graph" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"depth": 2, "max_nodes": 500, "max_edges": 1500}' \
  | jq '{truncated: .truncated, reason: .truncation_reason, nodes: .node_count, edges: .edge_count}'
```

**Resolution:** This is expected. Use the `continuation_token` from the response
to paginate the graph, or reduce the depth and increase the node budget per page.
No operator action required unless the tenant reports confusion.

---

## Case 2: Graph shows zero nodes (unexpected)

The campaign anchor node should always appear even for campaigns with zero
entities.

**Diagnosis steps:**

1. **Verify the campaign anchor node is present**:
   ```bash
   curl -X POST "$API_BASE/v1/campaigns/$CAMPAIGN_ID/graph" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"depth": 1, "max_nodes": 10}' \
     | jq ".nodes[] | select(.id == \"$CAMPAIGN_ID\")"
   ```
   If this returns nothing, the graph anchor is not being seeded. This is a bug.

2. **Check the graph store** for the campaign vertex:
   The campaign vertex is created when a campaign is created via `POST /v1/campaigns`.
   If the campaign was created before graph vertex materialization was enabled,
   the vertex may not exist.

3. **Check the explorer's `get_graph_anchor` log**:
   Look for `WARNING: campaign vertex not found in graph store` in the service logs.

**Resolution:**
Re-materialize the campaign vertex by triggering a graph refresh:
```bash
curl -X POST "$API_BASE/v1/campaigns/$CAMPAIGN_ID/graph" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"depth": 1}'
```
If the campaign vertex is still missing after this call, escalate to the platform engineering team
to manually insert the campaign vertex into the graph store.

---

## Case 3: Graph shows entities not in population list

Entities in the graph but not in the population list usually means:
- The entity had a touchpoint that was later deleted (ghost node)
- The graph was persisted before a touchpoint correction was applied
- The population list is filtered by a time window but the graph is not

**Diagnosis:**
1. Query the population with no time filter and compare with the graph node set.
2. Check if any touchpoints for the campaign were deleted or corrected recently.

**Resolution:**
- If touchpoints were corrected: trigger a graph refresh for the campaign.
- If it's a time window mismatch: this is expected; inform the operator.
- If ghost nodes persist after a graph refresh: escalate to platform engineering.

---

## Case 4: Graph revenue disagrees with overview revenue

The graph does not display revenue figures — it shows entity relationships only.
If a tenant reports that the "graph shows different revenue," they are comparing
the Population tab (which shows `attributed_revenue` per entity) with the Overview
tab (which aggregates across all entities). These will naturally differ if:

- A time window is set on the Population tab but not on the Overview tab
- The Population tab is showing a subset population tier (e.g., `attributed` only)

**Resolution:** Explain to the tenant that the Overview tab always shows campaign-level
totals regardless of tab filters. The Population tab respects the active time
window and population tier.

---

## Escalation path

| Condition | Escalate to |
|-----------|------------|
| Campaign anchor node missing after graph refresh | Platform engineering |
| Graph query times out at depth ≤ 2 with < 100 nodes | Database infrastructure (query plan regression) |
| `truncated: true` even at `max_nodes=500, max_edges=1500` | Expected; document for tenant |
| Ghost nodes persist after refresh | Platform engineering with node IDs |
