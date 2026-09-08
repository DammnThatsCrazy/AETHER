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
estimated_read_minutes: 6
toc_depth: 3
---

# Aether Spine P0 — IRRL Naming Overlay

**Status:** label map for the `rights_irrl` spine. Decided by
[ADR-011 D4](../decisions/ADR-011-spine-composition-kernel.md); the registry row
this labels is `in_flight`; the conformance map the Rights/IRRL spine must
pass is [SPINE_P0_CONFORMANCE_CHECKLIST.md](./SPINE_P0_CONFORMANCE_CHECKLIST.md).

This annex now tracks the **Rights Authority program** governed by
[RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md) (the frozen,
in-repo canonical implementation contract). Read this file as the reconciliation
substrate of that blueprint, and it is updated as the structured contracts it
names land.

## Canonical status — supersedes the standalone-IRRL framing

RIGHTS_AUTHORITY_BLUEPRINT.md supersedes any earlier proposal to build IRRL as an
**independent runtime, independent IRRL registry, independent retention
authority, or second rights ledger**. This overlay is superseded-and-retained:
it supersedes every residual "IRRL standalone runtime / parallel registry"
framing, and it is retained because its core naming-overlay doctrine is correct
and is exactly what the blueprint Phase 0 builds on.

The current authoritative statement of what IRRL is:

> IRRL is realized as the canonical **`rights_irrl` spine composition
> authority** inside the Contract Spine (via the Spine Composition Kernel),
> over the authorities that already own the governed state — `DataRightsGrant`
> (use authority), `ConsentPolicyDecision` (consent/decision records),
> `DataRetentionPolicy` + DSR propagation (retention/deletion/export), evidence
> and lineage, model governance, and the Graph Mutation Gateway. It is
> **not** another platform inside Aether, and it owns none of that state
> (blueprint §1.5, §14).

The structured canonical extension implementing this composition authority is
being built into a `services/rights_authority/` package (Effective Rights
Resolver, `RightsDecision`, canonical enums) plus nested governed components on
`DataRightsGrant` (blueprint §3–§5), with a TS twin in
`packages/shared/data-rights.ts`. Where this annex lists those homes they are the
**declared canonical homes per the blueprint**, with implementation state noted
honestly — none of the runtime enforcement is claimed "verified" until it is.

## Doctrine

Information Rights, Retention & Learning (IRRL) is a first-class **naming
overlay** on the rights machinery that already exists — not a parallel rights
registry. IRRL terms map onto existing ids; underlying data-authority state
continues to live in the owning services; the label must never drift from the
enforced behavior.

> The Rights/IRRL spine row references existing rights registries. A parallel
> rights registry is forbidden (ADR-011 D4). A row that re-defines an id owned
> elsewhere is a validator failure (ADR-011 D2).

The blueprint extends — it does not weaken — this doctrine. Under
[RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md), IRRL gains a
**decision/composition** code surface (the `rights_authority` package) that
records durable `RightsDecision` (`rdec_*`) records, but that surface composes
the owning authorities and stores **no source-data authority state of its own**.
So the overlay doctrine survives in stronger form: the new package is not a new
grant ledger, not a new consent decision store, and not a new retention store —
it resolves and records over them.

## The existing rights machinery (real symbols, verified in repo)

| Service | Real symbol · file | Role |
| --- | --- | --- |
| `services/integrations/data_rights` | `DataRightsGrant` · `models.py`; `DataRightsService` + `can_write_*`/`can_use_for_*` + `check_policy` → `PolicyCheckResult` · `service.py` | Use-authority ledger; fail-closed grant checks |
| `services/policy` | `ConsentPolicyDecision` · `contracts.py`; produced by `ConsentPolicyEngine` · `engine.py` | Explainable allow/deny/redact decision records |
| `services/dsr_propagation` | `DSRPropagationStep`, `DSR_COMPONENTS`, `overall_status` · `models.py` + `service.py` | DSR fan-out across every component that can hold subject data |
| `services/security` | `DataRetentionPolicy`, `DataRequest` · `contracts.py`; `DataRetentionService` · `retention.py`; sweep · `retention_worker.py` | Retention policy store + deletion/export data requests |
| `services/storage_lifecycle` | `run_bronze_compaction_loop` · `worker.py` | Object/Bronze lifecycle sweep (retention pass flag-gated via `security/retention_worker.py`) |
| Source-of-truth ledger | `DATA_RIGHTS_LEDGER.md` | Narrative grant model + fail-closed rules |
| Canonical blueprint | `RIGHTS_AUTHORITY_BLUEPRINT.md` | Frozen implementation contract for the structured extension + composition authority |

## Structured canonical vocabulary — declared homes & state

The blueprint (§3–§9) extends the grant ledger from source-data booleans into a
**structured rights contract** and adds a composition package. These are the
homes it declares. Implementation state is noted per symbol; treat **"declared
per the blueprint"** as canonical intent and **"implementing this session"** as
code landed or in progress against it — not as verified runtime enforcement.

| Symbol / authority | Declared home | Implementation state |
| --- | --- | --- |
| Nested governed components on `DataRightsGrant` — `source_use` / `generated_output_rights` / `learning_authority` / `disclosure_authority` / `retention_authority` / `termination_authority` | extended `DataRightsGrant` · `services/integrations/data_rights/models.py`; TS twin `packages/shared/data-rights.ts` (planned) | blueprint §3 (frozen field contract); implementing this session per the blueprint — **not yet in this checkout** |
| `SourceUseAuthority` (migrates `tenant_lake_allowed`/`tenant_graph_allowed`/`tenant_insights_allowed`/`olympus_baseline_allowed`/`cross_tenant_aggregate_allowed`/`commercial_reuse_allowed`) | data_rights / rights_authority models | blueprint §3.1; no semantic change on migration |
| `GeneratedOutputRights` (tenant license + Olympus proprietary + external disclosure + survival) | data_rights / rights_authority models | blueprint §3.2 (primary Olympus-strengthening contract) |
| `LearningAuthority` (replaces single `model_training_allowed` → `contributed_model_training`) | data_rights / rights_authority models | blueprint §3.3 migration map; mapping never broadens |
| `DisclosureAuthority`, `RetentionAuthority`, `TerminationAuthority` | data_rights / rights_authority models | blueprint §3.4–§3.5 |
| Canonical enums — `RightsDerivationClass`, `LearningClass`, `OwnershipClass`, `IntelligenceRightsProfile`, `DisclosureBoundary`, `OlympusPurpose`, `LifecycleAction`, `ModelRevocationState`, `RightsDecisionDisposition` | python models in `services/rights_authority/` (planned); TS twin `packages/shared/data-rights.ts` (planned) | blueprint §3, §5, §7–§9; vocabulary pointer: [RIGHTS_TAXONOMY.md](./RIGHTS_TAXONOMY.md) |
| `EffectiveRightsResolver` — `resolve_effective_rights(...)` → `RightsDecision` (`rdec_*`) | `services/rights_authority/` | blueprint §4. **Planned wiring**: composing `DataRightsService` grants + `ConsentPolicyDecision` + retention into durable, immutable, versioned `rdec_*` decisions is the M2 resolver milestone — not yet enforced in this checkout |
| `GeneratedIntelligenceEnvelope`, `RightsLineage` | `services/rights_authority/` | blueprint §5 |
| `Generalization Gateway` (`GeneralizationRequest`/`GeneralizedArtifact`) | `services/rights_authority/` gateway adapter owned by `rights_irrl` | blueprint §6. Runtime wiring that actually blocks a non-generalized write into the Olympus graph is **declared authority per the blueprint, not yet enforced** |
| `TrainingDataManifest` | `services/rights_authority/` (model governance surface) | blueprint §8 |
| Olympus internal actor/purpose — `OLYMPUS_INTERNAL` + `OlympusPurpose` (no global superuser) | rights_authority / Kyber request contracts | blueprint §7 |
| `SpineEnvelope.rights_decision_ref` | common spine envelope (`spine-envelope.ts` / `shared/spine/spine_envelope.py`) | blueprint §11: `@unpopulated` → optional during migration → required on governed material interactions |

## IRRL term → existing home

| IRRL term | Existing home (real symbol · path) | Direction | Enforcement note |
| --- | --- | --- | --- |
| `UseAuthority` | `DataRightsGrant` · `services/integrations/data_rights/models.py` | A grant **is** the authority to use one source's data for enumerated uses; today the grant's booleans (`tenant_lake_allowed`, `tenant_graph_allowed`, `tenant_insights_allowed`, `olympus_baseline_allowed`, `model_training_allowed`, `cross_tenant_aggregate_allowed`, `commercial_reuse_allowed`) are the specific authorities; the structured `SourceUseAuthority` (blueprint §3.1) nests them under `source_use` with **no semantic change on migration** | Fail-closed in `DataRightsService.check_policy` / `can_use_for_model_training` etc. (`service.py`); absence = deny (DATA_RIGHTS_LEDGER rule 1) |
| `RightsDecision` | Today: `ConsentPolicyDecision` · `services/policy/contracts.py` + `engine.py`; grant verdicts as `PolicyCheckResult` · `data_rights/service.py`. **Blueprint §4:** durable `RightsDecision` (`rdec_*`) produced by the `EffectiveRightsResolver` in `services/rights_authority/` (declared; implementing) | IRRL decision (allow / deny / redact, with reason + required/missing purposes) = a persisted `ConsentPolicyDecision` until the M2 resolver is canonical; the envelope's `rights_decision_ref` then points at a durable `rdec_*` decision | Explainable record carries `allowed`, `denied_reason`, `redacted_fields`; DSR steps attach it per component (`DSRPropagationStep.policy_decision_id`); `rdec_*` decisions are durable/versioned/evidence-linked by design (§4) |
| `DerivationClass` | Legacy: coarse `DataRightsGrant.model_training_allowed` · `data_rights/models.py`. **Blueprint §5:** `RightsDerivationClass` canonical enum (`SOURCE_REPRESENTATION` … `PLATFORM_KNOWLEDGE`) in `services/rights_authority/` (declared; implementing) | "Learning" derivation today collapses to one boolean; the canonical rights-derivation taxonomy is independent of the epistemic trust classes and must not merge with them | `can_use_for_model_training` (`service.py`) gates training pipelines today; the richer taxonomy is the declared canonical extension, not a new parallel symbol |
| `LearningAuthority` | Legacy: `model_training_allowed`. **Blueprint §3.3:** `LearningAuthority` with nine `LearningClass` values; migration maps `model_training_allowed` **only** → `contributed_model_training`, never broadens | The single training boolean becomes one of nine learning authorities; other authorities resolve from policy defaults / rights profile / agreement / data class | Contributed training stays explicitly granted; absence stays fail-closed |
| `RetentionPolicy` | `DataRetentionPolicy` (resource_type × retention_days × delete_behavior) · `services/security/contracts.py`; `DataRetentionService` · `services/security/retention.py`; sweep + storage lifecycle pass · `retention_worker.py` / `storage_lifecycle/worker.py` | IRRL retention policy = `DataRetentionPolicy`; blueprint §9 resolves effective retention by deterministic precedence over law/hold/contract/license/grant/profile/event class/storage; **no separate retention platform** | `DataRetentionService.sweep()`; legal holds and preserved resources block deletion; storage-plane retention flag-gated (FT-8) |
| `DataRightsEnvelope` | **Label only — no enforcing symbol yet.** Closest real analogue: `DataRightsGrant` + `PolicyCheckResult` (`data_rights/service.py`) and the per-event `ConsentState` snapshot. Blueprint §11 makes the envelope's `rights_decision_ref` the propagation mechanism | Naming term for the per-interaction rights state the envelope will carry | Rights gating today is real (the fail-closed checks above); a named `DataRightsEnvelope` + the envelope's `rights_decision_ref` field ship with the common spine envelope — Phase 3 (`@unpopulated`) |
| `Generalization Gateway` | Legacy: **label only** (doctrine in `GRAPH_OF_GRAPHS_DATA_USE.md`; closest real gates `can_write_olympus_baseline` / `can_use_for_cross_tenant_aggregate`). **Blueprint §6:** declared runtime adapter owned by `rights_irrl` in `services/rights_authority/` producing `GeneralizedArtifact` records; no parallel graph | Naming term for the boundary that generalizes/aggregates before data crosses into Olympus / shared intelligence; only qualifying outputs enter generalized Olympus knowledge | No rights-filtered intelligence-layer enforcement exists yet (SPINE_P0_ARCHITECTURE honesty list); the gateway **blocking** an Olympus graph write is declared-per-blueprint and not yet enforced (in_flight) |

## What this is NOT

- **Not a new rights registry.** There is exactly one grant ledger (`DataRightsGrant`
  + `DATA_RIGHTS_LEDGER.md`), one consent/decision surface (`consent-registry.json`
  → `ConsentPolicyDecision`), and one retention store (`DataRetentionPolicy`).
  IRRL adds labels (and, per the blueprint, durable `rdec_*` decision *records*)
  on top; it adds no source-data authority rows, no parallel ids, and no second
  ledger or retention store.
- **Not a new enforcement substrate that bypasses owning services.** Enforcement
  continues to compose the owning authorities: `DataRightsService` gate checks at
  lake/graph/training/baseline entry points, the `ConsentPolicyEngine` decision
  records, `DataRetentionService` sweeps, and DSR propagation. Where the blueprint
  adds a `rights_authority` composition surface, it resolves over those
  authorities and records decisions; it does not own their state.
- **Not a standalone IRRL runtime.** Earlier "IRRL as its own runtime / parallel
  registry / independent retention authority" framing is retired by
  [RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md) (see Canonical
  status above).
- **Structural guard.** The spine-registry validator (Phase 2) forbids a spine row
  from registering a parallel rights registry or re-defining ids owned by the
  rights machinery (`DataRightsGrant` fields, consent purpose tokens,
  `DataRetentionPolicy`, readiness tokens). A row that re-defines an id owned
  elsewhere is a hard failure; an unresolved reference must be declared `pending`
  with a reason and a resolving milestone (ADR-011 D1/D2). The blueprint's
  Phase 0 validator (blueprint §13) extends the guard to the new vocabulary names
  (`irrl-registry.json`, `ownership-registry.json`, `learning-rights-registry.json`,
  `retention-rights-registry.json`, `generalization-rights-registry.json` are
  prohibited unless registered as canonical vocabularies under the Contract Spine).

## Where the Rights/IRRL spine row points

The registry row is `in_flight`; this doc is the label map it consumes. The row
**references** — never re-defines — the registries that already own each id:

- `consent-registry.json` purpose + governance tokens (`modelTrainingPermission`,
  `graphProjectionPermission`, …) via `ConsentPolicyDecision` / `ConsentState`;
- the `DataRightsGrant` ledger and `DATA_RIGHTS_LEDGER.md` for use authority, now
  extended by the blueprint's structured components;
- `DataRetentionPolicy` + DSR propagation (`DSR_COMPONENTS`) for retention,
  deletion, and export fan-out;
- `readiness-vocabulary.json` **presentation-only** for the row's readiness key —
  never a certification token or `production_ready` (ADR-011 D5);
- the blueprint's structured vocabulary homes in `services/rights_authority/` and
  the extended `data_rights` models for the canonical contracts and enums, once
  they land (see Structured canonical vocabulary above).

Per [SPINE_REGISTRY_STATUS.md](./SPINE_REGISTRY_STATUS.md), the Rights/IRRL row
sits `PARTIAL` with `implementationState = in_flight` and its 14 conformance
checks `open`; it moves toward `CANONICAL` only after the blueprint phases land
(contracts → resolver → propagation → gateway → conformance closure, blueprint §17)
and its conformance evidence is verified end to end. `RightsContext`
(projection-carried rights context) is a Phase 5+ overlay label for projection
limitation/state sections and likewise has no enforcing symbol today.

Related: [RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md)
(canonical implementation contract),
[RIGHTS_TAXONOMY.md](./RIGHTS_TAXONOMY.md) (four-class taxonomy + vocabulary
reference),
[SPINE_P0_ARCHITECTURE.md](./SPINE_P0_ARCHITECTURE.md) (§5, honesty list),
[ADR-011](../decisions/ADR-011-spine-composition-kernel.md) (D2/D4),
[SPINE_P0_PHASES.md](../plans/SPINE_P0_PHASES.md) (Phase 5),
[DATA_RIGHTS_LEDGER.md](./DATA_RIGHTS_LEDGER.md),
[GRAPH_OF_GRAPHS_DATA_USE.md](./GRAPH_OF_GRAPHS_DATA_USE.md).
