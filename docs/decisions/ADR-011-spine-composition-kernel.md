---
title: "ADR-011: Spine Composition Kernel"
slug: decisions/adr-011-spine-composition-kernel
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
---

# ADR-011: Spine Composition Kernel

**Status**: Accepted (8.12.0)

## Context

Aether now runs on a governed truth substrate: a canonical contract spine, an
intelligence projection plane over canonical truth, a graph mutation gateway,
rights/data-use machinery, a readiness vocabulary, and Kyber as the operator
control surface. What is missing is a **governing statement of what a "spine"
is and what a spine PR must declare**. The founding architecture document
(*Aether Spine P0 — Architecture Placement, Operation & Value*, filed verbatim
in [SPINE_P0_ARCHITECTURE.md](../source-of-truth/SPINE_P0_ARCHITECTURE.md))
makes that statement: every existing and future spine declares what it owns,
what it may read or write, which canonical contracts it uses, which authorities
it depends on, what it publishes, how it degrades, and how it is exposed. It is
the ground-zero / founding-spine architecture.

Today the word "spine" already means three load-bearing things, and this ADR
must reconcile — never fork — each of them:

1. **The Truth Kernel "contract spine".** The canonical-schema layer:
   `packages/shared/*.ts` contracts, the JSON registries under
   `packages/shared/contracts/`, their Pydantic mirrors, and the unbypassable
   generation/validation gates (`scripts/generate_contracts.py`,
   `scripts/generate_platform_contracts.py`, `scripts/validate_contracts.py`,
   `scripts/repo_doctor.py --ci`). The kernel decided here is implemented
   **inside** this machinery, not beside it.
2. **The Intelligence Projection Plane's hard-spine vocabulary.** ADR-010 +
   `intelligence-projection-registry.json` already express the doctrine
   "a projection reads canonical authorities; a 360 is never a competing system
   of record." Its validator hard-codes a `SPINE_INDEX` of resolved spines
   (contract_spine, identity_resolution, evidence_provenance, temporal_kernel,
   relationship_fidelity, upr, computation_substrate,
   measurement_outcome_contract, tenant_readiness, exploration_fabric,
   infrastructure_model, model_governance, agentic_runtime_access,
   attribution_architecture, graph_history_replay, grouping_membership,
   context_capsule_semantics) and deliberately leaves two spines
   (`journey_continuity`, `reconciled_control_plane`) **pending**, declared
   per-projection via `pendingAuthority {kind:"spine"}` with the comment
   "until the spine plane formalizes them." (As filed this ADR counted five
   pending spines; the 2026-09-05 re-cut onto `origin/main` re-formalized
   `graph_history_replay`, `grouping_membership`, and
   `context_capsule_semantics` to `implemented` once their authorities —
   `services/temporal360` history replay, `services/population` membership
   governor + append-only definition versions, `services/geographic360` capsule
   semantics — landed on the base.) That registry is the closest
   existing analog to a spine registry; this ADR is the spine plane that
   formalizes it.
3. **"control spine"** in `docs/FOUNDING-TENANT-PRODUCTION.md` — an unrelated
   operations/deployment-validation meaning of "spine". Flagged once here so
   future readers are not confused; it is out of scope.

Three forces make the kernel necessary:

- **Ad-hoc authorities drift toward competing platforms.** Without a declared
  authority boundary, a new domain becomes a parallel store, a parallel write
  path, or a parallel readiness/metrics/consent surface that re-answers what
  canonical planes already answer.
- **Spines must be implementable out of order.** Order-independent composition
  requires every spine's dependency state, adapter boundary, degradation
  behavior, and readiness to be explicit before it is implemented.
- **Existing work must be inventoried honestly, like tetris.** The authorities
  below the kernel already exist under their current names. The kernel
  organizes them; it does not reimplement them.

## Decision

Adopt a **Spine Composition Kernel** implemented inside the Contract Spine:
one canonical machine-readable spine registry, a shared common spine envelope,
IRRL as a first-class naming overlay on the existing rights machinery, and a
14-item conformance contract enforced by the contract validator — all enforcing
the single binding doctrine:

> **Every spine is a governed authority or cross-cutting control boundary. No
> spine is a private platform inside the platform.**

The kernel is **additive and reversible** (registry + validator + contracts;
no data migration, no new runtime). The net-new surface is deliberately small:
the kernel/registry/envelope/IRRL vocabulary and the conformance gate.
Everything else is organization and labeling of authorities that already exist.
The kernel **does not create** parallel metric, readiness, surface, consent,
evidence, or provider registries — that prohibition is structurally enforced.

### D1 — A spine is a governed authority, never a private platform

Every spine row declares: ownership and non-ownership, canonical authority
status, consumed and published ports, hard/soft/runtime/policy dependencies,
mutation policy, tenant and rights boundary, implementation lifecycle,
readiness capability key, surfaces and adapters, security/compliance controls,
observability and recovery, and conformance gates. The validator hard-fails on
any row that leaves a reference unresolved or silent — unresolved refs must be
declared `pending` with a reason and a resolving milestone.

### D2 — One canonical spine registry, referencing — never re-defining

`packages/shared/contracts/spine-registry.json` is the single new canonical
registry for spines. Every spine id, dependency, contract ref, readiness key,
surface ref, and authority ref **resolves against the registry that owns it**
(`surface-capability-registry.json`, `readiness-vocabulary.json`,
`consent-registry.json`, `metric-registry.json`, `graph-mutation-registry.json`,
the evidence manifest, `intelligence-projection-registry.json`, …). A spine row
that re-defines an id owned elsewhere is a hard validator failure. The
projection plane's `SPINE_INDEX` and `pendingAuthority` declarations remain
authoritative for projections and are derived from / formalized by the kernel,
not duplicated.

### D3 — The common spine envelope reuses canonical primitives

The common spine envelope (`SpineEnvelope`) composes the canonical primitives —
`EntityRef`, `EvidenceRef`, `PageRequest`, the temporal envelope fields,
`ContextCapsule`, provenance — and adds the envelope fields the architecture
calls for (`tenant_id`, `request_id`, `scope_ref`, `subject_refs`, `as_of`,
`valid_time`, `identity_watermark`, `data_watermark`, `policy_ref`,
`consent_decision_ref`, `rights_decision_ref`, `evidence_refs`, `quality`,
`contract_versions`, `model_refs`, `lineage_refs`). Fields with no producer yet
(`identity_watermark`, `rights_decision_ref`) are declared present-but-unpopulated
(`@unpopulated`); no producer is claimed until one ships. Nothing is
re-defined.

### D4 — IRRL is a naming overlay, not a new runtime

Information Rights, Retention & Learning becomes a first-class **naming
overlay** on the rights machinery that already exists:
`services/integrations/data_rights` (`DataRightsGrant`, `model_training_allowed`),
`services/policy` (`ConsentPolicyDecision`), `services/dsr_propagation`,
`services/storage_lifecycle`, and the source-of-truth ledger
`DATA_RIGHTS_LEDGER.md`. IRRL terms (`DataRightsEnvelope`, `UseAuthority`,
`DerivationClass`, `RetentionPolicy`, `Generalization Gateway`,
`RightsDecision`) map onto those existing ids; enforcement continues to live in
the owning services. The Rights/IRRL spine row references existing rights
registries; a parallel rights registry is forbidden.

### D5 — `implementationState` is repo metadata, NOT readiness (unchanged)

ADR-010 D3 applies unchanged to spines. Spine `implementationState` records
where a spine is in the codebase, never production readiness. Spine
`readinessKey`s join `readiness-vocabulary.json` **presentation-only** and never
emit a certification token or `production_ready`.

### D6 — The 14-item conformance contract is enforced by the contract validator

Each spine PR must pass the architecture's 14-item conformance contract
(ownership, canonical-contract registration, ports/adapters, dependency DAG
validation, typed degradation, temporal/watermark behavior,
evidence/restatement, tenant/consent/rights/retention/residency/export, graph
mutation policy, API/event/UI/Kyber integration, readiness/entitlement,
security/compliance/observability evidence, migration/recompute/rollback plan,
positive/negative/replay/isolation/golden tests). `SPINE_P0_CONFORMANCE_CHECKLIST.md`
maps each item to concrete evidence; the validator refuses a state flip while a
conformance gap is open.

## Consequences

**Positive.** One governing doctrine replaces three overlapping spine meanings;
the registry's pending projection spines (`journey_continuity`,
`reconciled_control_plane` — as of the 2026-09-05 re-cut; the other three
filed-as-pending projection spines were re-formalized to `implemented` once
their authorities landed) gain a home to be formalized in
(`SPINE_REGISTRY_STATUS.md`); new spines attach through governed ports instead
of bespoke integrations; implementation becomes order-independent; the whole
kernel is additive and reversible.

**Negative.** Every spine row must declare its boundaries — no silent
references; no registry row implies readiness; IRRL is labeling over existing
rights machinery, so the label must never drift from the enforced behavior; the
"no parallel registries" rule requires the validator to stay vigilant.

**Follow-on.** Net-new capabilities ship as the tracked milestones in
[SPINE_P0_PHASES.md](../plans/SPINE_P0_PHASES.md), ledged honestly in
[SPINE_REGISTRY_STATUS.md](../source-of-truth/SPINE_REGISTRY_STATUS.md), against
the architecture filed in
[SPINE_P0_ARCHITECTURE.md](../source-of-truth/SPINE_P0_ARCHITECTURE.md).

Related: [ADR-010: Intelligence Projection Plane](./ADR-010-intelligence-projection-plane.md)
(the doctrine this kernel generalizes), the SOT/plan/ledger links above.
