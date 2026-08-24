---
title: "Outcome360 Vertical Slice Blueprint"
slug: blueprints/outcome360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Outcome360 — Intelligence Projection Vertical Slice

**Projection id**: `outcome360` · **Kind**: `measurement_360` ·
**Graph mutation policy**: `read_only` · **`ownsCanonicalTruth`**: `false`

The Outcome360 blueprint implements the `outcome360` row of
`packages/shared/contracts/intelligence-projection-registry.json` as a full
vertical slice: canonical outcome-domain contracts, the canonical outcome-type
vocabulary registry, a runtime provider implementing the projection Protocol,
and the test coverage that makes the row's `implemented` claim honest.

Definition of Done is the shared
[Intelligence Projection Vertical Slice Checklist](../../source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md)
— **this slice converges the row, it does not claim production readiness**
(`implementationState` is repo metadata, never readiness).

## What this is

A **360 is an intelligence projection over canonical Aether truth — never a
competing system of record** (ADR-010). Outcome360 is the projection that
answers: *"what is the attested outcome state of this campaign / episode /
population, what does the evidence say, and how did those outcomes reach that
state?"*

It does **not** re-implement measurement. Achievement truth stays with the
measurement engine (journey compiler, gold materializer,
`services/measurement/contracts.py`). Outcome360 reads canonical
`outcome_facts` / `measurement_contract` and projects them into the five
registered output sections:

| Section | What it renders |
|---|---|
| `summary` | Subject, outcome count, state distribution, effective temporal mode |
| `state` | `OutcomeState` distribution across the subject's outcome rows |
| `evidence` | Deduplicated `EvidenceRef`s grounding every outcome row |
| `outcomes` | The canonical `Outcome` rows, tenant-scoped |
| `findings` | Derived findings (e.g. `journey_completion_rate`) with evidence |

## Why

The eighteen 360 surfaces shipped as ad-hoc composites with no declared
authority boundary. Outcome360 is one of the first real providers on the
projection plane: it gives the measurement domain a typed, evidence-grounded,
tenant-scoped answer surface while proving the plane's order-resilience
contract (a follow-up projection may land before or after any other without
corrupting previously-placed work).

## How it works

### Canonical outcome domain contracts (`services/measurement/outcome/contracts.py`)

The OutcomeState **finality ladder** and its **legality table** are the spine of
the domain vocabulary:

```
            PROVISIONAL ──► REVERSIBLE ──► CONDITIONALLY_FINAL ──► FINAL
                ▲             │                  │                    │
                └─────────────┘                  └──────────┬─────────┘
                                                           ▼
                                                       SUPERSEDED   (terminal sink,
                                                                     explicit superseding
                                                                     transition only)
```

The legality table (`OUTCOME_STATE_TRANSITIONS`) enforces:

* `FINAL` may transition only to `SUPERSEDED` — **never** back to
  `PROVISIONAL` or `REVERSIBLE` (those paths are ILLEGAL and rejected by the
  transition validator).
* `CONDITIONALLY_FINAL` may transition to `FINAL` or `SUPERSEDED` — also never
  backward.
* Leaving a finality position (`FINAL`, `CONDITIONALLY_FINAL`) for `SUPERSEDED`
  requires an **explicit superseding transition** (`OutcomeTransition.superseding=True`).
* `SUPERSEDED` is terminal; `UNKNOWN` is the unclassified fallback that may be
  reclassified onto any ladder position.

Enforcement is two-layered: the `OutcomeTransition` model validator rejects an
illegal pair at construction, and `apply_transition(outcome, transition)` (a
pure function — the projection plane is read-only) additionally requires the
transition's `from_state` to match the row's current state before returning a
new `Outcome`.

The contracts **reuse** the canonical `EvidenceRef`, `PageRequest` and
`TimeRangeFilter` from `services/operational_intelligence/models.py` — the
slice declares no second copy of any canonical primitive (parity-tested).

### Canonical outcome-type vocabulary (`packages/shared/contracts/outcome-type-registry.json`)

Sixteen outcome types spanning all nine domains (commercial, product,
operational, agentic, security, fraud, economic, institutional, onchain), ids
unique lower-snake and sorted for order-stability. This file is the canonical
source; the generated twins
(`packages/shared/outcome-types_generated.ts`,
`Backend Architecture/aether-backend/shared/measurement/generated_outcome_types.py`,
`docs/_generated/outcome-type-registry-table.md`) are produced from it by the
platform contract generator after the slice lands.

`services/measurement/outcome/registry.py` consumes the JSON **directly by
repo-root-relative path** (the same pattern as
`scripts/lib/intelligence_projection_validation.load_context()`), never a
generated twin, and fails closed at load on an unknown domain, a duplicate /
non-lower-snake id, or a malformed entry.

### Runtime provider (`services/measurement/outcome/provider.py`)

`Outcome360Provider` implements the `IntelligenceProjectionProvider` Protocol
(`projection_id = "outcome360"`, `contract_version` = the exact
`INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION`). Registration is explicit
(`register_provider(registry)` on a fresh `ProviderRegistry`); it is
deliberately NOT auto-registered on the global registry at import time.

Tenant scope is server-authoritative: every outcome row the provider touches
carries `request.tenantId`, and the provider derives everything from that id —
tenant A can never see tenant B's outcomes or evidence (tenant-isolation
tested). The provider reads canonical truth through a narrow
`OutcomeStore` read surface; the default backing is a defensive import of the
measurement engine that degrades to a typed `missing` section when unavailable
— it never crashes the plane.

### Dependency story — `temporal360` is still `in_flight`

The registry row declares `projectionDependencies: [temporal360]`. Until a
`temporal360` provider lands, `build_context` records that dependency as
`missing` in `dependencyState`, and Outcome360 projects normally:

* `request.temporalMode == "compare"` **degrades to `window`** with a typed
  warning (never a raise, never a silent change).
* The result's `dependencyState` keeps the `temporal360` entry visible so the
  caller knows exactly what degraded.
* When `temporal360` lands, the dependency entry flips to `available` with zero
  provider changes — the plane is order-resilient by construction.

## What it means for the graph

* Outcome360 is a **pure read** (`graphMutationPolicy: read_only`); it has no
  write path and never mutates canonical state.
* Every claim carries a reused `EvidenceRef` (`requiresEvidence: true`); an
  ungrounded claim is a typed `missing`/`degraded` state, never a silent
  assertion.
* The `journey_completion` outcome type is the canonical anchor for the
  registered `journey_completion_rate` metric ref — the provider derives the
  rate from the outcome rows it reads, never from a parallel store.
* `ownsCanonicalTruth: false` is structurally enforced — this projection cannot
  become a competing system of record.

## Convergence state

* **Zero pending** — `pendingAuthority: []`, `pendingReference: []` (already
  holds at `in_flight`).
* **`implemented`** — the row flips `implementationState` to `implemented` and
  `legacyBindings.migrationMode` to `converged`; the legacy `/v1/measurement`,
  `/v1/journeys`, `/v1/conversions`, `/v1/attribution`, `/v1/spend`,
  `/v1/resolution` bindings resolve to the existing measurement service.
* Flipping to `implemented` makes **no** `production_ready` claim.

## Files

* `Backend Architecture/aether-backend/services/measurement/outcome/__init__.py`
* `Backend Architecture/aether-backend/services/measurement/outcome/contracts.py`
* `Backend Architecture/aether-backend/services/measurement/outcome/registry.py`
* `Backend Architecture/aether-backend/services/measurement/outcome/provider.py`
* `packages/shared/contracts/outcome-type-registry.json`
* `Backend Architecture/aether-backend/tests/unit/test_outcome_contracts.py`
* `Backend Architecture/aether-backend/tests/unit/test_outcome360_registry.py`
* `Backend Architecture/aether-backend/tests/unit/test_outcome360_provider.py`
* `docs/blueprints/outcome360.md` (this blueprint)
