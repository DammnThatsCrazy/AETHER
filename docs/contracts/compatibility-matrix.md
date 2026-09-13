---
title: Contract Compatibility Matrix
slug: contracts/compatibility-matrix
section: reference
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# Contract Compatibility Matrix

This document maps every schema/registry under `contracts/delivery/` and
`packages/shared/contracts/` to its current version fields, and records which
contracts must change together (lock-step) versus which can change
independently. See [VERSION_POLICY.md](../../contracts/VERSION_POLICY.md) for
the versioning rules this matrix assumes.

## How to read this table

- **`schemaVersion`** — the structural shape of the JSON document itself.
- **`contractVersion`** — the semantic version of the data the schema
  describes (bumped per the compatibility rules in `VERSION_POLICY.md`).
- Delivery schemas (`contracts/delivery/*.schema.json`) use a JSON Schema
  `$id` versioned path (`.../v1`) instead of an in-body `contractVersion`.
- A dash (`-`) means the field is not present in that file.

## `contracts/delivery/` — delivery pipeline schemas

All delivery schemas are pinned at `$id` version `v1`. They are consumed by
`scripts/delivery_orchestrator.py`, `scripts/artifact_builder.py`, and the
release-evidence tooling under `scripts/release/`.

| Schema | `$id` version | Lock-step with |
|---|---|---|
| `release-candidate.schema.json` | v1 | `staging-orchestration-state.schema.json`, `release-evidence-bundle.schema.json`, `config/impact_graph.json` (`release-candidate` contract entry) |
| `staging-orchestration-state.schema.json` | v1 | `release-candidate.schema.json`, `staging-lifecycle-result.schema.json`, `config/impact_graph.json` |
| `staging-lifecycle-result.schema.json` | v1 | `staging-orchestration-state.schema.json`, `migration-evidence.schema.json` |
| `migration-evidence.schema.json` | v1 | `staging-lifecycle-result.schema.json` |
| `environment-capability-snapshot.schema.json` | v1 | `environment-resolution.schema.json`, `config/impact_graph.json` |
| `environment-resolution.schema.json` | v1 | `environment-capability-snapshot.schema.json` |
| `effective-iam-comparison.schema.json` | v1 | `effective-iam-evidence.schema.json`, `config/impact_graph.json` |
| `effective-iam-evidence.schema.json` | v1 | `effective-iam-comparison.schema.json` |
| `terraform-reconciliation.schema.json` | v1 | `terraform-remote-inventory.schema.json`, `config/impact_graph.json` |
| `terraform-remote-inventory.schema.json` | v1 | `terraform-reconciliation.schema.json` |
| `deployment-impact.schema.json` | v1 | `impact-graph-index.schema.json` |
| `impact-graph-index.schema.json` | v1 | `deployment-impact.schema.json`, `config/impact_graph.json` |
| `artifact-closure.schema.json` | v1 | `release-candidate.schema.json` |
| `change-plan.schema.json` | v1 | `scripts/change_plan.py` |
| `failure-envelope.schema.json` | v1 | Consumed broadly by delivery orchestration; no single lock-step partner |
| `hosted-adapter-request.schema.json` | v1 | `hosted-adapter-result.schema.json`, `profile-delivery-operation.schema.json` |
| `hosted-adapter-result.schema.json` | v1 | `hosted-adapter-request.schema.json` |
| `profile-delivery-operation.schema.json` | v1 | `hosted-adapter-request.schema.json`, `hosted-adapter-result.schema.json` |
| `release-evidence-bundle.schema.json` | v1 | `release-candidate.schema.json`, `scripts/release/evidence_bundle.py` |
| `telemetry-event.schema.json` | v1 | `config/telemetry_contracts.json`, `scripts/validate_telemetry_contracts.py` |

Note: `release-candidate.schema.json`'s `$id` is the one exception in this
directory — it points at the filename itself
(`.../release-candidate.schema.json`) rather than a `/v1` path. This is a
pre-existing inconsistency, not a version bump; do not "fix" it without
checking every consumer that resolves `$id` by string match.

## `packages/shared/contracts/` — domain registries

| Registry | `schemaVersion` | `contractVersion` | Lock-step with |
|---|---|---|---|
| `event-registry.json` | 2.2.0 | 0.1.0-alpha.0 | `packages/shared/events.ts`, `Backend Architecture/aether-backend/services/ingestion/generated_registry.py`, `consent-registry.json` (via `consent_purpose` refs), native iOS/Android regions (`mobile_native_regions` ownership category) |
| `consent-registry.json` | 2.0.0 | 8.12.0 | `event-registry.json` (event `consent_purpose` must exist here), `packages/shared/consent.ts` |
| `integration-consent-registry.json` | 1.0.0 | 8.13.0 | `consent-registry.json` (shares consent-purpose vocabulary), `processingDecisionVersion`/`canonicalConsentReceiptVersion` fields versioned independently |
| `graph-mutation-registry.json` | 1.0.0 | 1.0.0 | `intelligence-projection-registry.json` (`graphMutationPolicies` enum reused), `spine-registry.json` |
| `intelligence-projection-registry.json` | 1.0.0 | 1.0.0 | `packages/shared/intelligence-projection.ts`, `packages/shared/intelligence-projections_generated.ts`, `graph-mutation-registry.json`, `spine-registry.json` |
| `spine-registry.json` | 1.0.0 | 1.0.0 | `packages/shared/spine-registry.ts`, `intelligence-projection-registry.json`, `rights-vocabulary.json` (rights_irrl spine row) |
| `relationship-predicate-registry.json` | 1.0.0 | 1.0.0 | `relationship-motif-registry.json`, `packages/shared/relationship-predicate-registry.ts` |
| `relationship-motif-registry.json` | 1.0.0 | 1.0.0 | `relationship-predicate-registry.json` (motifs reference predicate families), `packages/shared/relationship-motif-registry.ts` |
| `relationship-fidelity-vector.schema.json` | - | - | `relationship-predicate-registry.json`, `relationship-motif-registry.json` |
| `observation-envelope-registry.json` | 1.0.0 | - | `packages/shared/observation-envelope.ts`, `Backend Architecture/aether-backend/shared/observation/envelope.py` (three-way parity enforced by `tests/contracts/test_observation_envelope_parity.py`) |
| `rights-vocabulary.json` | 2.0.0 | 0.1.0-alpha.0 | `packages/shared/data-rights.ts`, `Backend Architecture/**/data_rights/models.py`, `spine-registry.json` (rights_irrl row) |
| `readiness-vocabulary.json` | 2.0.0 | 2.0.0 | Consumed by release-readiness tooling; no direct registry lock-step |
| `metric-registry.json` | - | 1 | `packages/shared/measurement-contract.ts`, `docs/_generated/metric-registry-table.md` |
| `outcome-type-registry.json` | 1 | 1.0.0 | `interaction-vocabulary.json` (shared actor/evidence vocabulary) |
| `interaction-vocabulary.json` | 1.0.0 | 1.0.0 | `outcome-type-registry.json`, `signal-use-matrix.json` |
| `signal-use-matrix.json` | 1.0.0 | 0.1.0-alpha.0 | `interaction-vocabulary.json`, `traffic-source-registry.json` |
| `traffic-source-registry.json` | 1.0.0 | 1.0.0 | `signal-use-matrix.json` |
| `comparison-registry.json` | 1.0.0 | 1.0.0 | `relationship-fidelity-vector.schema.json` (materiality/causal claim vocab reused) |
| `context-capsule-registry.json` | 1.0.0 | 1.0.0 | `location-registry.json` (shares precision classes) |
| `location-registry.json` | 1.0.0 | 1.0.0 | `context-capsule-registry.json` |
| `filter-field-registry.json` | 1.0.0 | 1.0.0 | `surface-capability-registry.json` (filter dispositions) |
| `surface-capability-registry.json` | 1.0.0 | 1.0.0 | `filter-field-registry.json`, `lens-registry.json` |
| `lens-registry.json` | 1.0.0 | 1.0.0 | `surface-capability-registry.json` |
| `projector-ownership-registry.json` | 1.0.0 | 1.0.0 | `intelligence-projection-registry.json` (projector-to-projection ownership) |
| `task-profile-registry.json` | 1.0.0 | 1.0.0 | `model-registry.json` (model roles referenced by profiles) |
| `model-registry.json` | 1.0.0 | 1.0.0 | `task-profile-registry.json` |
| `social-provider-capability-vocabulary.json` | 1.0.0 | 1.0.0 | `social-silver-facts.schema.json` |
| `social-silver-facts.schema.json` | - | - | `social-provider-capability-vocabulary.json` |
| `temporal-policy-registry.json` | 1.0.0 | - | Consumed by policy enforcement; no registered lock-step registry |
| `kyber-feature-surface-manifest.json` | 1.0.0 | - | `frontend/kyber/**` surfaces (not schema-linked; validated structurally only) |
| `evidence-manifest.schema.json` | - | - | `scripts/release/evidence_bundle.py`, `release-evidence-bundle.schema.json` (delivery-side sibling) |
| `incentive-context.schema.json` | - | - | `outcome-type-registry.json` |

## Cross-directory relationships

A few contracts span both directories:

- `evidence-manifest.schema.json` (domain, `packages/shared/contracts/`) and
  `release-evidence-bundle.schema.json` (delivery, `contracts/delivery/`)
  describe adjacent but distinct evidence shapes — the domain manifest is
  produced by application-level release checks, the delivery bundle wraps it
  for the delivery pipeline. They are not currently schema-linked
  (`$ref`); treat any structural change to one as a signal to check the other.
- `metric-registry.json` and `contracts/delivery/telemetry-event.schema.json`
  both describe measured signals but serve different planes (product metrics
  vs. delivery-pipeline telemetry) and are versioned independently.

## Lock-step enforcement

Lock-step relationships listed above are enforced by the `change_categories`
entries in `docs/source-of-truth/repo_consistency_ownership.json` (see
[validation.md](./validation.md)), not by this document. This matrix is the
human-readable index; the ownership map is the machine-checked source of
truth for which files must change together and which commands must pass.

## Compatibility across `contractVersion` bumps

Per `VERSION_POLICY.md`, all registries are pre-1.0 (`0.x` family) or track an
internal `contractVersion` independent of the platform's `0.x` release train
(several registries, e.g. `consent-registry.json` at `8.12.0`, use their own
long-lived counter). Two contracts are "compatible" across versions only when:

1. Both sides are on the same `contractVersion` major (or the same exact
   version, for internal counters that don't follow semver majors), and
2. No `required_commands` in the ownership map for the touched category are
   failing.

There is no automated cross-registry version-skew checker beyond
`scripts/validate_contracts.py`'s explicit cross-file checks (event families,
consent purposes) and the domain-specific validators
(`scripts/validate_spine_registry.py`, `scripts/validate_intelligence_projections.py`,
`scripts/validate_rights_vocabulary.py`, `scripts/generate_platform_contracts.py --check`).
Contracts without an explicit validator pairing rely on `make repo-doctor`
catching broken registry bindings structurally.
