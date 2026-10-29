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
reviewed_source_commits:
  - commit: "482948261"
    reason: "Reviewed 482948261 (Codex findings on fleet hypotheses, bounded lineage reads and journey handoff): repositories/repos.py only gains the additive BaseRepository.insert_if_absent and replace_if_matches conditional-write primitives, deployment_routes.py reads lineage through a shared bounded reader that reports truncation, middleware.py lets site-bound publishable keys reach the two journey-handoff POSTs, and route_registry.yaml classifies the /sdk/journey-handoff prefix; nothing this doc describes changed behavior, so no body change was required."
source_hashes:
  "packages/shared/contracts/event-registry.json": "sha256:3d839b394ff0ee3a40679f92a9c38f2e321ab7785663d1a8ef047279d8b757f2"
  "packages/shared/graph-contract.ts": "sha256:662e10a7d4737ba53c673173105344ccf1720ac7e62497d36346734898575087"
  "services/api/actions/agent/deployment_routes.py": "sha256:46ace5ea27e1c0a95bb62b7d63cd9c53f383f0ae759e30c795914f41e5e2a8b4"
  "services/api/actions/agent_marketplace/authority.py": "sha256:b136984919ab302e7140815f5984f4cfad11494c3a591853af33d4c741a88b29"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
---

# Canonical Event Model

453 events across 25 families in
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
