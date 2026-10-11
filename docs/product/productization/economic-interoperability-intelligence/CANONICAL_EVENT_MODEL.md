---
title: Canonical Event Model (cross-domain)
slug: productization/economic-interoperability-intelligence/canonical-event-model
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [packages/shared/contracts/event-registry.json, packages/shared/graph-contract.ts, services/api/actions/agent/deployment_routes.py, services/api/actions/agent_marketplace/authority.py, services/api/actions/agent_marketplace/identity_binding.py, services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py, services/api/alembic/versions/20261011_agent_delegated_to_namespace.py]
canonical_owner: platform@aether
source_hashes:
  "packages/shared/contracts/event-registry.json": "sha256:d7507199ec0837a4c77f7fe4d54d2590f4ad49d98b10c35fc3bbb9bddd37c64a"
---

# Canonical Event Model

416 events across 25 families in
`packages/shared/contracts/event-registry.json` (single source of truth;
`scripts/generate_contracts.py` emits TS/Python/doc artifacts). The
economic-interoperability families:

| Family | Events | Purpose | Silver projection |
|---|---|---|---|
| `stablecoin` | 30 | `economic_observability` | `stablecoin_facts` |
| `derivatives` | 52 | `financial_activity` | `derivatives_facts` |
| `interop` | 39 | `cross_chain_observability` | `interop_facts` |

Rules:

- `introducedVersion: "0.1.0-alpha.0"` on every new event.
- `privacyClass`: `financial` for facts, `sensitive_financial` for
  positions/P&L, `governance` for registry/ops events.
- `retentionClass`: `financial_7y` for facts; standard classes for ops.
- `graphProjection` only on material events.
- Projector routing is registry-derived
  (`services/api/ingestion/silver/projectors/registry_handles.py`) — adding an event
  to a family automatically routes it; a cross-cutting test asserts
  every declared `silverProjection` token maps to a registered projector.
- Metering uses ONLY the 8 canonical meter names validated by
  `scripts/validate_meter_names.py` against `MeteringEventType`.

External-agent task, outcome and delegation events may carry payment-intent,
settlement-event, delegation, deployment-agent, and delegated-to-agent IDs as
`SOURCE_REFERENCE` fields. These are caller-reported references, not economic
facts: payment amount, currency and status come only from server-authoritative
x402 records. A deployment agent reference resolves to a canonical Agent only
through an explicit tenant-admin binding scoped by tenant, source namespace,
and source reference. Delegated targets likewise require the event's explicit
`delegatedToNamespace`; the resolver does not fall back to the actor's
namespace.

The registry maps `agent_delegated_task` to
`REFERENCES_DELEGATION_RECORD`, an `EXCLUDED` graph reference layer. The exact
same-tenant delegation reference is correlation. Separately, backend authority
compares the resolved parties, reported action/resource, reported event time,
and any authoritative economic amount against the canonical delegation's
parties, scope, status, and effective/revoked times. It reports
`within_scope`, `out_of_scope`, or `indeterminate`; action, resource, and event
time remain source-asserted. This grant-scope result does not verify that the
external action occurred. Without a server-owned execution receipt, occurrence
remains `source_reported` and unverified.
