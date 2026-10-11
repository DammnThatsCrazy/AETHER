---
title: Graph Projection Model
slug: productization/economic-interoperability-intelligence/graph-projection-model
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/api/shared/graph/graph.py, services/api/shared/graph/relationship_layers.py, packages/shared/graph-contract.ts, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/ingestion/silver/projectors/silver_graph_projector.py, services/api/actions/agent_marketplace/lineage.py, services/api/actions/agent_marketplace/projection.py]
canonical_owner: platform@aether
source_hashes:
  "packages/shared/graph-contract.ts": "sha256:1d8abee6ae4996435a52ec89e4631fb24a1db9a73009387f5c7c45ce9060a2ab"
  "services/api/actions/agent_marketplace/lineage.py": "sha256:df30e2c21f5a763e3a778d32824d3d29e864ea62f04903174d65b96fe9471ba0"
  "services/api/actions/agent_marketplace/projection.py": "sha256:174c8ab0c749ef7aa1611008aa9b3c1a456f13cb828d52c9937d49061e877e2d"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:63f702d411c6e2f11349abb68f70f67bfc0cd22e5aff7d150614a43f3821486c"
  "services/api/ingestion/silver/projectors/silver_graph_projector.py": "sha256:5e1772ea0b72e26131503b6b98716a852d608a6704bf64579d24acb0ff510488"
  "services/api/shared/graph/graph.py": "sha256:5ebd5c00091501ed11bac0bd49baf741261177a93ae1e99e5e9d6b0ec5054a06"
  "services/api/shared/graph/relationship_layers.py": "sha256:0d53e3c12efef77b060beb2b53b7e02f5086d4ee93ecea098b1d8318a4eb8af6"
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
`.has(TENANT_PROPERTY, t).limit(n)`, Postgres `WHERE tenant_id = $1 ... LIMIT`
(the tenant is denormalised to an indexed column via `tenant_of`), in-memory
filter-then-slice — so the cap bounds that tenant's rows. `get_all_vertices(limit)` remains for genuinely
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
(`services/api/value/card_linked_payments/graph_projector.py`).

The semantic-intelligence relationship Gold follows the same projection
rules: `SEMANTIC_RELATES_TO` (directed entity → entity, a derived analytics
overlay) is mapped to `RelationshipLayer.EXCLUDED` in `_EDGE_LAYER_MAP` and is
projected by the semantic graph projector
(`services/api/intelligence/semantic_intelligence/graph_projector.py`) from
`gold_relationship_semantic_state` through the canonical `GraphMutationGateway`
— governed (edge intent, ledger-aware in shadow/enforce mode), idempotent, and
tenant-scoped, gated on `SEMANTIC_GRAPH_PROJECTOR_ENABLED` (default OFF). See
[`docs/architecture/INTELLIGENCE-GRAPH.md`](../../../architecture/INTELLIGENCE-GRAPH.md#semantic-relationship-overlay).

## External agent execution lineage

Marketplace listings, tenant-declared deployments, and observed execution are
separate graph evidence. A deployment's marketplace origin remains a
tenant-declared reference; its agent ID is not linked to a canonical Agent
until identity authority resolves it. Runs are grouped using the validated
deployment plus source run ID, or trace ID when no run ID is supplied.

The graph links each run to the deployment and source-scoped task/outcome
records. Source-reported actions, tool calls, triggers, policy decisions, and
delegation references are retained as timestamped `ActionRecord` and
`DecisionRecord` nodes. The complete source event stays in Silver. A run
explanation is an ordered view of those observations and their coverage gaps,
not an inference about hidden reasoning or a verification of reported policy.

Graph writes use a store-backed outbox and the canonical `GraphMutationGateway`.
Kyber can reconcile expected mutations from deployment/Silver sources, enqueue
missing work, and replay dead-lettered or stale processing rows. This proves
source-to-outbox coverage only; it does not detect graph-side drift. The
projection is feature-flagged and local in-memory store mode is not durable
across processes.
