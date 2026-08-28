---
title: Graph Projection Model
slug: productization/economic-interoperability-intelligence/graph-projection-model
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/graph.py
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - packages/shared/graph-contract.ts
canonical_owner: platform@aether
last_synced_commit: "15b8889"
---

# Graph Projection Model

8.12.0 adds 8 vertex types and 87 edge types; the per-domain alignment
docs (`STABLECOIN_GRAPH_ALIGNMENT`, `DERIVATIVES_GRAPH_ALIGNMENT`,
`INTEROP_GRAPH_ALIGNMENT`) carry the full lists. The traffic-intelligence
acquisition/attribution edges are included: `ARRIVED_THROUGH_SOURCE`,
`USED_PLACEMENT`, `ORIGINATED_FROM_LINK`, and
`ATTRIBUTED_TO_PLATFORM_EVIDENCE` are `EXCLUDED`-layer topology edges, while
`REFERRED_ENTITY` (AI/agent → entity) participates in the `A2H` layer. All
five are mapped in `_EDGE_LAYER_MAP` and projected by `SilverGraphProjector`
from touchpoint facts (tenant-scoped, replay-safe).

Cross-domain rules:

- High-cardinality facts (observations, orders, fills, positions,
  messages) are NEVER vertices — they stay silver facts.
- Actor edges participate in the four layers (H2H/H2A/A2H/A2A); domain
  topology edges are `EXCLUDED`. Every new edge is mapped in
  `_EDGE_LAYER_MAP`; `assert_contract_valid()` and the exhaustiveness
  test fail on unmapped edges.
- A2H edges exist in BOTH `packages/shared/graph-contract.ts` and the
  Python map — `tests/unit/test_graph_contract_parity.py` asserts set
  equality (the 7 derivatives A2H edges and interop `RELAYED_FOR` are
  covered).
- All mutations flow through `build_edge_properties` (tenant, actor,
  provenance, valid_from, source_event_id, idempotency key) and
  `persist_mutations`, gated per domain by `*_graph_enabled` flags.
- Import rollback and replay use conservative ownership-aware garbage collection.
  A vertex is removed only when the failed import is its canonical owner, the
  vertex has no ownership history from another import, and no active edge still
  references it. Pre-existing or shared vertices are retained.

Administrative rehearsal cleanup is separate from import rollback and is
tenant-scoped: `GraphClient.delete_tenant_data` removes projection vertices and
tenant-tagged edges for both `tenantId` and legacy `tenant_id`, including edges
to shared endpoints. It fails closed on a backend error and never removes
unscoped/system graph data.

## Tenant scoping on reads

The tenant a vertex or edge belongs to is resolved through
`shared/graph/graph.py::tenant_of`, which reads either spelling the graph
carries: vertex producers write camelCase `tenantId` (`SilverGraphProjector`)
while edge producers write snake_case `tenant_id` (`build_edge_properties`,
`revoke_edge`, `delete_vertex_if_orphaned`). `TENANT_PROPERTY` names the
canonical spelling for new writes and for the Neptune predicate; `tenant_of`
means existing rows in both spellings resolve without a backfill. An absent or
empty tenant property resolves to `None`, which callers must treat as "not this
tenant" rather than as a wildcard.

Per-tenant reads use `GraphClient.get_vertices_for_tenant(tenant_id, limit)`,
which puts the predicate **inside** the query — Neptune
`.has(TENANT_PROPERTY, t).limit(n)`, in-memory filter-then-slice — so the cap
bounds that tenant's rows. `get_all_vertices(limit)` remains for genuinely
global reads and applies its cap to the whole graph; using it to answer a
per-tenant question truncates silently, because the tenant's rows may sort past
the cap and never reach the filter. `scripts/validate_graph_scoped_reads.py` is
a shrink-only gate that fails CI when a module under `services/` calls the
global read.

The same resolution applies to `current_graph_digest`: `_canonical_props`
normalises the tenant key so a ledger replay that stored one spelling digests
equal to a live graph holding the other, rather than reporting a parity failure
between two representations of identical state.

The card-linked payment rail slice adds 5 vertex types (`CARD_PROGRAM`,
`CARD_ISSUER`, `PAYMENT_NETWORK`, `CARD_LINKED_FLOW`, `CARD_BENCHMARK`)
and 9 edge types (`CAME_FROM`, `PARTICIPATED_IN`, `USED_PROVIDER`,
`FUNDED`, `OCCURRED_ON`, `USED_ASSET`, `RUNS_ON`, `FOLLOWED_BY`,
`INITIATED_OR_INFLUENCED`), every one mapped to
`RelationshipLayer.EXCLUDED` — card-linked behavior is intentionally
never usable as deterministic identity-merge evidence. PaymentScan
benchmark rows are never projected to the graph at all
(`services/card_linked_payments/graph_projector.py`).

The semantic-intelligence relationship Gold follows the same projection
rules: `SEMANTIC_RELATES_TO` (directed entity → entity, a derived analytics
overlay) is mapped to `RelationshipLayer.EXCLUDED` in `_EDGE_LAYER_MAP` and is
projected by the semantic graph projector
(`services/semantic_intelligence/graph_projector.py`) from
`gold_relationship_semantic_state` through the canonical `GraphMutationGateway`
— governed (edge intent, ledger-aware in shadow/enforce mode), idempotent, and
tenant-scoped, gated on `SEMANTIC_GRAPH_PROJECTOR_ENABLED` (default OFF). See
[`docs/INTELLIGENCE-GRAPH.md`](../../INTELLIGENCE-GRAPH.md#semantic-relationship-overlay).
