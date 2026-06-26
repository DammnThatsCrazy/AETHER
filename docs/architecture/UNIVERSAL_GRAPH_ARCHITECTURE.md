---
title: Universal Intelligence Graph Architecture
slug: architecture/universal-graph-architecture
section: architecture
visibility: internal
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.10.0"
canonical_owner: graph@aether
---
# Universal Intelligence Graph Architecture

## Overview

The Universal Intelligence Graph (v8.10.0) is a multi-tenant, bitemporal, multi-layer graph serving two distinct hierarchies:

- **Aether hierarchy** — tenant graph: campaign → cluster → entity → economic flow → outcome
- **Kyber hierarchy** — platform graph: tenant operational envelope → SDK health → connector health → graph metrics

These hierarchies share the same `GraphClient` and `GraphTraversalEngine` but operate under different authorization models.

---

## System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Aether Frontend                         │
│  /graph (GraphCanvas + Inspector + Overlays + Replay)       │
│  /clusters/:id (Cluster360)                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────┐
│              Universal Query API (/v1/graph/*)              │
│  POST /query      POST /facets    POST /compare             │
│  POST /replay     POST /explain   POST /export              │
│  GET  /capabilities               GET /export/{job_id}      │
│  POST /traverse   POST /path      POST /temporal            │
│  POST /overlay    POST /filter    GET  /health              │
└────────────┬──────────────────────────┬─────────────────────┘
             │                          │
┌────────────▼───────────┐  ┌──────────▼────────────────────┐
│  GraphTraversalEngine   │  │  Boolean Filter Engine        │
│  BFS + temporal BFS     │  │  AND/OR/NOT + all 15 ops      │
│  A2A cycle detection    │  │  cursor pagination             │
│  tenant_id isolation    │  │  query budget enforcement     │
└────────────┬───────────┘  └──────────┬────────────────────┘
             │                          │
┌────────────▼──────────────────────────▼────────────────────┐
│                       GraphClient                           │
│  In-memory (local) ↔ Neptune/gremlinpython (staging/prod)  │
│  Tenant-scoped reads and writes                             │
│  Bitemporal vertex/edge properties (valid_from/valid_to)   │
└─────────────────────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────┐
│                   Cache Layer (Redis)                      │
│  Keys: aether:graph:<type>:<tenant_id>:<query_hash>:...   │
│  SHORT TTL for real-time; MEDIUM TTL for temporal replay   │
└────────────────────────────────────────────────────────────┘
```

---

## Kyber Operator Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Kyber Frontend                      │
│  /noesis/fleet (Fleet Graph + Tenant Portfolio Table)   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│          Kyber Operator Service (/v1/kyber/*)           │
│  POST /operator/tenant-entry  (enter tenant, audit log) │
│  DELETE /operator/tenant-entry  (exit, revoke session)  │
│  GET  /tenants/{id}/operational-envelope                │
└──────────────────────────┬──────────────────────────────┘
                           │  operator_tenant_scope header
┌──────────────────────────▼──────────────────────────────┐
│     Universal Query API (/v1/graph/* operator mode)     │
│  Validates: kyber:operator permission + active session  │
│  Creates: immutable audit record per query              │
└─────────────────────────────────────────────────────────┘
```

---

## Data Flow — Entity Lifecycle

```
1. SDK event  →  Unified Pipeline  →  graph_mutations.py
2. graph_mutations.py writes Vertex with:
     valid_from = event_time
     recorded_at = ingestion_time
     lifecycle_state = "provisional"
     observation_class = "observed"
     tenantId = request.tenant_id
3. Identity resolver: MEMBER_OF_CLUSTER edges written
4. Campaign attributor: ACQUIRED_VIA edges written
5. Fraud scorer: MEMBER_OF_FRAUD_NETWORK edges written (if triggered)
6. At DSR withdrawal:
     vertex.consent_state = "withdrawn"
     vertex.activation_eligible = false
     vertex.lifecycle_state = "revoked"
```

---

## Bitemporal Model

Every vertex and edge has four time dimensions:

| Dimension | Field | Meaning |
|-----------|-------|---------|
| Valid-time start | `valid_from` | When the fact became true |
| Valid-time end | `valid_to` | When the fact stopped being true (null = open) |
| System-time start | `recorded_at` | When Aether wrote this version |
| System-time end | `superseded_at` | When a newer version replaced this (null = current) |

Point-in-time query: `valid_from ≤ as_of AND (valid_to IS NULL OR valid_to > as_of)`

Historical compare: run point-in-time query at `as_of` and `compare_to`, diff the result sets.

---

## Semantic Zoom

The graph API supports two zoom modes without requiring the client to render millions of raw nodes:

| Mode | Request | Response |
|------|---------|----------|
| Macro (zoom out) | `depth=0, include_clusters=true` | Returns ClusterNode aggregates (member_count, risk_score, etc.) |
| Expand (zoom in) | `anchors=[cluster_id], depth=1` | Returns cluster members as individual nodes |

The backend decides the appropriate projection; the frontend sends the zoom level and receives the right data.

---

## Query Authorization Model

```
All /v1/graph/* routes:
  1. Authenticate JWT → extract tenant_id
  2. _require_read(tenant_id, request.tenant_id)
     → 403 if mismatch
     → increment graph_tenant_isolation_violation_total counter if mismatch
  3. All graph reads pass tenant_id to GraphClient (Neptune/in-memory)
  4. Neptune queries include g.V().has('tenantId', tenant_id) filter

Kyber operator routes:
  1. Authenticate JWT → verify kyber:operator role
  2. Check active TenantEntrySession for (operator_id, target_tenant_id)
  3. If session exists: allow, add to audit log
  4. If no session: 403 — must call POST /v1/kyber/operator/tenant-entry first
```

---

## Feature Flag Control

All graph layers and features are controlled by feature flags, defaulting to `false` in staging:

| Flag | Controls |
|------|---------|
| `IG_AGENT_LAYER` | H2A, A2H, A2A relationship layer |
| `IG_COMMERCE_LAYER` | PAYS_FOR, TRANSFERS_TO, economic edges |
| `IG_ONCHAIN_LAYER` | On-chain wallet/protocol edges |
| `IG_X402_LAYER` | x402 payment channel edges |
| `IG_EXPORT_JOBS` | Async export via Celery |
| `IG_SEMANTIC_ZOOM` | Server-backed macro→micro zoom |
| `IG_FLEET_GRAPH` | Kyber fleet graph + operator tenant entry |

In `AETHER_ENV=local`, the in-memory backend is used and all flags behave as enabled unless explicitly overridden.

---

## Rollback Plan

The Universal Query API routes (`/v1/graph/query`, `/v1/graph/facets`, etc.) are additive — the legacy routes (`/v1/graph/traverse`, `/v1/graph/filter`, etc.) remain unchanged. To roll back:

1. Disable `IG_SEMANTIC_ZOOM` and `IG_FLEET_GRAPH` feature flags
2. Route frontend to legacy `/v1/graph/traverse` endpoints
3. No data migration required — routes are stateless query adapters

---

## SLO Targets

| Operation | P50 | P95 |
|-----------|-----|-----|
| Graph query (depth 2, 100 nodes) | <200ms | <500ms |
| BFS traversal (depth 3, 200 nodes) | <300ms | <800ms |
| Cluster360 overview | <200ms | <500ms |
| Replay (historical) | <500ms | <1s |
| Facet computation | <300ms | <600ms |
