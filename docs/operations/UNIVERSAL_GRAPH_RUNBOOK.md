---
title: Universal Intelligence Graph Operations Runbook
slug: operations/universal-graph-runbook
section: operations
visibility: I
audience: [ops, dev-senior, ai]
status: stable
since_version: "8.10.0"
canonical_owner: sre@aether
---
# Universal Intelligence Graph Operations Runbook

---

## Graph Mutation Lag

**Symptom:** `meta.freshness_seconds` in query responses exceeds SLO (>300s for real-time, >3600s for batch paths). Dashboard shows "Graph data may be stale" banner.

**Causes and checks:**
1. Lake pipeline backlog — check `silver_lag_seconds` and `gold_lag_seconds` Grafana panels
2. Neptune write throttling — check Neptune CloudWatch `WriteThrottleEvents`
3. `graph_mutations.py` worker crash — check Celery worker logs: `celery -A aether worker --loglevel=info`

**Resolution:**
- If lake backlog: scale up lake tier workers or reduce event fanout
- If Neptune throttling: check provisioned IOPS; switch to serverless if spike is temporary
- If worker crash: restart worker, check dead-letter queue for failed mutation tasks

---

## Replay Failure

**Symptom:** `POST /v1/graph/replay` returns 500 or empty results despite data existing in the graph.

**Diagnosis:**
1. Check that nodes have `valid_from` populated — pre-Phase-3 nodes use `created_at` as fallback
2. Check `as_of` format: must be ISO 8601 with timezone (e.g., `2026-01-01T00:00:00+00:00`)
3. Check that edges connecting the anchor also have temporal properties

**Resolution:**
- For pre-Phase-3 data missing `valid_from`: run backfill script to copy `created_at → valid_from`
- For timezone issues: normalize all as_of inputs to UTC before passing to `temporal_bfs`

---

## Cache Contamination

**Symptom:** Queries return stale or incorrect data after a tenant data update. Cache hit rate unexpectedly high.

**Diagnosis:**
1. Check cache key used: `aether:graph:query:<tenant_id>:<query_hash>:...`
2. Verify `tenant_id` is not empty in the key — an empty tenant_id segment allows cross-tenant collisions
3. Check TTL: SHORT TTL is ~60s, MEDIUM TTL is ~300s. Stale data should self-heal within TTL.

**Resolution:**
- Flush tenant-specific cache: `redis-cli --scan --pattern "aether:graph:*:<tenant_id>:*" | xargs redis-cli DEL`
- For cross-tenant contamination (critical): flush all graph cache keys and increment `contract_version` to invalidate all existing keys
- Alert on `graph_tenant_isolation_violation_total > 0` — this is a P0 incident

**Prevention:** All cache key methods in `CacheKey` class include `tenant_id`. Do not add graph cache keys outside this class.

---

## Neptune Degradation

**Symptom:** Graph queries time out or return partial results; `GraphClient` logs `Neptune connection failed: ...`

**Checks:**
1. Neptune cluster status: AWS Console → Neptune → Clusters → Status
2. Check `graph_query_duration_seconds` P95 — if >2s, Neptune is degraded
3. Check if `NEPTUNE_ENDPOINT` env var is set correctly in the deployment

**Fallback mode:**
The `GraphClient` does NOT automatically fall back to in-memory on Neptune failure. In non-local environments, Neptune failure returns 500. This is intentional — silent fallback to in-memory would serve empty graphs.

**Resolution:**
1. If Neptune is degraded: failover to replica endpoint if available
2. If replica not available: set feature flags `IG_SEMANTIC_ZOOM=false` and `IG_FLEET_GRAPH=false` to reduce graph load
3. For prolonged outage: serve cached responses by extending TTL (MEDIUM → LONG)

---

## High Query Budget Usage

**Symptom:** `meta.budget_used` consistently near 1.0; many `meta.truncated: true` responses. `graph_budget_exceeded_total` counter rising.

**Causes:**
- Anchor nodes with very high fan-out (e.g., campaign nodes with millions of member edges)
- Deep traversals (`depth=6`) on dense subgraphs
- Filter language missing selective filters (scanning too many nodes)

**Resolution:**
1. Add more selective filters to queries (e.g., filter on `lifecycle_state=active` before traversal)
2. Reduce default `depth` in frontend queries (default is 2; only increase when needed)
3. For campaign/cluster nodes: use semantic zoom — fetch aggregates first, then expand specific clusters
4. If a specific anchor is causing overload: add it to the high-fanout allowlist and set a lower per-anchor limit

---

## Operator Session Runaway

**Symptom:** A Kyber operator session has been active for an unusually long time (>4 hours). Audit log shows queries from an operator without a corresponding exit event.

**Diagnosis:**
1. Check active sessions: `GET /v1/kyber/operator/tenant-entry` (admin endpoint)
2. Review audit log for operator_id and activity during session

**Resolution:**
1. Force-revoke session: `DELETE /v1/kyber/operator/tenant-entry?session_id=<id>` (admin privilege required)
2. Notify security team if session appears unauthorized
3. Review audit records for the session — all queries are logged and cannot be deleted

---

## Missing Graph Data After DSR

**Symptom:** User reports their data is not deleted after a DSR request. Or: graph queries still return a vertex that should have been erased.

**Checks:**
1. Check DSR pipeline status: `GET /v1/consent/dsr/{dsr_id}/status`
2. Check if graph cascade was triggered: look for `GRAPH_DSR_CASCADE` audit event
3. Check if Neptune had a write failure during cascade

**Resolution:**
1. If cascade not triggered: manually trigger `POST /v1/consent/dsr/{dsr_id}/retry`
2. If Neptune write failed: re-run cascade with retry flag; check Neptune write availability
3. Verify erasure with `GET /v1/graph/query` for the entity — should return empty result or tombstoned vertex

---

## SLO Reference

| Operation | P50 target | P95 target | Alert threshold |
|-----------|-----------|-----------|----------------|
| Graph query (depth 2) | 200ms | 500ms | P95 > 1s |
| BFS traversal (depth 3) | 300ms | 800ms | P95 > 2s |
| Cluster360 overview | 200ms | 500ms | P95 > 1s |
| Temporal replay | 500ms | 1s | P95 > 3s |
| Facet computation | 300ms | 600ms | P95 > 1.5s |

## Key Metrics

| Metric | Type | Labels | Alert |
|--------|------|--------|-------|
| `graph_query_duration_seconds` | histogram | route, truncated | P95 > threshold |
| `graph_query_node_count` | histogram | route | — |
| `graph_budget_exceeded_total` | counter | budget_type | Rate > 5/min |
| `graph_tenant_isolation_violation_total` | counter | — | **> 0 → P0** |
| `graph_query_cache_hit` | counter | — | Hit rate < 20% |
