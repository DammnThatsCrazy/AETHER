---
title: Graph of Graphs Data Use
slug: architecture/graph-of-graphs-data-use
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: platform@aether
source_files:
  - Backend Architecture/aether-backend/services/integrations/data_rights/models.py
last_synced_commit: "pending"
estimated_read_minutes: 5
---

# Graph of Graphs Data Use

> Aether operates two distinct graph layers: the per-tenant graph (private to
> each tenant) and the Olympus graph (platform-wide, shared baseline). Data
> moves between these two layers only under explicit DataRightsGrant authorization.
> This document defines the transition rules.

## Why two graph layers?

Tenants contribute graph edges about their own users, wallets, and events.
Those edges reflect the tenant's proprietary intelligence and must not leak
across tenant boundaries.

The Olympus graph captures signals that are beneficial across all tenants: shared
wallet clusters, known CEX addresses, protocol activity, and prediction market
correlations. These signals improve everyone's models without exposing any
individual tenant's data.

The challenge is that some tenant-observed edges are genuinely useful in the
Olympus graph — but only with the tenant's explicit consent.

---

## Default isolation

By default, all tenant graph edges are isolated to the tenant's graph partition:

- Vertices are prefixed with `tenant:{tenant_id}:`.
- Edges created by tenant-owned connectors carry `GraphWritePolicy = TENANT_GRAPH_ONLY`.
- Olympus graph traversal queries do not cross into tenant partitions.
- Tenant queries do not traverse Olympus-baseline edges unless the tenant opts
  in to consuming Olympus graph signals.

---

## Transition rules: tenant graph to Olympus graph

A tenant graph edge may enter the Olympus graph only when all of the following
hold:

| Condition | Check |
|---|---|
| Active DataRightsGrant exists | `grant.olympus_baseline_allowed = true` |
| Grant covers the edge's source connector | `grant.source_slug` matches connector |
| Edge carries a valid `lineage_id` | Non-null `lineage_event_ids[]` |
| PII fields are stripped | No `email`, `phone`, `name` on cross-graph edges |
| Tenant has not opted out | `tenant.olympus_contribution = true` |

If any condition fails, the edge remains in the tenant partition and does not
enter the Olympus graph.

---

## Safe transition table

The following table shows the permitted data use for different edge origins.

| Edge origin | Tenant graph | Olympus graph | Training |
|---|---|---|---|
| Olympus provider (Dune, DeFiLlama) | Yes | Yes | Requires grant |
| Tenant BYOD connector | Yes | Only with grant | Opt-in only |
| BYOK-routed provider | Yes (ephemeral) | Never | Never |
| Identity bridge (ENS, Farcaster) | Yes | Yes | Requires grant |
| Action notifier | Never | Never | Never |

---

## Cross-graph edge schema requirements

When a tenant graph edge is promoted to the Olympus graph, the edge is
re-written with a new set of properties:

| Property | Value |
|---|---|
| `source_partition` | `tenant:{tenant_id}` |
| `olympus_lineage_id` | New lineage ID for the cross-graph write |
| `original_lineage_id` | Tenant-side lineage ID (audit trail) |
| `grant_id` | DataRightsGrant that authorized the promotion |
| `promoted_at` | Timestamp of the promotion |
| `pii_stripped` | `true` (validation gate) |

The original tenant-side edge is preserved unchanged. Promotion is additive.

---

## Cross-tenant graph queries

Olympus graph traversal is available to all tenants as a read-only service.
Tenants can query the Olympus graph to enrich their local signals:

- "Is this wallet associated with a known MEV bot?"
- "Is this protocol flagged for anomalous TVL behavior?"
- "What is the social graph distance between these two Farcaster identities?"

These queries are read-only. A tenant's query result is scoped to their
authorized intelligence tier. Premium tiers receive deeper traversal (more hops)
and richer edge properties.

---

## Revocation in the cross-graph context

When a DataRightsGrant is revoked for a tenant:

1. Edges that were promoted to the Olympus graph under that grant are flagged
   `LINEAGE_TAINTED`.
2. Olympus graph queries filter out tainted edges by default.
3. A background job eventually removes tainted edges from the Olympus graph.
4. The original tenant-side edges are unaffected (tenant isolation is
   maintained).

The revocation timeline for Olympus graph edges may be longer than for lake
records due to graph traversal caching. Clients should check edge
`lineage_status` when freshness is critical.

---

## Related docs

- `DATA_RIGHTS_LEDGER.md` — Grant model that authorizes cross-graph transitions.
- `ENRICHMENT_LINEAGE.md` — Lineage records attached to graph edges.
- `CONNECTOR_LAKE_POLICY.md` — GraphWritePolicy by connector class.
- `CONNECTOR_TAXONOMY.md` — ConnectorClass definitions.
