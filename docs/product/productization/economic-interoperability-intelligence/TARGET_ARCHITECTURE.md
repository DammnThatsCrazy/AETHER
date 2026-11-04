---
title: Target Architecture — Economic & Interoperability Intelligence
slug: productization/economic-interoperability-intelligence/target-architecture
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/api/main.py, services/api/config/settings.py, services/api/actions/agent/deployment_routes.py, services/api/actions/agent_marketplace/catalog.py, services/api/actions/agent_marketplace/identity_binding.py, services/api/actions/agent_marketplace/authority.py, services/api/actions/agent_marketplace/graph_state_check.py, services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py, services/api/alembic/versions/20261011_agent_delegated_to_namespace.py]
canonical_owner: platform@aether
reviewed_source_commits:
  - commit: "3906b500a"
    reason: "Reviewed the 360 PR main.py diff: Social360 evidence and Workflow definition route mounts do not change the observation-only external agent economy paths described here."
  - commit: "482948261"
    reason: "Reviewed 482948261 (Codex findings on fleet hypotheses, bounded lineage reads and journey handoff): repositories/repos.py only gains the additive BaseRepository.insert_if_absent and replace_if_matches conditional-write primitives, deployment_routes.py reads lineage through a shared bounded reader that reports truncation, middleware.py lets site-bound publishable keys reach the two journey-handoff POSTs, and route_registry.yaml classifies the /sdk/journey-handoff prefix; nothing this doc describes changed behavior, so no body change was required."
source_hashes:
  "services/api/actions/agent/deployment_routes.py": "sha256:052adc35fd86925e255ea0f0fd2101ebdd3a9ea1b832f2b98702ecda335adc1f"
  "services/api/actions/agent_marketplace/authority.py": "sha256:b136984919ab302e7140815f5984f4cfad11494c3a591853af33d4c741a88b29"
  "services/api/actions/agent_marketplace/catalog.py": "sha256:b80db998c39a966ff19a25a64487b005b049bba96f6ca51cba18c15554cdce82"
  "services/api/actions/agent_marketplace/graph_state_check.py": "sha256:595617063afe604a7a5b1c421fa73916141a37b374a008606bb6dab460cd0983"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/config/settings.py": "sha256:fe581665da73af478c3da53600fb0fdd4994d801f408e56f6d2796fbd00748bf"
  "services/api/main.py": "sha256:fca84921a91cae1332efdd3da2218d211d3a960dd232470b9ea808536a3aa9e2"
---

# Target Architecture

Three observation-only domains wired through EXISTING platform systems —
no parallel infrastructure was introduced. (Post-merge note: the
independently merged observer-stack implementations — `services/api/value/stablecoins`
at `/v1/stablecoin` and the derivatives ingestion/accounting layer at
`/v1/derivatives` — coexist with these domains; this branch's derivatives
runtime is namespaced under `/v1/derivatives/runtime`.)


The external-agent economy slice extends the same observation-only foundation.
Tenant deployment source references acquire canonical identity only through
explicit tenant-admin, tenant-and-namespace-scoped bindings. Canonical
Delegation records are evaluated at the source-reported event time using
backend-owned status, endpoints, validity, and supported scope; action, resource,
and time remain source claims. A scope result does not prove an external action
occurred, and occurrence remains unverified without a server-owned execution
receipt. The bounded read-only graph state check compares supported graph links
to tenant source evidence, reports partial/non-snapshot coverage honestly, and
does not repair or certify the graph. Public marketplace observations remain
platform-scoped and separate from tenant deployment identity.

A fourth observation-only slice, card-linked payment rails, follows the
same wiring pattern: `main.py` mounts
`services/api/value/card_linked_payments/routes.py` under
`/v1/integrations/providers/payment-rails/card-linked` when
`AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` is on, and
`services/api/value/card_linked_payments/kyber_routes.py` under
`/v1/admin/kyber/payment-rails/card-linked` when either the master or
`KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED` flag is on. Its source of
truth is `docs/reference/source-of-truth/CARD_LINKED_PAYMENT_RAILS.md`.

```
provider evidence (RPC logs / venue snapshots / simulator fixtures)
        │ read-only adapters (honest ImplementationStatus)
        ▼
domain services (services/{stablecoin,derivatives,interop})
        │ canonical events (registry families, 110 events)
        ▼
silver projectors (registry-derived handles) ──► silver_*_facts
        │                                              │
        ▼                                              ▼
graph mutations (flag-gated, idempotent)        gold materialization
        │                                       (ClickHouse DDL, no training)
        ▼
Product 360 frames (`/v1/experience360/frames`) · Profile360 sub-resources ·
Noesis intents · OODA suggestions · alerts
        ▼
Aether tenant pages · Kyber operator ops pages (flag-gated, honest states)
```

## Invariants

- `execution_by_aether = false` at every layer: DB CHECK constraints,
  `Literal[False]` model fields, `check_no_execution` on write routes,
  read-only adapter credentials, conformance assertions.
- Fail-closed flags: every capability defaults OFF
  (`AETHER_STABLECOIN_*`, `AETHER_DERIVATIVES_*`, `AETHER_INTEROP_*`,
  `KYBER_*_OPS_ENABLED`); `Settings.__post_init__` enforces coherence
  (LayerZero requires the adapters flag).
- Tenant isolation: every tenant table keyed and filtered by
  `tenant_id`; public reference data (registries, topology) in the
  public scope only.
- Decimal-only canonical finance: NUMERIC(38,18) + typed repositories
  preserving `Decimal`; validators reject floats and exponent forms.
