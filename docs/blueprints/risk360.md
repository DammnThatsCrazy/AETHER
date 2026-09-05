---
title: "Risk360 Vertical Slice Blueprint"
slug: blueprints/risk360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Risk360 — Intelligence-Projection Blueprint

**Registry id:** `risk360`
**Projection kind:** `risk_360`
**Blueprint for:** the registry row's `implementationBlueprint` /
`legacyBindings.migrationBlueprint` — the vertical slice that converges
`risk360` to `implementationState: "implemented"`. Executed as program phases
4–5 of
[docs/plans/RISK_FRAUD_360_PHASES.md](../plans/RISK_FRAUD_360_PHASES.md), then
flipped in the phase-6 gate.

---

## What it is

Risk360 is Aether's **evaluative 360** — a universal contextual risk-assessment
projection over canonical Aether truth, for subjects of kind `entity`,
`relationship`, `cluster`, or `population`. It answers "what could be materially
harmful, abnormal, unstable, compromised, deceptive, or uncertain here, and
why?" by **reading** the canonical risk authorities — risk overlays, agent
capability-risk, trust vectors, fraud decision history, comparison baselines,
cluster membership, economic exposure, the entity graph, and model governance —
and projecting a typed, evidence-grounded, tenant-scoped result through the
Intelligence Projection Plane's shared contracts (`ProjectionRequest` →
`ProjectionResult`).

It is NOT a competing system of record (ADR-010, `ownsCanonicalTruth: false`)
and it is NOT a store of bare scores. It never writes: `graphMutationPolicy:
read_only`; there is no write path at all.

## Why

The backend already ships risk surfaces (`/v1/risk-overlays`, `/v1/capability-risk`)
as mounted routes and services, and risk signal output exists across the fraud
engine, trust scoring, and device/IP enrichment — but nothing states what the
*Risk360 surface* is relative to canonical truth, and there is no single
subject-risk workbench. Without a declared authority boundary and an explicit
epistemic contract, a composite risk read drifts toward a parallel score store
that re-answers questions the canonical planes already answer, and risk numbers
escape the "suspicion is not fact" discipline. This slice lands `risk360` as a
first-class projection: a real provider implementing the
`IntelligenceProjectionProvider` protocol that reads the same canonical sources
the routes already read, fail-isolated, tenant-scoped, and epistemically honest.

## How it works

### Canonical sources (read-only)

| Section | Canonical source read |
|---|---|
| `summary` | risk state for the subject: dimension states, primary drivers, mitigating factors, confidence, freshness — assembled from the sources below through `services/risk_overlay` (overlay graphs) + `services/agent_access_intelligence` (capability-risk findings) + trust vectors |
| `state` | typed `SectionState` per risk dimension — `available`/`missing`/`degraded`/`unknown`/`not_applicable`; a dimension with no observation is `unknown`, never `0` |
| `evidence` | the reused `EvidenceRef`s grounding every claim |
| `findings` | risk finding candidates passing materiality; degraded honestly until the findings path (program phase 6) is live |
| `health` | detector/baseline freshness for the contributing signal sources; degraded honestly when a source is flag-gated off |

Every read is defensive: an unavailable backing source degrades its section
(typed `degraded`/`missing`/`empty`), never crashes, never fabricates, and never
leaks exception detail. `requiresDimensionState`, `requiresFreshness`, and
`requiresLimitations` are honored — a Risk360 result without dimension state,
freshness, and limitations is incomplete.

### Epistemic honesty (the no-silent-escalation rule)

- Every claim in the result carries a claim state from the consolidated
  `EpistemicStatus` vocabulary, a confidence, and reused `EvidenceRef`s.
  An ungrounded claim is a typed `missing`/`degraded` state, never a silent
  assertion (vertical-slice checklist §7).
- Missing dimensions are not zero. `unknown`, `unavailable`, `not_applicable`,
  `suppressed` are legal and rendered as such.
- There is **no unexplained traffic-light badge**: `summary` risk state is
  derived from typed dimension states and never implies factual certainty about
  a subject.
- Policy thresholds live in policies, never as service constants. The same
  RiskVector projects differently under different `DecisionPolicy` contexts —
  a single raw score has no universal meaning.

### Dependency story (profile360 / economic360 / cluster360)

`risk360` declares `projectionDependencies: [profile360, economic360,
cluster360]`. `economic360` is `implemented`; siblings that are still
`in_flight` compute as `missing` at the registry level and the provider
**degrades honestly** instead of failing — e.g. `summary` enrichment from
`profile360` and population context from `cluster360` degrade with a typed
reason until those slices land, while `economic360`-backed exposure reads lift
immediately. The projection still returns a valid `ProjectionResult` with
`dependencyState` echoed verbatim from the registry. When siblings land, the
provider's sections lift to `available` with zero code change. `risk360` is
itself the dependency that gates `fraud360`.

### No redefinition

The slice reuses the canonical `EntityRef`, `RelationshipRef`, `EvidenceRef`,
`PageRequest`, `TimeRangeFilter`, and `FilterExpression` primitives — the risk
package declares NO second copy (parity-tested). `inputRefs` include
`GraphSnapshotRef`, which requires the typed snapshot reference (program phase 2)
before the row can flip to `implemented`.

### Metric absorption

`metricRefs` is empty today. Before the flip, the risk metric set is absorbed
into `metric-registry.json` (and the hand-authored
`shared/measurement/registry.py` mirror) field-for-field — e.g. subject risk
state share, high-risk subject count, estimated exposure, detector health
freshness — clearing any `pendingReference` rows whose
`resolvesInProjection` is `risk360`, and the provider surfaces them in `summary`
metrics. `campaign_cac`-style honestly-missing metrics stay `missing`, never `0`.

### Zero-pending declaration

With pending references cleared and no `pendingAuthority`, `risk360` becomes a
**zero-pending** row eligible for `implementationState: "implemented"` and
`legacyBindings.migrationMode: "converged"` once the orchestrator flips it.
`ownsCanonicalTruth` stays structurally `false`.

## What it means for the graph

Risk360 projects *over* the graph's risk-relevant truth — entity graph, cluster
membership, economic facts, evidence, model governance — and never writes to it.
The graph remains the single system of record; the projection is a read-only
lens that can be run, degraded, or rebuilt without touching canonical state.
Because the provider is fail-isolated and order-resilient, it can land before or
after profile360 / cluster360 without corrupting them, and it lifts to full
`available` automatically when those sibling projections land. Fraud360's
dependence on Risk360 means flipping `risk360` first raises `fraud360` out of
`missing` dependency state.

## Definition of Done

This slice follows the canonical vertical-slice checklist —
`docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`
(registry row zero-pending + converged, shared-contract conformance, runtime
provider, evidence, tenant isolation, `read_only` graph policy, targeted tests,
source-linked review, and `make ci-check` green). Because the convergence spans
program phases, the `implemented` flip additionally requires the consolidated
`EpistemicStatus` vocabulary and typed `GraphSnapshotRef` (phase 2), the domain
contracts and metric absorption (phase 3), and a real signal→assessment
pipeline (phase 5).

## Test surface

* Contract tests — risk signals/assessments carry claim state + confidence +
  evidence; missing dimensions are never zeroed; `extra="forbid"`;
  no-redefinition of canonical primitives.
* Registry tests — zero-pending, DAG acyclic, bindings resolve, order-resilient.
* Provider tests — valid `ProjectionResult` with typed sections and
  evidence-grounded claims; missing-dep honest degradation (never raises);
  content-free degradation; tenant isolation; registration (success / duplicate
  / version-mismatch / unknown id).
* Epistemic tests — a `derived`/`inferred` risk condition can never surface as a
  factual claim; no unexplained traffic-light rendering.
* Policy-projection tests — the same RiskVector under different `DecisionPolicy`
  contexts yields the documented different projections; determinism + run
  reproducibility on `computation_runs`.
