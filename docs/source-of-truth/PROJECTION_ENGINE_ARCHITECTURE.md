---
title: Projection Engine Architecture
slug: source-of-truth/projection-engine-architecture
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/lens-registry.json
  - Backend Architecture/aether-backend/shared/projection_engine/__init__.py
  - Backend Architecture/aether-backend/shared/projection_engine/compiler.py
  - Backend Architecture/aether-backend/shared/projection_engine/conflict.py
  - Backend Architecture/aether-backend/shared/projection_engine/context_operator.py
  - Backend Architecture/aether-backend/shared/projection_engine/degradation.py
  - Backend Architecture/aether-backend/shared/projection_engine/digest.py
  - Backend Architecture/aether-backend/shared/projection_engine/executor.py
  - Backend Architecture/aether-backend/shared/projection_engine/ir.py
  - Backend Architecture/aether-backend/shared/projection_engine/lens_composition.py
  - Backend Architecture/aether-backend/shared/projection_engine/lens_registry.py
  - Backend Architecture/aether-backend/shared/projection_engine/lens_set.py
  - Backend Architecture/aether-backend/shared/projection_engine/operators.py
  - Backend Architecture/aether-backend/shared/projection_engine/plan.py
  - Backend Architecture/aether-backend/shared/projection_engine/planner.py
  - Backend Architecture/aether-backend/shared/projection_engine/runtime.py
  - Backend Architecture/aether-backend/shared/projection_engine/temporal_modes.py
  - Backend Architecture/aether-backend/shared/projection_engine/generated_lenses.py
  - packages/shared/intelligence-projection.ts
  - Backend Architecture/aether-backend/shared/intelligence_projections/contracts.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/generated_registry.py
  - scripts/generate_platform_contracts.py
  - scripts/lib/intelligence_projection_validation.py
last_synced_commit: 8bf32a56
---
# Projection Engine Architecture

The projection engine (program slice A8) is the compositional orchestration layer
of the intelligence projection plane. It turns a request + a **lens set** + an
engine **temporal mode** into a scheduled, fail-isolated projection run over the
plane's canonical runtime — and it does so without becoming a competing system
of record.

A 360 is an intelligence projection over canonical Aether truth. The engine
never stores canonical truth, never mutates it, and never re-declares a
canonical primitive. It composes *how to look*, schedules *what to run*, and
degrades *what could not be satisfied* — all typed, deterministic, and
tenant-scoped.

---

## Layering

The engine sits ABOVE the P0 plane and keeps `shared/intelligence_projections/`
pristine as the stable contract boundary:

```
services/exploration ──► ProjectionRuntime ──► ProjectionExecutor
                                                 │ compile → plan → run
                              ┌──────────────────┴───────────────────┐
                        ProjectionCompiler                     ProviderRegistry (P0)
                        ProjectionPlanner                      └─ 18 projection providers
                        ProjectionIR / ProjectionPlan
                        LensRegistry / LensSet / compose_lenses
                        ProjectionDegradation / digest / G @ C
```

- **P0 plane (stable boundary):** `ProjectionRequest` / `ProjectionContext` /
  `ProjectionResult`, `ProjectionContract` (`extra="forbid"`), the
  `IntelligenceProjectionProvider` Protocol, and the fail-isolated
  `ProviderRegistry`. The engine never widens this boundary; it extends the
  contracts with **strictly optional** fields (see below).
- **Engine (this doc):** lenses + composition algebra, the temporal-mode
  vocabulary, IR/compiler/planner/executor, typed degradation, deterministic
  digest, and the `G @ C` context operator.

## Why a separate layer?

The P0 plane establishes *which projections exist* and *how a provider is
called* — deliberately minimal. The engine adds the *composition* the 360
blueprints call for: a lens frame (which viewing angles apply), a temporal
frame (which mode the projection runs in), dependency-aware scheduling, and a
content digest that makes projections reproducible. Keeping the two layers
separate means the plane stays the stable contract boundary while the engine
can evolve its algebra without touching provider contracts.

---

## The lens registry

The canonical lens definitions live in
`packages/shared/contracts/lens-registry.json` (day-1: **28 lenses** — one
default base `standard` + 27 overlays). The generator emits three twins:
`packages/shared/lenses_generated.ts`, `.../shared/projection_engine/generated_lenses.py`
and `docs/_generated/lens-registry-table.md` — so the typed vocabulary can never
drift from the JSON.

```jsonc
{
  "contractVersion": "1.0.0",
  "lensKinds": ["base", "overlay"],
  "lenses": [
    {
      "id": "standard", "kind": "base", "baseLens": null,
      "applicableSubjectKinds": ["..."], "temporalModes": ["window", "as_of", "compare", "relative"],
      "default": true
    },
    { "id": "economic", "kind": "overlay", "baseLens": "standard", "default": false, ... }
  ]
}
```

Every overlay declares its `baseLens`; the validator (`rule group
lens_registry`) enforces: unique lower-snake ids, kind ∈ `{base, overlay}` and
within `lensKinds`, an overlay's `baseLens` resolves to a DIFFERENT lens, a
base declares `baseLens: null`, and **exactly one** lens is `default: true`
(and it is a base).

### Lens kinds

| Kind | Meaning |
|---|---|
| `base` | A self-standing viewing frame; composes with any overlays. `standard` is the default base (identity element of composition). |
| `overlay` | A domain/capability viewing angle that composes ON a base lens. |

### Lens domains (day-1 overlays)

temporal, geographic, population, relationship, episode, journey,
communication, campaign, attribution, economic, outcome, infrastructure,
agent, execution, risk, fraud, trust, consent, policy, wallet, payment,
source, evidence, data_quality, operational, deployment, security.

---

## Lens sets and the composition algebra

A `LensSet(base_lens, overlays)` is the frame a projection runs under. It is
built from a request's optional `lensIds` via `LensSet.from_request`:

* `None` / empty `lensIds` → the default base lens alone (identity).
* A non-base lens listed first → the default base + every listed id as an
  overlay.
* A base lens listed first → that base + the remaining ids as overlays.

`compose_lenses(lens_set, subject_kind, registry)` applies the composition laws:

* **Identity** — composing no overlays yields the base lens alone.
* **Idempotence** — a repeated overlay composes once.
* **Order stability** — overlays compose in registry-declared (id-sorted)
  order regardless of request order, so the same set always produces the same
  composition.
* **Disparate grain** — a lens whose `applicableSubjectKinds` excludes the
  requested subject kind is a `CAPABILITY_MISSING` conflict: it is dropped
  (degraded), never silently merged.

Illegal compositions (unresolvable id, a base composed as an overlay, an
overlay whose base is not the set's base) raise `LensConflict`
(`PARAMETER_CONFLICT`) — those are request bugs, surfaced at compile time.

## Conflict classes and resolutions

`ConflictClass` is the typed vocabulary of "why a lens cannot compose":

| Class | Resolution | When |
|---|---|---|
| `HARD_CONFLICT` | `SUPPRESS_SECTION` | mutually exclusive lenses (day-1 future) |
| `SOFT_CONFLICT` | `DOMINANT_WINS` | overlap resolved by dominance (day-1 future) |
| `PARAMETER_CONFLICT` | `REJECT_AT_COMPILE` | request bug: illegal composition / operator |
| `TEMPORAL_CONFLICT` | `DEGRADE` | a lens cannot honor the requested temporal mode |
| `POLICY_CONFLICT` | `SUPPRESS_SECTION` | a policy forbids the lens on this subject (day-1 future) |
| `GRAIN_CONFLICT` | `COARSEST_WINS` | lens grains conflict (day-1 future) |
| `CAPABILITY_MISSING` | `DEGRADE` | subject kind excluded by the lens |

Recoverable conflicts (`TEMPORAL_CONFLICT`, `CAPABILITY_MISSING`) drop the
lens and record it in the IR's `incompatible_lenses` so the executor can
surface the degradation — they never fail the request. A request with NO lens
left that can honor the mode fails closed at compile.

---

## Temporal modes

The engine vocabulary is RICHER than the plane's surface vocab — and it is
deliberately kept off the wire by dispatching onto the four registered surface
modes (`window` / `as_of` / `compare` / `relative`):

| Engine `TemporalMode` | Dispatches to surface |
|---|---|
| `LIVE` | `window` |
| `AS_OF` | `as_of` |
| `KNOWN_THEN` | `as_of` |
| `KNOWN_NOW` | `as_of` |
| `COMPARE` | `compare` |
| `CORRECTION_DIFF` | `compare` |
| `PLAYBACK` | `relative` |
| `SIMULATION` | `relative` |

The `degradation_vocab` validator rule pins the registry `sectionStates` as a
superset of the engine's emittable states (`available`, `empty`, `missing`,
`degraded`, `not_applicable`, `unknown`, `suppressed`, `stale`) so the engine
can never invent a parallel section-state vocabulary.

---

## IR → plan → execute

**`ProjectionCompiler`** (fail-fast): composes the lens set over the subject
kind, applies the temporal-mode fit (dropping unsupported lenses as
`TEMPORAL_CONFLICT`), validates operator legality for the projection kind, and
produces an immutable `ProjectionIR`.

**`ProjectionPlanner`**: walks the registry's dependency DAG and schedules the
target + every reachable hard dependency, dependency-first (topological).
A dependency with no registered provider is never scheduled — it is recorded in
`dependencies_missing` (fail-closed). A missing TARGET schedules nothing and
degrades.

**`ProjectionExecutor`**: for each plan node, builds a P0 `ProjectionRequest`
and calls `ProviderRegistry.project(...)`, inheriting the plane's
fail-isolation. Only the target node carries the composed `lensIds` + the
dispatched surface `temporalMode`; dependency nodes run tenant-scoped but
lens-free. The executor reassembles the engine-level `ProjectionResult`:
composed lens ids, dispatched temporal mode, a deterministic digest, typed
degradation and suppressed sections.

**`ProjectionRuntime`**: the single facade — `compile → plan → execute`
behind one method (`execute_projection`), with the engine's lens-set and
temporal-mode helpers exposed for the service layer.

## Digests

`compute_projection_digest` is a deterministic sha256 over the CANONICAL
serialization of a result's content — projection id, tenant id, subject,
as-of, sections, claims, dependency state, lens ids and temporal mode —
sort-keyed with minimal separators. `generatedAt` and `page` are deliberately
excluded: a digest must be stable across reruns of the same content, which is
what makes it usable for cache-keying and drift detection.

## Typed degradation

`ProjectionDegradation` (an A8-optional field on `ProjectionResult`) carries
`level` (`none` / `partial` / `full`), content-free `reasons`,
`conflictedLenses`, and `missingDependencies`:

* **none** — every requested section available, no failure signal.
* **full** — the target itself failed: no sections produced while a failure
  signal exists, or every section is suppressed/degraded.
* **partial** — anything in between (a dropped lens, a missing dependency, a
  provider-degraded section).

Reasons are engine-computed and NEVER echo a provider diagnostic — a degraded
result stays content-free with respect to provider messages (fail-closed
secret hygiene, mirroring the runtime registry).

## The context operator — `G @ C`

`ContextOperator.apply(request, lens_set=...)` is the pure functional transform
that applies a lens frame / engine temporal mode to a request, yielding a
FRESH request. It never mutates the caller's request and never widens tenant
scope (tenant id is server-authoritative). Operations: `SET_TEMPORAL`,
`SET_SUBJECT`, `ADD_LENS`, `REMOVE_LENS`, `SET_PAGE`, `SET_SECTIONS`.

---

## Contract extension (backward compatible)

The engine extends the P0 contracts with STRICTLY OPTIONAL fields so a minimal
construction stays valid under `extra="forbid"`:

* `ProjectionRequest` — optional `lensIds: string[]`, `temporalMode: string`
  (surface modes only).
* `ProjectionResult` — optional `digest`, `lensIds`, `temporalMode`,
  `degradation: ProjectionDegradation`, `suppressedSections: string[]`.
* New model `ProjectionDegradation`.

Mirrors exist in `packages/shared/intelligence-projection.ts` (parity gate).
The richer engine `TemporalMode` enum never leaks into the wire contract.

---

## Security invariants

* **Tenant scope is server-authoritative** — the engine carries the request's
  tenant id through every sub-request and never widens it.
* **Fail-isolated runtime** — provider failures (any exception) degrade the
  node; they never take down the plane or the engine.
* **Content-free degradation** — degraded `reasons`/`degradedReasons` are
  engine-computed or exception-class names only; provider messages never
  surface.
* **Read-only by doctrine** — the engine has no write path; projections read
  canonical truth and project.
* **No redefinition** — the engine reuses `ProjectionSubject`, `PageRequest`,
  `TimeRangeFilter`, `EvidenceRef` and the section-state/kind vocabularies; it
  never re-declares a canonical primitive.

---

## Relationships

* **Registry**: `packages/shared/contracts/intelligence-projection-registry.json`
  (18 projections) and `packages/shared/contracts/lens-registry.json` (28 lenses)
  are both generated with order-stable emission (see
  [generated docs rule](../REPO-INDEX.md)).
* **Doctrine**: ADR-010 — a 360 is an intelligence projection over canonical
  Aether truth, never a competing system of record.
* **Checklist**: `INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md` — the
  vertical-slice DoD the engine-backed 360s converge on.
