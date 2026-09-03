---
title: "Temporal360 Vertical Slice Blueprint"
slug: blueprints/temporal360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Temporal360 — Intelligence-Projection Blueprint

**Registry id:** `temporal360`
**Projection kind:** `context_360`
**Blueprint for:** the registry row's `implementationBlueprint` /
`legacyBindings.migrationBlueprint` — the vertical slice that converges
`temporal360` to `implementationState: "implemented"`. Executed as **Phase 2** of
[docs/plans/CONTEXTUAL_360_PHASES.md](../plans/CONTEXTUAL_360_PHASES.md) (per-360
workstreams T2.1–T2.4), then flipped to `implemented` at the phase-2 exit gate.

---

## What it is

Temporal360 is Aether's **contextual time projection** — a governed, read-only
answer to the two time questions the graph stores separately but has never
served as one surface:

1. **Valid time — "what was true of this subject during window W?"** Replay the
   subject's canonical facts over their validity intervals.
2. **Knowledge time — "what did Aether know, and when did it know it?"** —
   reconstruct the state of a subject as it was **known at a given instant**,
   so that *"as known then"* (`KNOWN_THEN`) and *"as known now"* (`KNOWN_NOW`,
   after corrections) are both first-class, honest answers.

It is registered on the Intelligence Projection Registry
([intelligence-projection-registry.json](../../packages/shared/contracts/intelligence-projection-registry.json))
for `subjectKinds: [entity, relationship]`, projecting `summary`, `state`,
`timeline`, `evidence`, and `findings` sections under `graphMutationPolicy:
read_only` with `ownsCanonicalTruth: false`. It has **no** `projectionDependencies`
— it is the root of the contextual cluster — yet `outcome360`, `relationship360`,
`execution360`, `geographic360`, and `population360` all declare it as a
dependency, so landing it lifts those rows out of `missing` dependency state.

It is NOT a new clock, calendar, parser, or history store. `shared/temporal/`
is the sole temporal kernel; the bitemporal ledger is the record. Temporal360
is a **read-side authority** that answers over those canonical sources.

## Why

The repository already keeps two kinds of temporal truth — the bitemporal
close-and-append ledger (`graph_fact_versions`, `graph_mutation_ledger.py`) and
valid-time as-of query over the live graph (`temporal_bfs`, `/v1/graph/compare`,
universal-query `as_of`) — but nothing serves the *"what did we know at decision
time τ"* question that compliance, re-attribution, fraud reconstruction, and
every sibling 360 need. `KNOWN_THEN`/`KNOWN_NOW` exist as enum values in the
projection engine with no reconstruction authority behind them, and
`replay_ledger`/`current_graph_digest` are digest-only (sha256 parity), not
state reconstruction. Without this slice, a knowledge-time answer silently
collapses into a valid-time/live answer — which is exactly the epistemic
confusion the plane exists to prevent.

This slice lands `temporal360` as a first-class projection: a real provider
implementing the `IntelligenceProjectionProvider` protocol, backed by the
newly-built `graph_history_replay` authority, tenant-scoped and evidence-
grounded.

## How it works

### Canonical sources (read-only)

| Section | Canonical source read |
|---|---|
| `summary` | subject's temporal posture: first/last known activity in window, correction count, gap/staleness state, effective mode, freshness — assembled from the sources below |
| `state` | typed `SectionState` per temporal dimension — `available`/`missing`/`degraded`/`unknown`/`not_applicable`; a window with no observation is `unknown`, never empty-by-omission |
| `timeline` | the canonical output: ordered subject events/transitions, each with valid interval, knowledge time, source fact version, and `EvidenceRef` |
| `evidence` | the reused `EvidenceRef`s grounding every timeline entry and state claim |
| `findings` | derived findings — correction/supersession events, staleness gaps, validity gaps, mode-degradation notices — with evidence |

Every read is defensive: a backing authority that is not yet available degrades
its section (typed `degraded`/`missing`/`empty`) or its temporal mode, never
raises, never fabricates, and never leaks exception detail. `requiresEvidence`,
`requiresDimensionState`, `requiresFreshness`, and `requiresLimitations` are
honored — a Temporal360 result without evidence-grounding, dimension state,
freshness, and limitations is incomplete.

### The `graph_history_replay` authority (the pending authority this slice resolves)

The row declares `hardDependencies: [contract_spine, graph_history_replay]` and a
single `pendingAuthority`:

```json
{ "id": "graph_history_replay", "kind": "spine",
  "reason": "bitemporal ledger exists; graph-history replay API not yet built",
  "resolvesInProjection": "temporal360" }
```

Phase 2 builds that authority as a **read-side reconstruction** from the
append-only ledger + `graph_fact_versions` (extending `services/operational_intelligence`
and `shared/graph/traversal.py`), so that for any knowledge instant τ the slice
can answer:

* **As of τ (live-valid)** — facts whose validity interval covers τ, read from
  the current graph (already exists via `temporal_bfs` / `as_of`).
* **Known at τ (knowledge/system time)** — the ledger prefix closed at τ,
  replayed to rebuild the graph state Aether actually had at τ
  (`KNOWN_THEN`). This is the genuinely new reconstruction.
* **Known now vs known then** — `KNOWN_NOW` (post-correction state) diffed
  against `KNOWN_THEN` (state at decision time) to surface corrections,
  supersessions, and late-arrival facts (`COMPARE`/`CORRECTION_DIFF`
  semantics) without ever mutating the ledger.

`replay_ledger` stays append-only and digest-verifiable; reconstruction is a
pure read that may be cached by digest and never writes canonical state. The
surface modes the row declares — `window`, `as_of`, `compare`, `relative` —
map onto the engine's `TemporalMode` vocabulary (`LIVE/AS_OF/KNOWN_THEN/
KNOWN_NOW/COMPARE/...`). Until the authority lands, modes that require
reconstruction degrade honestly to live/valid-time with a typed warning; they
never silently relabel.

### No redefinition (do-not-duplicate boundaries)

Temporal360 reuses the canonical `TimeRangeFilter`, `GraphSnapshotRef`,
`GraphResult`, `PageRequest`, and `EvidenceRef` — it declares **no** second copy
(parity-tested). And it must not become a second temporal engine:

* `shared/temporal/` + `packages/shared/temporal.ts` — the **only** temporal
  parser/calendar authority (instants, IANA zones, clocks, DST windows,
  bitemporal `TemporalEnvelope`). No new parser.
* `services/temporal_preferences/` — display preferences, not truth. Temporal360
  renders facts, it does not host UI prefs.
* `shared/projection_engine/temporal_modes.py` — the `TemporalMode` *vocabulary*;
  Temporal360 is a consumer/provider of modes, never a re-declaration.

Bitemporal facts keep flowing only through the graph mutation gateway's
close-and-append; Temporal360 has no write path.

### Dependency story (the leaf that lifts siblings)

`projectionDependencies: []` and `hardDependencies` are only the spine +
replay authority. Temporal360 therefore computes independently of the other 360s
and is order-resilient: it can land before or after `outcome360`/`geographic360`/
`population360` without corrupting them, and each sibling's `temporal360`
dependency entry flips from `missing` to `available` the moment this row lands —
with **zero** code change on the sibling side. `geographic360` and
`population360` both gate their flips on Phase 2 for exactly this reason.

## What it means for the graph

Temporal360 is a **pure read** over the graph's bitemporal truth. It never
writes canonical state, never rewrites history, and never merges the two clocks
into one timestamp. "When it happened" (valid) and "when Aether knew" (system)
stay distinct and both reachable — the graph remains the single system of
record, and a correction is visible as a fact *and* as a correction event, never
as a silent rewrite. Because the authority is reconstruction-by-digest over an
append-only ledger, a Temporal360 answer is reproducible and auditable: given
the same ledger prefix and τ, it returns the same state.

## Definition of Done

This slice follows the canonical vertical-slice checklist —
[docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md](../../docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md)
(registry row zero-pending + converged, shared-contract conformance, runtime
provider, evidence, tenant isolation, `read_only` graph policy, targeted tests,
source-linked review, and `make ci-check` green). The `implemented` flip
additionally requires the `graph_history_replay` authority to actually serve a
knowledge-time reconstruction (workstream T2.1) before the provider can claim
`KNOWN_THEN`/`KNOWN_NOW` answers. Flipping to `implemented` makes **no**
`production_ready` claim.

## Test surface

* Contract tests — timeline entries carry valid interval + knowledge time +
  reused `EvidenceRef`; `unknown` windows never render as `0`/`empty`;
  `extra="forbid"`; no redefinition of `TimeRangeFilter`/`GraphSnapshotRef`.
* Replay-authority tests — knowledge-time reconstruction matches the ledger
  prefix at τ; `KNOWN_THEN` vs `KNOWN_NOW` diff surfaces a supersession/correction
  and never mutates the ledger; digest verification holds.
* Registry tests — zero-pending once the authority lands, DAG acyclic (leaf),
  bindings resolve (`/v1/graph`, `/v1/preferences`, `shared/temporal`),
  order-resilient.
* Provider tests — valid `ProjectionResult` with typed sections; unsupported
  mode degrades with a typed warning (never raises, never silent); tenant
  isolation; registration (success / duplicate / version-mismatch / unknown id).
* Surface tests — `temporal360` present in `surface-capability-registry.json` and
  routable on `/v1/explore/query` once the surface block lands.
