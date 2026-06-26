---
title: Universal Intelligence Graph Security Model
slug: security/universal-graph-security-model
section: security
visibility: I
audience: [architect, dev-senior, security, ai]
status: stable
since_version: "8.10.0"
canonical_owner: security@aether
---
# Universal Intelligence Graph Security Model

---

## Tenant Isolation

### Layer 1 — API Authorization

Every `/v1/graph/*` route calls `_require_read(authed_tenant_id, request_tenant_id)` before any graph operation. A mismatch returns HTTP 403 immediately without touching the graph store.

On a mismatch, `graph_tenant_isolation_violation_total` is incremented — this counter must always be zero in production. Any non-zero value triggers a P0 alert.

### Layer 2 — Graph Store Isolation

`GraphClient` enforces tenant isolation at the storage layer:

- **In-memory (local):** vertices are stored in a dict keyed by `vertex_id`; `get_all_vertices(tenant_id)` filters by `vertex.properties["tenantId"]`. A vertex without a matching `tenantId` is silently excluded.
- **Neptune (staging/production):** all queries include `.has('tenantId', tenant_id)` in the Gremlin traversal. Neptune does not enforce RLS natively — the application enforces it.

### Layer 3 — BFS Traversal Isolation

`GraphTraversalEngine.bfs()` and `temporal_bfs()` accept a `tenant_id` parameter. During traversal, every neighbor vertex is checked for `properties["tenantId"] == tenant_id`. Cross-tenant vertices are silently dropped (fail-closed). This prevents graph traversal from accidentally crossing tenant boundaries even if a cache or store bug returned a foreign vertex.

### Layer 4 — Cache Key Isolation

All graph cache keys include `tenant_id` as the first path segment:

```
aether:graph:<type>:<tenant_id>:<query_hash>:...
```

This prevents cross-tenant cache hits even if two tenants issue identical queries. A permission change (user losing access) invalidates the cache via the `permission_hash` segment.

---

## Consent and Activation Eligibility

When a user withdraws consent:

1. `consent_state` is set to `"withdrawn"` on the vertex
2. `activation_eligible` is set to `false`
3. `lifecycle_state` transitions to `"revoked"` or `"suppressed"`

The graph API does NOT automatically hide withdrawn-consent vertices — they remain queryable. The `activation_eligible=false` flag is the signal that downstream systems (activation pipelines, campaign targeting, recommendation engines) must check before using the entity.

The consent overlay (`include_overlays: ["consent"]`) surfaces `consent_state` and `activation_eligible` per node in query results.

DSR (Data Subject Request) processing is handled by `services/consent/` and cascades to the graph:
- Soft delete: vertex `lifecycle_state = "tombstoned"`, properties redacted
- Hard delete (erasure): vertex removed from Neptune; in-memory store cleared on restart

---

## Kyber Operator Privileged Access

### Break-Glass Model

Kyber operators can access any tenant's graph data via a controlled break-glass flow:

1. Operator calls `POST /v1/kyber/operator/tenant-entry` with:
   - `tenant_id` — target tenant
   - `access_reason` — required, minimum 10 characters
   - `purpose` — one of: `incident_response`, `customer_support`, `compliance_audit`, `security_investigation`, `data_request`, `diagnostics`, `break_glass`
   - `duration_minutes` — optional, defaults to 60

2. Backend validates:
   - Caller has `kyber:operator` permission
   - `access_reason` is non-empty
   - `purpose` is a recognized value
   - Creates immutable `TenantEntrySession` audit record with timestamp, operator_id, reason, purpose

3. Session token returned. All subsequent graph queries in this session carry `operator_tenant_scope` header.

4. Operator exits via `DELETE /v1/kyber/operator/tenant-entry?session_id=<id>` — session revoked, exit timestamp recorded.

### Audit Requirements

Every operator action during a tenant session must produce an audit record including:
- `operator_id`
- `target_tenant_id`
- `access_purpose`
- `action` (query, export, etc.)
- `query_summary` (hash or description)
- `timestamp`

Audit records are immutable — they cannot be deleted or modified, even by operators with admin privileges.

### Access Controls

- `kyber:operator` permission is required to call any tenant-entry endpoint
- Without an active `TenantEntrySession`, operator graph queries return 403
- Session expiry (default 60 min) revokes access automatically
- Force-exit is available via `DELETE /v1/kyber/operator/tenant-entry` at any time
- The "Operator session active — all actions audited" banner must be shown in the Kyber UI whenever an active session exists

---

## Input Validation

### Gremlin Injection Prevention

All values written to Neptune go through `_escape_gremlin()` in `graph.py`, which escapes:
- Single quotes `'`
- Double quotes `"`
- Backticks `` ` ``
- Semicolons `;`
- Backslashes `\`

Raw Gremlin strings are never accepted from client input.

### Filter Language Operator Allowlist

The boolean filter language rejects any `FilterOperator` value not in the explicit enum. Unknown operators return HTTP 400 (not 500). This prevents operator injection attacks where crafted values could bypass filters.

### Query Budget Enforcement

All graph queries are subject to hard limits:
- `max_depth`: 6
- `max_nodes`: 500
- `max_edges`: 2000
- `timeout_seconds`: 30

Exceeding any limit returns HTTP 200 with `meta.truncated: true` — budgets are not errors, they are safety valves. The `meta.budget_used` field shows how close to the limit the query came.

---

## Non-Local Environment Hardening

In `AETHER_ENV != local`:

- JWT secret must be at least 32 bytes; startup fails with `RuntimeError` if not
- API key stubs are rejected
- All graph layer flags default to `false` — must be explicitly enabled per environment
- Neptune endpoint required for graph writes in production; in-memory backend fails-closed
- Debug endpoints (`/v1/debug/*`) are disabled

---

## Threat Model Summary

| Threat | Control |
|--------|---------|
| Cross-tenant data read via traversal | API-layer + BFS-layer + store-layer tenant checks |
| Cross-tenant cache read | Tenant_id in all cache key segments |
| Operator data exfiltration | Immutable audit log + session expiry + purpose enforcement |
| Consent bypass | `activation_eligible` flag checked by all consumers |
| Gremlin injection | `_escape_gremlin()` on all values; no raw query input |
| Filter language abuse | Operator allowlist (400 on unknown) + budget limits |
| Temporal replay bypass | Valid-time filtering on both edges and vertices in BFS |
| JWT secret leak | Startup validation; secrets from manager, not .env |
