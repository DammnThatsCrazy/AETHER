---
title: "Aether Spine P0 — Spine Registry Status"
slug: architecture/spine-registry-status
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---
# Aether Spine P0 — Spine Registry Status

This is the output ledger for the **Spine Composition Kernel**
([ADR-011](../decisions/ADR-011-spine-composition-kernel.md)): one row per
spine / authority / program capability, tracking how far each has moved onto
the governed architecture described in
[SPINE_P0_ARCHITECTURE.md](./SPINE_P0_ARCHITECTURE.md) (filed verbatim as the
ground-zero founding target). The phase that moves each row is defined in
[../plans/SPINE_P0_PHASES.md](../plans/SPINE_P0_PHASES.md).

**State vocabulary** (per row): `CANONICAL` = a governed spine row exists in
the canonical `spine-registry` and its 14-item conformance gate is verified end
to end; `PARTIAL` = the governed spine row exists and some spine capabilities
have landed (code, envelope, joins) but full conformance is not yet verified;
`LEGACY` = the authority exists in code under its current name but the governed
row has not advanced, or the net-new spine capability does not exist yet (such
spines are formally declared `pending` rows in the registry and stay `LEGACY`
until real implementation lands); `BLOCKED` = cannot proceed without an
external dependency.

**Honesty rule.** Every row below is tracked against the canonical,
machine-readable `spine-registry`
(`packages/shared/contracts/spine-registry.json`), which Phase 2 shipped with
**34 governed rows** (25 `implemented`, 7 `in_flight`, 2 declared `pending`).
Phase 2 shipped **33 governed rows** (21 `implemented`) on the main-based lane;
the re-cut onto the 360-foundation base (`fced2960`) extended it to **34
governed rows** (22 `implemented`) by formalizing `infrastructure_model` —
already named among the resolved spines in ADR-011 §2 but absent from the
main-based registry — and the re-cut onto `origin/main` (2026-09-05)
re-formalized `graph_history_replay`, `grouping_membership`, and
`context_capsule_semantics` from `pending` to `implemented`: their authorities
(`services/temporal360` history replay, `services/population` membership
governor + append-only definition versions, `services/geographic360` capsule
semantics) landed on the base the program is now cut against.
The registry is validated on every `make ci-check`
(`scripts/validate_spine_registry.py` — schema, conformance, cross-registry,
lifecycle, ownership, inventory), its generated TS/PY/MD twins are byte-stable,
and the projection plane now derives its resolved-spine index from it (Phase 4).
A code authority existing under its current name is **not** enough for
`PARTIAL` — the governed registry row must exist too (it does for every
authority below). **No row is `CANONICAL`**: each non-program row carries its
14 conformance checks in-registry, all currently `open` (declared, not yet
verified with evidence). Rows move LEGACY → PARTIAL → CANONICAL as capabilities
land; `CANONICAL` is claimed only when a row's conformance is actually
verifiable end to end, which no row meets in this pass. The registry-row,
envelope, join, and conformance columns are filled only where the corresponding
capability has actually landed for that row.

## Ledger

| Spine / capability | Registry row | Envelope | Conformance | State |
| --- | --- | --- | --- | --- |
| Spine Composition Kernel (program capability) | `spine_composition_kernel` (`in_flight`) | common spine envelope (D1) | 14-item contract in-registry + validator; all `open` | PARTIAL |
| spine-registry (program capability) | the canonical registry itself (`spine-registry.json`, contract v1.0.0) | — (registry plane) | `make spine-registry-check` + byte-stable twins in ci-check | PARTIAL |
| Common spine envelope (program capability) | `common_spine_envelope` (`in_flight`) | `spine-envelope.ts` + `shared/spine/spine_envelope.py` (parity); `identity_watermark` / `rights_decision_ref` `@unpopulated` | envelope shape asserted by parity test | PARTIAL |
| IRRL naming overlay (program capability) | `irrl_naming_overlay` (`in_flight`) | rights fields stay `@unpopulated` | naming overlay reconciles with `DATA_RIGHTS_LEDGER.md`; no parallel rights registry | PARTIAL |
| 14-item conformance contract (program capability) | `spine_conformance_contract` (`in_flight`) | — (gate) | 14 ids are the in-registry conformance vocabulary; `SPINE_P0_CONFORMANCE_CHECKLIST.md` evidence mapping | PARTIAL |
| Contract Spine (Truth Kernel: TS contracts + JSON registries + Pydantic mirrors + generation gates) | `contract_spine` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Platform Authority | `platform_authority` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Identity Resolution | `identity_resolution` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Temporal Kernel | `temporal_kernel` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Evidence / Lineage / Truth-State / Restatement | `evidence_provenance` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Consent / Privacy / Deletion | `consent` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Context Capsule | `context_capsule` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Graph Mutation / State Transition / History | `graph` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Relational Intelligence / Relationship Fidelity | `relationship_fidelity` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Measurement / Metrics / Algebra | `measurement_outcome_contract` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Attribution architecture | `attribution_architecture` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Lens / Projection Algebra + Exploration Fabric | `exploration_fabric` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| 360 projections | `projection_plane` (`in_flight`, 19 projections) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| ML / model contracts | `model_governance` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Universal Provider Runtime | `upr` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Connector Normalization + SDK & Universal Alignment | `connector_normalization` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Computation substrate (shared measurement/computation engine) | `computation_substrate` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Rights / IRRL runtime | `rights_irrl` (`in_flight`) | rights fields `@unpopulated` | 14 `open` in-registry; IRRL overlay reconciles existing names | PARTIAL |
| Findings / Investigations / Decision contracts | `decision_contracts` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Agent / Execution contracts | `agentic_runtime_access` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Product Runtime / Tenant Activation & Readiness | `tenant_readiness` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Kyber (operator control surface) | `kyber` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Aether surfaces / Noesis | `aether_surfaces` (`implemented`) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Infrastructure Model (platform runtime topology/state read by Infrastructure360) | `infrastructure_model` (`implemented`; row added in the re-cut onto the 360 foundation) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Graph History Replay (historical as-of graph reconstruction over the bitemporal mutation ledger, read by temporal360) | `graph_history_replay` (`implemented`; authority = `services/temporal360` history replay over `shared/graph` replay_state — formalized on the re-cut onto origin/main) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Context Capsule Semantics (capsule → canonical-geographic reading rules, read by geographic360) | `context_capsule_semantics` (`implemented`; authority = `services/geographic360` capsule_semantics — formalized on the re-cut onto origin/main) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| Grouping Membership (governed population membership + append-only definition versions, read by population360) | `grouping_membership` (`implemented`; authority = `services/population` membership governor — formalized on the re-cut onto origin/main) | — (shared D1) | 14 `open` in-registry | PARTIAL |
| journey_continuity (pending projection spine) | declared `pending` row (`unresolvedRefs`: reason + resolving milestone) | — | 14 `open` in-registry | LEGACY |
| reconciled_control_plane (pending projection spine) | declared `pending` row (`unresolvedRefs`: reason + resolving milestone) | — | 14 `open` in-registry | LEGACY |

## Notes

- **This ledger is now machine-backed.** Phase 2 landed the canonical
  `spine-registry` and `validate_spine_registry.py`; the table above is the
  human index over its 34 governed rows and is kept in step with it. Rows move
  LEGACY → PARTIAL → CANONICAL only as their conformance evidence actually
  lands (see the dated moves in the [phases-plan ledger](../plans/SPINE_P0_PHASES.md)).
- **`implementationState` ≠ readiness.** A row moving to `CANONICAL` makes no
  `production_ready` claim; readiness is a presentation-only join that never
  emits a certification token (ADR-010 D3, unchanged for spines).
- **No parallel registries.** When a spine row lands it references — never
  re-defines — the registry that owns each id (surface, metric, readiness,
  consent, graph-mutation, evidence, projection, provider …). A row that
  re-defines an id owned elsewhere is a validator failure.
- **`CANONICAL` candidates.** The Phase-7 exit names the strongest authorities
  — the contract-spine kernel, identity resolution, temporal kernel, and
  evidence/provenance — as the first rows that may move to `CANONICAL` once
  their 14 conformance checks carry verified evidence. None do yet; all remain
  `open` in-registry, so no row is declared `CANONICAL` in this pass.
- **Terminology reconciliation** between this document's vocabulary and the
  existing repo (contract spine, hard spines, control spine) is in the
  repo-grounding annex of
  [SPINE_P0_ARCHITECTURE.md](./SPINE_P0_ARCHITECTURE.md).

Related: [SPINE_P0_ARCHITECTURE.md](./SPINE_P0_ARCHITECTURE.md) (architecture
source of truth),
[SPINE_P0_PHASES.md](../plans/SPINE_P0_PHASES.md) (phased program + its own
ledger),
[ADR-011](../decisions/ADR-011-spine-composition-kernel.md) (decision record).
