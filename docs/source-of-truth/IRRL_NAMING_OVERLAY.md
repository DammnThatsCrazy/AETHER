---
title: "Aether Spine P0 — IRRL Naming Overlay (Phase 5)"
slug: architecture/irrl-naming-overlay
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
source_files:
  - Backend Architecture/aether-backend/services/integrations/data_rights/models.py
  - Backend Architecture/aether-backend/services/integrations/data_rights/service.py
  - Backend Architecture/aether-backend/services/policy/contracts.py
  - Backend Architecture/aether-backend/services/policy/engine.py
  - Backend Architecture/aether-backend/services/dsr_propagation/models.py
  - Backend Architecture/aether-backend/services/security/contracts.py
  - Backend Architecture/aether-backend/services/security/retention.py
  - docs/source-of-truth/DATA_RIGHTS_LEDGER.md
last_synced_commit: "pending"
estimated_read_minutes: 5
toc_depth: 3
---

# Aether Spine P0 — IRRL Naming Overlay

**Status:** Phase 5 source-of-truth annex (label map). Decided by
[ADR-011 D4](../decisions/ADR-011-spine-composition-kernel.md); the registry row
this labels is created in Phase 2; the conformance map the Rights/IRRL spine must
pass is [SPINE_P0_CONFORMANCE_CHECKLIST.md](./SPINE_P0_CONFORMANCE_CHECKLIST.md).

## Doctrine

Information Rights, Retention & Learning (IRRL) is a first-class **naming
overlay** on the rights machinery that already exists — not a new runtime, and
not a parallel rights registry. IRRL terms map onto existing ids; enforcement
continues to live in the owning services; the label must never drift from the
enforced behavior.

> The Rights/IRRL spine row references existing rights registries. A parallel
> rights registry is forbidden (ADR-011 D4). A row that re-defines an id owned
> elsewhere is a validator failure (ADR-011 D2).

## The existing rights machinery (real symbols, verified in repo)

| Service | Real symbol · file | Role |
| --- | --- | --- |
| `services/integrations/data_rights` | `DataRightsGrant` · `models.py`; `DataRightsService` + `can_write_*`/`can_use_for_*` + `check_policy` → `PolicyCheckResult` · `service.py` | Use-authority ledger; fail-closed grant checks |
| `services/policy` | `ConsentPolicyDecision` · `contracts.py`; produced by `ConsentPolicyEngine` · `engine.py` | Explainable allow/deny/redact decision records |
| `services/dsr_propagation` | `DSRPropagationStep`, `DSR_COMPONENTS`, `overall_status` · `models.py` + `service.py` | DSR fan-out across every component that can hold subject data |
| `services/security` | `DataRetentionPolicy`, `DataRequest` · `contracts.py`; `DataRetentionService` · `retention.py`; sweep · `retention_worker.py` | Retention policy store + deletion/export data requests |
| `services/storage_lifecycle` | `run_bronze_compaction_loop` · `worker.py` | Object/Bronze lifecycle sweep (retention pass flag-gated via `security/retention_worker.py`) |
| Source-of-truth ledger | `DATA_RIGHTS_LEDGER.md` | Narrative grant model + fail-closed rules |

## IRRL term → existing home

| IRRL term | Existing home (real symbol · path) | Direction | Enforcement note |
| --- | --- | --- | --- |
| `UseAuthority` | `DataRightsGrant` · `services/integrations/data_rights/models.py` | A grant **is** the authority to use one source's data for enumerated uses; the grant's booleans (`tenant_lake_allowed`, `tenant_graph_allowed`, `olympus_baseline_allowed`, `model_training_allowed`, `cross_tenant_aggregate_allowed`, `commercial_reuse_allowed`) are the specific authorities | Fail-closed in `DataRightsService.check_policy` / `can_use_for_model_training` etc. (`service.py`); absence = deny (DATA_RIGHTS_LEDGER rule 1) |
| `RightsDecision` | `ConsentPolicyDecision` · `services/policy/contracts.py` + `engine.py`; grant verdicts as `PolicyCheckResult` · `data_rights/service.py` | IRRL decision (allow / deny / redact, with reason + required/missing purposes) = a persisted `ConsentPolicyDecision`; the envelope's `rights_decision_ref` points at it | Explainable record carries `allowed`, `denied_reason`, `redacted_fields`; DSR steps attach it per component (`DSRPropagationStep.policy_decision_id`) |
| `DerivationClass` | `DataRightsGrant.model_training_allowed` · `data_rights/models.py`; `modelTrainingPermission` consent tokens · `packages/shared/contracts/consent-registry.json` | "Learning" derivation today collapses to one boolean: trainable or not | Real but coarse: `can_use_for_model_training` (`service.py`) gates training pipelines; consent opt-in purposes gate the derived uses. A finer derivation taxonomy is future IRRL work, not a new symbol now |
| `RetentionPolicy` | `DataRetentionPolicy` (resource_type × retention_days × delete_behavior) · `services/security/contracts.py`; `DataRetentionService` · `services/security/retention.py`; sweep + storage lifecycle pass · `retention_worker.py` / `storage_lifecycle/worker.py` | IRRL retention policy = `DataRetentionPolicy`; deletion/export of a subject's data runs as `DataRequest`s + DSR propagation | `DataRetentionService.sweep()`; legal holds and preserved resources block deletion; storage-plane retention flag-gated (FT-8) |
| `DataRightsEnvelope` | **Label only — no enforcing symbol yet.** Closest real analogue: `DataRightsGrant` + `PolicyCheckResult` (`data_rights/service.py`) and the per-event `ConsentState` snapshot | Naming term for the per-interaction rights state the envelope will carry | Rights gating today is real (the fail-closed checks above); a named `DataRightsEnvelope` + the envelope's `rights_decision_ref` field ship with the common spine envelope — Phase 3 (`@unpopulated`) — and this label map, Phase 5 |
| `Generalization Gateway` | **Label only — no enforcing symbol yet.** Doctrine only: `GRAPH_OF_GRAPHS_DATA_USE.md` transition rules + cross-graph properties (`pii_stripped`, `olympus_lineage_id`, `grant_id`); closest real gates `can_write_olympus_baseline` / `can_use_for_cross_tenant_aggregate` | Naming term for the boundary that generalizes/aggregates before data crosses into Olympus / shared intelligence | No rights-filtered intelligence-layer enforcement exists (SPINE_P0_ARCHITECTURE honesty list). Resolving milestone: Graph-of-Graphs rights-filtered intelligence enforcement — a follow-on **beyond** SPINE_P0_PHASES phases 1–7; the naming row itself lands Phase 5 |

## What this is NOT

- **Not a new rights registry.** There is exactly one grant ledger (`DataRightsGrant`
  + `DATA_RIGHTS_LEDGER.md`), one consent/decision surface (`consent-registry.json`
  → `ConsentPolicyDecision`), and one retention store (`DataRetentionPolicy`). IRRL
  adds labels on top; it adds no rows, no ids, and no store.
- **Not a new enforcement runtime.** Enforcement continues in the owning services:
  `DataRightsService` gate checks at lake/graph/training/baseline entry points, the
  `ConsentPolicyEngine` decision records, `DataRetentionService` sweeps, and DSR
  propagation. IRRL has no code path of its own.
- **Structural guard.** The spine-registry validator (Phase 2) forbids a spine row
  from registering a parallel rights registry or re-defining ids owned by the
  rights machinery (`DataRightsGrant` fields, consent purpose tokens, `DataRetentionPolicy`,
  readiness tokens). A row that re-defines an id owned elsewhere is a hard failure;
  an unresolved reference must be declared `pending` with a reason and a resolving
  milestone (ADR-011 D1/D2). This annex is the reference the guard checks the
  Rights/IRRL row against.

## Where the Rights/IRRL spine row points

The registry row is created in Phase 2; this doc is the Phase 5 label map it
consumes. When the row lands it **references** — never re-defines — the existing
registries that already own each id:

- `consent-registry.json` purpose + governance tokens (`modelTrainingPermission`,
  `graphProjectionPermission`, …) via `ConsentPolicyDecision` / `ConsentState`;
- the `DataRightsGrant` ledger and `DATA_RIGHTS_LEDGER.md` for use authority;
- `DataRetentionPolicy` + DSR propagation (`DSR_COMPONENTS`) for retention,
  deletion, and export fan-out;
- `readiness-vocabulary.json` **presentation-only** for the row's readiness key —
  never a certification token or `production_ready` (ADR-011 D5).

Per [SPINE_REGISTRY_STATUS.md](./SPINE_REGISTRY_STATUS.md), the Rights/IRRL row
sits `LEGACY` until its registry row, envelope, and conformance evidence land
`PARTIAL` → `CANONICAL`. `RightsContext` (projection-carried rights context) is a
Phase 5+ overlay label for projection limitation/state sections and likewise has
no symbol today.

Related: [SPINE_P0_ARCHITECTURE.md](./SPINE_P0_ARCHITECTURE.md) (§5, honesty
list), [ADR-011](../decisions/ADR-011-spine-composition-kernel.md) (D2/D4),
[SPINE_P0_PHASES.md](../plans/SPINE_P0_PHASES.md) (Phase 5),
[DATA_RIGHTS_LEDGER.md](./DATA_RIGHTS_LEDGER.md),
[GRAPH_OF_GRAPHS_DATA_USE.md](./GRAPH_OF_GRAPHS_DATA_USE.md).
