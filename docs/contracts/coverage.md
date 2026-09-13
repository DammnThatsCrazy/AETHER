---
title: Contract Coverage
slug: contracts/coverage
section: reference
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# Contract Coverage

This document audits which domain surfaces in Aether are backed by a
registered contract (schema or registry under `contracts/delivery/` or
`packages/shared/contracts/`) and which are not. It complements
[VERSION_POLICY.md](../../contracts/VERSION_POLICY.md) and the
[compatibility matrix](./compatibility-matrix.md).

## Domain surfaces with contract coverage

| Domain surface | Contract | Notes |
|---|---|---|
| Analytics events | `packages/shared/contracts/event-registry.json` | Field-trust metadata, semantic levels, SDK boundary declared in-schema; twin-checked against TS/Python/mobile |
| Consent purposes | `packages/shared/contracts/consent-registry.json` | Cross-checked against event registry's `consent_purpose` refs by `scripts/validate_contracts.py` |
| Integration/connector consent | `packages/shared/contracts/integration-consent-registry.json` | Separate receipt/processing-decision versioning from the core consent registry |
| Graph mutations | `packages/shared/contracts/graph-mutation-registry.json` | Mutation types, actor kinds, causality classes, explanation types |
| Intelligence projections | `packages/shared/contracts/intelligence-projection-registry.json` | Validated by `scripts/validate_intelligence_projections.py`; legacy bindings must resolve to real routes/surfaces/services |
| Spine composition kernel | `packages/shared/contracts/spine-registry.json` | ADR-011; validated by `scripts/validate_spine_registry.py` |
| Relationship predicates | `packages/shared/contracts/relationship-predicate-registry.json` | Parity-tested against `packages/shared/relationship-predicate-registry.ts` |
| Relationship motifs | `packages/shared/contracts/relationship-motif-registry.json` | References predicate families; parity-tested |
| Relationship fidelity vectors | `packages/shared/contracts/relationship-fidelity-vector.schema.json` | JSON Schema (not a vocabulary registry) |
| Observation envelope (Envelope B) | `packages/shared/contracts/observation-envelope-registry.json` | Three-way parity: registry, Python runtime model, TS twin |
| Rights / IRRL authority | `packages/shared/contracts/rights-vocabulary.json` | Tri-surface: JSON vocabulary, Python enum, TS const array; no parallel registries allowed |
| Readiness vocabulary | `packages/shared/contracts/readiness-vocabulary.json` | Release-plan and claim-dimension tokens |
| Metrics | `packages/shared/contracts/metric-registry.json` | Generated into `docs/_generated/metric-registry-table.md` |
| Outcome types | `packages/shared/contracts/outcome-type-registry.json` | Domain-scoped outcome vocabulary |
| Interaction vocabulary | `packages/shared/contracts/interaction-vocabulary.json` | Interaction types, actor kinds, evidence basis |
| Signal use | `packages/shared/contracts/signal-use-matrix.json` | Signal-to-use mapping |
| Traffic source | `packages/shared/contracts/traffic-source-registry.json` | UTM/click-id/entry-method vocabulary |
| Comparison / benchmarking | `packages/shared/contracts/comparison-registry.json` | Comparison modes, alignment outcomes, materiality |
| Context capsules | `packages/shared/contracts/context-capsule-registry.json` | Location semantics, precision, retention classes |
| Location | `packages/shared/contracts/location-registry.json` | Location roles, region types, coordinate systems |
| Filter fields | `packages/shared/contracts/filter-field-registry.json` | Field categories, data types, sensitivities |
| Surface capabilities | `packages/shared/contracts/surface-capability-registry.json` | Views, filter dispositions, temporal modes |
| Lenses | `packages/shared/contracts/lens-registry.json` | Lens kinds and definitions |
| Projector ownership | `packages/shared/contracts/projector-ownership-registry.json` | Which projector owns which projection |
| Task profiles | `packages/shared/contracts/task-profile-registry.json` | Model routing profiles, guardrail kinds |
| Model registry | `packages/shared/contracts/model-registry.json` | Providers, model capabilities, aliases, thinking modes |
| Social provider capabilities | `packages/shared/contracts/social-provider-capability-vocabulary.json` | Capability grammar and lifecycle states |
| Social silver facts | `packages/shared/contracts/social-silver-facts.schema.json` | JSON Schema for the silver-tier social fact shape |
| Temporal policy | `packages/shared/contracts/temporal-policy-registry.json` | Enforcement modes, reason codes, family bounds |
| Kyber feature surfaces | `packages/shared/contracts/kyber-feature-surface-manifest.json` | Structural manifest, not cross-checked against a TS/Python twin |
| Evidence manifest | `packages/shared/contracts/evidence-manifest.schema.json` | JSON Schema for release-evidence content |
| Incentive context | `packages/shared/contracts/incentive-context.schema.json` | JSON Schema |
| Release candidates | `contracts/delivery/release-candidate.schema.json` | Immutable release metadata; produced by `scripts/artifact_builder.py` |
| Staging orchestration | `contracts/delivery/staging-orchestration-state.schema.json`, `staging-lifecycle-result.schema.json` | Fail-closed staging lifecycle |
| Migration evidence | `contracts/delivery/migration-evidence.schema.json` | Migration rehearsal evidence |
| Environment resolution | `contracts/delivery/environment-resolution.schema.json`, `environment-capability-snapshot.schema.json` | Canonical profile vs. observed capability |
| Effective IAM | `contracts/delivery/effective-iam-comparison.schema.json`, `effective-iam-evidence.schema.json` | IAM drift comparison |
| Terraform reconciliation | `contracts/delivery/terraform-reconciliation.schema.json`, `terraform-remote-inventory.schema.json` | Plan-vs-remote reconciliation |
| Deployment / impact graph | `contracts/delivery/deployment-impact.schema.json`, `impact-graph-index.schema.json` | Also registered in `config/impact_graph.json` |
| Change plans | `contracts/delivery/change-plan.schema.json` | Produced by `scripts/change_plan.py` |
| Failure envelopes | `contracts/delivery/failure-envelope.schema.json` | Shared failure shape across delivery tooling |
| Hosted adapters | `contracts/delivery/hosted-adapter-request.schema.json`, `hosted-adapter-result.schema.json`, `profile-delivery-operation.schema.json` | Credential-safe hosted delivery |
| Release evidence bundle | `contracts/delivery/release-evidence-bundle.schema.json` | Wraps `evidence-manifest.schema.json` content for delivery |
| Artifact closure | `contracts/delivery/artifact-closure.schema.json` | Component/lockfile closure for a release candidate |
| Telemetry events | `contracts/delivery/telemetry-event.schema.json` | Delivery-pipeline telemetry, distinct from `metric-registry.json` |

## Domain surfaces WITHOUT a registered contract (gaps)

These surfaces are real, load-bearing parts of the platform but are not
backed by a `.schema.json` or registry `.json` in either contract directory.
They are governed only by code review, tests, or narrative docs:

- **Jobs platform** (`Backend Architecture/**/services/jobs/**`) — governed by
  `docs/source-of-truth/JOBS_PLATFORM.md` and tests only; no schema.
- **Tenant import engine** (`services/imports/**`) — has a TS/Python contract
  twin (`packages/shared/imports.ts` ↔ `services/imports/contracts.py`) but no
  registered JSON Schema/registry file under either contracts directory.
- **Data exchange plane** (`services/data_exchange/**`, `services/reports/**`)
  — has a TS/Python twin (`packages/shared/data-exchange.ts`) but no schema
  file in `contracts/`.
- **Reconciled control plane / managed integrations**
  (`services/managed_integrations/**`, `services/security/**`) — TS/Python
  twins (`packages/shared/managed-integrations.ts`,
  `packages/shared/security-governance.ts`) exist; no JSON Schema.
- **Computation substrate** (`services/computation/**`) — governed by
  `config/computation_inventory.yaml`, not a `contracts/` schema.
- **Universal asset registry** (`services/assets/**`) — governed by
  `docs/BACKEND-API.md` and route tests; no schema file.
- **Event-time valuation** (`services/valuation/**`) — governed by narrative
  invariants in `docs/source-of-truth/**`; no schema file.
- **Ingress adapter registry / universal ingestion gateway**
  (`services/ingestion/adapters/**`, `gateway.py`) — governed by code +
  `tests/unit/observation`; consumes the Envelope-B registry but is not
  itself schema-defined.
- **Ingestion replay + normalization spine** (`services/ingestion/replay.py`,
  `spine.py`) — feature-flag-gated behavior with test coverage; no schema.
- **Backend HTTP routes generally** (`Backend Architecture/**/routes/**`) —
  covered by `docs/BACKEND-API.md` (generated) and route tests, not by a
  request/response JSON Schema per endpoint.
- **Deployment profiles / Terraform topology**
  (`config/deployment_profiles.yaml`, `config/terraform_resource_contracts.yaml`)
  — YAML-based contracts validated by dedicated Python checkers
  (`scripts/release/check_terraform_plan_policy.py`,
  `scripts/release/check_cost_model.py`), not JSON Schema under `contracts/`.

## Coverage policy

A domain surface does not require a `contracts/` schema to be considered
"governed" — many of the gaps above have an equivalent enforcement mechanism
(a TS/Python contract twin plus a parity test, a YAML registry plus a
dedicated validator, or a source-linked doc plus route tests). This document
tracks the split so reviewers know which enforcement mechanism to check for a
given surface, not to imply every gap must be closed. When adding a new
domain surface that produces or consumes structured data across a
service/SDK boundary, prefer registering a schema under
`packages/shared/contracts/` (see [README.md](../../contracts/README.md),
"Adding a contract") over inventing a new twin-and-test pattern.
