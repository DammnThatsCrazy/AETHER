---
title: Graph Projection Model
slug: productization/economic-interoperability-intelligence/graph-projection-model
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/api/shared/graph/graph.py, services/api/shared/graph/relationship_layers.py, packages/shared/graph-contract.ts, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/ingestion/silver/projectors/silver_graph_projector.py, services/api/actions/agent_marketplace/authority.py, services/api/actions/agent_marketplace/identity_binding.py, services/api/actions/agent_marketplace/graph_state_check.py, services/api/actions/agent/deployment_routes.py, services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py, services/api/alembic/versions/20261011_agent_delegated_to_namespace.py, packages/sdk/server/src/agent-telemetry.ts, services/api/actions/agent_marketplace/catalog.py, services/api/actions/agent_marketplace/lineage.py, services/api/actions/agent_marketplace/projection.py, services/api/repositories/repos.py, services/api/value/x402/economic_mutations.py, services/api/value/x402/lifecycle_mapper.py, services/api/value/x402/provenance.py, services/api/workers/profile360_workers/workers.py]
canonical_owner: platform@aether
source_hashes:
  "packages/sdk/server/src/agent-telemetry.ts": "sha256:95db783d969918011e29a3aeb96e837a559f547aec4c2efcee1679188b360f0b"
  "packages/shared/graph-contract.ts": "sha256:662e10a7d4737ba53c673173105344ccf1720ac7e62497d36346734898575087"
  "services/api/actions/agent/deployment_routes.py": "sha256:f0cb4ff2fb6a2d504e740a8e7d18b16cd99716937beb310cc81d6a118cd69e5d"
  "services/api/actions/agent_marketplace/authority.py": "sha256:696f7db917fe642c7d39195660d9956eeea4971f4e135eb1fc5826807f7ac506"
  "services/api/actions/agent_marketplace/catalog.py": "sha256:b80db998c39a966ff19a25a64487b005b049bba96f6ca51cba18c15554cdce82"
  "services/api/actions/agent_marketplace/graph_state_check.py": "sha256:595617063afe604a7a5b1c421fa73916141a37b374a008606bb6dab460cd0983"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/actions/agent_marketplace/lineage.py": "sha256:bfe247f42c3360f30b3f4fa92b1f39e95f654be0862303d6f74b9fb2363e6566"
  "services/api/actions/agent_marketplace/projection.py": "sha256:5354b080f686377d2b74124bb6b56b8522cb2cb51ea5e5a7164ffdf81fc89e2d"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:8871db780d887fbd8857b2bc3745f630798a3b872dd00e2bfe75ebf2489c3ab7"
  "services/api/ingestion/silver/projectors/silver_graph_projector.py": "sha256:9e5324ad309694cebfbbc1e22f0ae7ae8734c5167791de9190b89bbf1ca0932d"
  "services/api/repositories/repos.py": "sha256:9d45ac53e8e307d497da4e28d552ca6ef909c0b278dfe32ec825281aab6ec58e"
  "services/api/shared/graph/graph.py": "sha256:07c5a70eb15c7924fad58de63eba5d3d984b6eac21c328cd3072de0f77ee14fd"
  "services/api/shared/graph/relationship_layers.py": "sha256:592a96efb98c32148e7f6911beef348f49dbf2b6db8430e4d403969d62430ba6"
  "services/api/value/x402/economic_mutations.py": "sha256:bdd180a936e048840636f221fdee3b142c0babab5d8e2bcc59b4a51983198f51"
  "services/api/value/x402/lifecycle_mapper.py": "sha256:77066a174bdf8e3feed32e1a7b81feb321983975b5cd9e6116a4fa5a588c473e"
  "services/api/value/x402/provenance.py": "sha256:235c29fc3b743ea75c15902f8e9a2cb635c95d2b04b7aa82c28c96ae65769b18"
  "services/api/workers/profile360_workers/workers.py": "sha256:0c79f5ee2cc03eb0ae92d8690a8622b8ebaea245dc047c7643107fe909d7170a"
---

# Graph Projection Model

8.12.0 introduced 8 vertex types and 87 edge types; the current contract has
89 edge types after two external-agent evidence links were added. The per-domain alignment
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
separate graph evidence. A tenant administrator can explicitly bind a
deployment's `(tenant_id, source_namespace, source_agent_ref)` to an existing
canonical Agent in that tenant. This durable binding is audited and separate
from automatic identity resolution; absent, ambiguous, stale, or cross-tenant
bindings fail closed. Runs are grouped using the validated deployment plus
source run ID, or trace ID when no run ID is supplied.

The graph links each run to the deployment and source-scoped task/outcome
records. Source-reported actions, tool calls, triggers, policy decisions, and
delegation references are retained as timestamped `ActionRecord` and
`DecisionRecord` nodes. The complete source event stays in Silver. A run
explanation is an ordered view of those observations and their coverage gaps,
not an inference about hidden reasoning or a verification of reported policy.

An `ActionRecord` links to `PaymentIntent` or `SettlementEvent` only when the
caller-supplied record reference exactly matches a same-tenant server-owned
x402 row and that row's agent reference matches the tenant registry deployment
reference. These economic links remain correlation evidence, not causality or
proof that a source action occurred. A delegation ID can link an action to an
exact same-tenant `Delegation` record. The backend resolves the actor and target
through explicit bindings; target resolution requires the source-declared
`delegated_to_namespace` and never falls back to the actor namespace. It then
evaluates canonical delegation
endpoints, status, effective/revocation window, action, resource, and supported
amount limit at source event time. The result is `within_scope`,
`out_of_scope`, or `indeterminate`; event time, action, and resource remain
source-reported inputs. A matching grant is not proof of execution. Without a
server-owned execution receipt, occurrence remains `source_reported` and
unverified. Canonical `DELEGATES`, `GRANTED_BY` and `GRANTED_TO` links remain
projected from the delegation authority record, independently of run telemetry.

Graph writes use a store-backed outbox and the canonical `GraphMutationGateway`.
Kyber reconcile/repair can restore source-to-outbox coverage and replay dead
letters; that path is distinct from the read-only bounded graph state check.
`GET /v1/admin/kyber/agent-telemetry/graph-projection/state-check` compares
supported tenant source references against graph state and reports missing,
extra, mismatched, unresolved, or unauthorized findings. It can return partial
coverage and is best-effort/non-snapshot; it does not mutate the graph or
certify all tenant graph state. The projection remains feature-flagged and
local in-memory store mode is not durable across processes.

Public catalog state transitions are retained as append-only observations so a
later poll cannot erase a version whose outbox enqueue failed. Platform
reconciliation and repair accept a source cursor to page those observations;
reports expose source and outbox scan truncation so a bounded partial scan is
not read as complete coverage. Public catalog graph records stay in the
`platform` scope and are surfaced in Agent 360's separate catalog panel; they
are not included by tenant graph queries.
