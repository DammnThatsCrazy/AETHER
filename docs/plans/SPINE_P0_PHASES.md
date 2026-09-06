---
title: Aether Spine P0 — Phased Implementation Program
slug: plans/spine-p0-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
---

# Aether Spine P0 — Phased Implementation Program

This is the implementation program for the **Aether Spine P0 (Ground Zero
Founding Spine)**: the governing architecture described in
[docs/source-of-truth/SPINE_P0_ARCHITECTURE.md](../source-of-truth/SPINE_P0_ARCHITECTURE.md).
That document is the architecture source of truth — the founding architecture,
filed verbatim, plus its repo-grounding annex. This document records the gap
between the repository and that architecture, orders the work into phases, and
is the ledger for what has shipped.

The program makes every existing and future spine a **governed authority or
cross-cutting control boundary** — no spine is a private platform inside the
platform — by implementing the **Spine Composition Kernel inside the existing
Contract Spine**: a canonical `spine-registry` that references (never
re-defines) existing registries, a common spine envelope that reuses canonical
primitives, IRRL as a naming overlay on the existing rights machinery, and a
14-item conformance contract enforced by the contract validator. It reuses the
Intelligence Projection Plane's registry/validator machinery (ADR-010), the
generation pipeline (`scripts/generate_platform_contracts.py`), and the repo
doctor CI seam. Phases 1–6 have shipped on the execution lane
`feat/aether-p0-spine-architecture` (2026-09-02 → 2026-09-03); the section-2
phase map shows per-phase status and the section-4 ledger records each landing.
Phase 7 (convergence + release) is this pass: it reconciles the registry-status
ledger and the architecture SOT annex with the shipped registry, runs the final
`make ci-check`, and leaves the branch complete and un-PR'd for the
orchestrator.

Completion of the whole program is gated by the repository's canonical gate
(`make ci-check`), not by this document. The per-spine output ledger lives in
[docs/source-of-truth/SPINE_REGISTRY_STATUS.md](../source-of-truth/SPINE_REGISTRY_STATUS.md).

## 1. Gap analysis

The repository already has a governed contract spine, an intelligence
projection plane with a hard-spine vocabulary (ADR-010), canonical registries,
a rights/data-use layer under non-IRRL names, a readiness vocabulary, and Kyber.
The gaps against the target architecture are the absence of a governing spine
doctrine, a canonical spine registry, a unified spine envelope, IRRL naming,
graph-of-graphs rights filtering, and a spine-wide conformance gate.

| Area | Repository state before this program | Gap to the target architecture |
| --- | --- | --- |
| Spine doctrine | Nothing states what a "spine" is or what a spine PR must declare; the projection plane's hard-spine vocabulary is implicit | **Governing doctrine** — every spine declares ownership, ports, dependencies, mutation policy, degradation, and readiness; no spine is a private platform |
| Spine registry | No canonical spine registry; only the hard-coded `SPINE_INDEX` (13 resolved spines) + five `pendingAuthority {kind:"spine"}` declarations in `scripts/lib/intelligence_projection_validation.py` | **Canonical spine-registry** — one machine-readable registry whose refs resolve against owning registries and which formalizes the five pending spines |
| Common spine envelope | Fragments scattered (`as_of`, `graph_watermark`, `subject_refs`, `scope_ref`, `data_watermark`); no unified envelope; `identity_watermark` / `rights_decision_ref` absent | **Common spine envelope** — one envelope composing canonical primitives, with no-producer fields declared unpopulated |
| IRRL | Rights exist under non-IRRL names (`DataRightsGrant`, `ConsentPolicyDecision`, DSR propagation, storage lifecycle, `DATA_RIGHTS_LEDGER.md`) | **IRRL as naming overlay** — rights/retention/learning become a first-class contractual spine via labeling over existing machinery; no parallel rights registry |
| Graph-of-Graphs rights filtering | Data-use doctrine only (`GRAPH_OF_GRAPHS_DATA_USE.md`, `AETHER_GRAPH_OF_GRAPHS_POLICY_ENABLED`); no rights-filtered intelligence-layer enforcement | **Rights-filtered intelligence** — Olympus/Aether consume only what the rights runtime authorizes (generalized / consented / retained) |
| Conformance gate | Projection vertical-slice checklist precedent (13 items); no spine-wide gate | **14-item spine conformance contract** enforced by the contract validator before any state flip |

## 2. Phase map

Phases are ordered so the registry foundation and envelope land before any
surface join, IRRL labeling, or conformance enforcement. Statuses below are
updated as each phase lands on the execution lane; the ledger in section 4
records the dated result. (Phase 7, the convergence pass, closes out with this
commit.)

| Phase | What ships | Entry criteria | Exit criteria | Status |
| --- | --- | --- | --- | --- |
| **1** — Kickoff docs (C1-DOCS) | ADR-011 (Spine Composition Kernel decision), the Spine P0 architecture source of truth (verbatim + repo-grounding annex), this phased plan, and the per-spine status ledger | Architecture doc reviewed; program scope approved | Four docs present and honest; doc-manifest regenerated; `make ci-check` exits 0 with a clean `git status` | SHIPPED (2026-09-03) |
| **2** — Spine-registry foundation (C1) | `packages/shared/contracts/spine-registry.json` (planes / spine kinds / mutation policies / lifecycle / tenant boundaries / the 14 conformance checks; per-spine rows carrying ownership, read/write authority, contract refs, hard/soft/runtime/policy deps, mutation policy, tenant/rights boundary, lifecycle, readiness key, surfaces/adapters, security/compliance, observability/recovery, conformance gates, implementation state); schema + cross-registry-ref validator (`scripts/lib/spine_registry_validation.py`, `scripts/validate_spine_registry.py`); REGISTRIES-tuple generation of TS/PY/MD twins; parity tests; repo_doctor wiring | Phase 1 landed; registry shape agreed with the projection registry precedent | Validator green; every spine row ref resolves to an existing registry/code path or is declared `pending`; generated twins byte-stable; `make ci-check` green | SHIPPED (2026-09-03) |
| **3** — Common spine envelope (C2) | `packages/shared/spine-envelope.ts` + backend mirror; parity test; envelope composes existing canonical primitives; no-producer fields (`identity_watermark`, `rights_decision_ref`) declared `@unpopulated`; no producers claimed | Phase 2 landed | Parity green; no redefinition of `EntityRef`/`EvidenceRef`/`PageRequest`/temporal envelope/`ContextCapsule` | SHIPPED (2026-09-03) |
| **4** — Surface / readiness / Kyber / projection joins (C3) | Join cross-refs + validator add-on tying spine rows to `surface-capability-registry.json`, `readiness-vocabulary.json` (presentation-only), `kyber-feature-surface-manifest.json`; derive the projection `SPINE_INDEX` from the generated spine twin | Phase 2 landed | Every spine row's readiness key / surfaces / adapters resolve; projection validator still green with the derived index; no parallel readiness/surface registry | SHIPPED (2026-09-03) |
| **5** — IRRL vocabulary / labeling (C4) | IRRL as naming overlay: SOT annex/glossary rows tying `DataRightsGrant` / `ConsentPolicyDecision` / DSR propagation / storage lifecycle / `DATA_RIGHTS_LEDGER.md` to IRRL terms; Rights/IRRL spine row referencing existing rights registries; envelope rights fields still unpopulated | Phase 2 landed | IRRL vocabulary reconciles with `DATA_RIGHTS_LEDGER.md`; validator forbids a parallel rights registry | SHIPPED (2026-09-03) |
| **6** — Conformance gate + DoD (C5) | `SPINE_P0_CONFORMANCE_CHECKLIST.md` mapping the 14 items to concrete evidence; per-row 14-item conformance enforcement before any state flip | Phase 2 landed; checklist evidence scope agreed | A spine row cannot flip state with an open conformance gap; `make ci-check` green | SHIPPED (2026-09-03) |
| **7** — Convergence + release (C6) | Track merges; orchestrator-owned registry row additions; first spine rows declared CANONICAL only where conformance is verifiable (contract spine kernel, identity resolution, temporal kernel, evidence/provenance candidates); ledger/SOT annex updates; `make release-gate` expectations documented | Phases 1–6 landed; at least the strongest authorities verified | Ledger honestly reflects each row; `make ci-check` green; no `production_ready` claim unless the `scripts/production_status.py` scorecard supports it | SHIPPED (2026-09-03) |

### Implementation priority

Registry data comes before envelope; envelope before surface joins; IRRL
labeling and the conformance gate come last.

- **Phase 2 (registry) first** because every later phase consumes the spine id
  vocabulary and the cross-registry ref discipline. Locking refs against owning
  registries before any join avoids a parallel-registry fork.
- **Phase 3 (envelope) before Phase 4 (joins)** because envelope field names are
  what surface/readiness joins will reference; the no-producer discipline must
  be settled before anything claims to populate the envelope.
- **Phase 5 (IRRL) and Phase 6 (conformance) deliberately later.** IRRL is a
  naming overlay on rights machinery that already works; labeling it before the
  registry and envelope exist would create vocabulary without an anchor. The
  conformance gate enforces the architecture and is only meaningful once the
  registry rows exist to be gated. Domain/surface convergence (existing 360s,
  providers, agentic surfaces attaching to spine rows) is a follow-on beyond
  this program's phases, using the same registry rows.

## 4. Ledger

| Date | Phase | Result |
| --- | --- | --- |
| 2026-09-02 | kickoff | Program docs authored (ADR-011, architecture source of truth, this phased plan, per-spine status ledger); implementation starting |
| 2026-09-03 | 1 | Phase 1 gated green on the execution lane `feat/aether-p0-spine-architecture`: `make docs-fix` clean (49/49 gates), `make ci-check` exit 0 (69 gates, 0 failed), `git status` clean. Kickoff docs honest; doc-manifest regenerated at kickoff |
| 2026-09-03 | 2 | Spine-registry foundation gated green on the lane: `packages/shared/contracts/spine-registry.json` (33 governed rows — 21 `implemented`, 7 `in_flight`, 5 declared `pending`; plane/kind/lifecycle/graph-mutation-policy vocab; every non-program row carries its 14 conformance checks, all `open`); validator `scripts/validate_spine_registry.py` (schema, conformance, cross-registry, lifecycle, ownership, inventory — 0 errors on the real registry); generated TS/PY/MD twins (`packages/shared/spine-registry.ts`, `shared/spine/generated_spine_registry.py`, `docs/_generated/spine-registry-table.md`) byte-stable; parity tests; `make spine-registry-check` wired into repo-doctor + an ownership change-category (gate count 69→70). Lane commits 4e1926c2 / 0e31d4a0 / 148520d6 / fa97d881 |
| 2026-09-03 | 3 | Common spine envelope: `packages/shared/spine-envelope.ts` + backend mirror (`Backend Architecture/aether-backend/shared/spine/spine_envelope.py`) + parity test; composes canonical primitives; `identity_watermark` / `rights_decision_ref` declared `@unpopulated`; no producers claimed. Lane commit 4e1926c2 |
| 2026-09-03 | 4 | Surface / readiness / Kyber / projection joins: validator cross-registry rule group resolves every spine row's readiness key / surfaces / adapters against `surface-capability-registry.json`, `readiness-vocabulary.json`, and the kyber feature-surface manifest; the projection plane's `SPINE_INDEX` (28 resolved) and `PENDING_SPINE_INDEX` (5) are now derived from the canonical registry, with an undeclared-pending-spine order-resilience gate. Lane commits 0e31d4a0 / 0bffa736 |
| 2026-09-03 | 5 | IRRL naming overlay: `docs/source-of-truth/IRRL_NAMING_OVERLAY.md` reconciles `DataRightsGrant` / `ConsentPolicyDecision` / DSR propagation / storage lifecycle / `DATA_RIGHTS_LEDGER.md` onto IRRL terms; `rights_irrl` + `irrl_naming_overlay` governed rows reference existing registries; validator forbids a parallel rights registry. Lane commit 4e1926c2 |
| 2026-09-03 | 6 | Conformance gate + DoD: the 14-item conformance vocabulary is the in-registry conformance contract, structurally enforced by `validate_spine_registry.py` (a row cannot flip state with an open conformance gap); `docs/source-of-truth/SPINE_P0_CONFORMANCE_CHECKLIST.md` maps each of the 14 items to concrete evidence. Lane commit 4e1926c2 |
| 2026-09-03 | 7 | Convergence + release: `SPINE_REGISTRY_STATUS.md` ledger reconciled with the shipped registry (governed code authorities LEGACY → PARTIAL; the five pending spines formally declared `pending` rows; no `CANONICAL` — all conformance `open`); architecture SOT annex honesty block updated; final `make ci-check` green (70 gates, 0 failed) on the lane; branch left complete and un-PR'd for the orchestrator |
| 2026-09-03 | re-cut | Phases 1–7 re-cut from the main-based execution lane `feat/aether-p0-spine-architecture` onto the 360-foundation base `feat/aether-360-program` @ `fced2960` as the sibling lane `feat/spine-p0-foundation`. Reconciliation: added `infrastructure_model` (ADR-011 §2 names it among the resolved spines, but the main-based registry lacked the row — registry now 34 governed rows / 22 `implemented` / `SPINE_INDEX` 29 resolved); spine generator + repo-doctor blocks ported additively onto the 360-foundation files (lens/outcome-type registries kept); `repo_consistency_ownership.json` + authored SOT docs merged three-way; generated twins / doc-manifest / REPO-INDEX regenerated. Re-cut gate: spine-registry validator 0 errors (34 rows), projection validator 0 errors (19 projections, 3 implemented), platform-contracts generator idempotent; registry test count updated 33 → 34. The npm-dependent tail of the full gate (`npm ci`/typecheck/test) is deferred to a network-available run |
| 2026-09-05 | re-cut | Phases 1–7 re-cut again onto `origin/main` (`9620539f`) and stacked onto PR #608 (`feat/social360-relationship-fidelity`) as a sibling lane to Social360/Relationship-Fidelity, Risk360/Fraud360, and Universal Financial Normalization. Reconciliation against the newer base: the repo-doctor spine gate (validate_spine_registry dispatch + generated spine twins in the clean-check list) and the projection-plane registry-derived `SPINE_INDEX`/`PENDING_SPINE_INDEX` were merged additively onto main's `readonly_generation_workspace` structure (main's hand-maintained hardcoded index superseded — its resolved ids now resolve against the registry). Registry re-formalization: `graph_history_replay`, `grouping_membership`, and `context_capsule_semantics` moved `pending` → `implemented` (now 25 `implemented`, 7 `in_flight`, 2 `pending`; `SPINE_INDEX` 32 resolved / `PENDING_SPINE_INDEX` 2) because their authorities (`services/temporal360` history replay, `services/population` membership governor + append-only `population_definition_versions`, `services/geographic360` capsule semantics) exist on the new base — a `pending` row pointing at built code is a false claim. Ledger + architecture-SOT + projection-architecture docs updated to the reconciled set; generated twins / doc-manifest / REPO-INDEX regenerated. Python-side verification runs against the combined PR #608 tip |

Each landing above updates the section-2 phase map and moves the corresponding
per-spine rows in `docs/source-of-truth/SPINE_REGISTRY_STATUS.md`
(LEGACY → PARTIAL → CANONICAL; `CANONICAL` only when a row's 14 conformance
checks are verified, which no row meets yet).
