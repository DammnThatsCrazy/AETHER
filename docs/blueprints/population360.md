---
title: "Population360 Vertical Slice Blueprint"
slug: blueprints/population360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Population360 — Intelligence-Projection Blueprint

**Registry id:** `population360`
**Projection kind:** `context_360`
**Blueprint for:** the registry row's `implementationBlueprint` /
`legacyBindings.migrationBlueprint` — the vertical slice that converges
`population360` to `implementationState: "implemented"`. Executed as **Phase 3**
of [docs/plans/CONTEXTUAL_360_PHASES.md](../plans/CONTEXTUAL_360_PHASES.md)
(per-360 workstreams P3.1–P3.5), then flipped to `implemented` at the phase-3
exit gate.

---

## What it is

Population360 is Aether's **contextual WHO / WHAT SET projection** — a governed,
read-only answer to "who is in this set, how did membership change, and how do
sets overlap and compose?" over `subjectKinds: [entity, population, cluster]`. It
projects `summary`, `state`, `timeline`, `evidence`, and `findings` for a
population definition — and for an entity/cluster, which definitions it belongs
to and with what membership state — through the Intelligence Projection Plane's
shared contracts.

It is NOT a competing population store, NOT a second cohort/segment system, and
NOT a demographics backend. Demographics are a governed **human lens** of this
projection over canonical profile facts — there is **no `Demographic360`** and no
`Spatiotemporal360` (standing rule 6). Membership is a first-class **governed
graph fact**, not a table row: the pending authority this slice resolves is
`grouping_membership`, making membership versioned, bitemporal, evidence-carrying,
consent-gated, and erasure-covered.

The registry names its authorities: `population_definitions`,
`cohort_membership`, `cluster_definitions`, `entities`, `evidence`, `temporal`;
surface ids `comparison_workbench` and `cluster360`; legacy binding `services/population`
(`/v1/population`); `hardDependencies: [contract_spine, grouping_membership]`;
`projectionDependencies: [profile360, relationship360, temporal360]`;
`supportedTemporalModes: [window, relative]`.

## Why

`services/population/` already ships auto-created JSONB tables
(`populations`, `population_memberships`, `population_snapshots`) with bus events
(`ENTITY_MEMBERSHIP_ADDED`) — but membership there is **not** a governed graph
fact (spike §5.4): no Alembic migration, no versioning (idempotent update, hard
delete), no `MEMBER_OF` graph edge, no consent/policy evaluation at write, and no
DSR-component coverage (none of the 26 `DSR_COMPONENTS` touches the population
tables). In repository terms that is an explicit erasure + consent gap, and it
means a population read cannot be trusted the way a graph read is trusted. This
slice converges the surface *and* closes that gap: membership moves onto the
graph as a governed edge fact so that "who/what set" is answerable with the same
evidence, consent, and erasure guarantees as every other canonical fact.

## How it works

### The `grouping_membership` authority (the pending authority this slice resolves)

The row declares a single `pendingAuthority`:

```json
{ "id": "grouping_membership", "kind": "spine",
  "reason": "canonical grouping/membership contract not yet formalized",
  "resolvesInProjection": "population360" }
```

Phase 3 formalizes membership as a first-class graph fact written **through the
graph mutation gateway** — not as a standalone table row:

* **Membership is a `MEMBER_OF` edge with provenance.** Definition version,
  membership state, and evidence refs are carried on the membership
  record/edge vocabulary (`definition_version` immutable, `membership_state`,
  `evidence_refs`), which today the canonical edge property vocabulary does not
  support and which the slice adds in the same phase.
* **Bitemporal close-and-append.** Joins and leaves are appended facts with
  valid-time and knowledge-time (via the gateway ledger), never in-place
  idempotent updates; a membership history is reconstructable.
* **Definition versioning is immutable.** A population definition is a versioned
  contract; recomputing a definition produces a new version and a documented
  transition, never a silent redefinition of the old cohort.
* **Consent is enforced where membership is written** (standing rule 8) — the
  same consent/policy evaluation graph writes receive applies at membership
  compute/write time, not merely a tenant `write` permission.
* **Erasure is not a dead end** (standing rule 7) — the population tables and the
  membership facts gain `DSR_COMPONENT` coverage in `services/dsr_propagation/`
  in this same phase.

The provider projects snapshots, deltas, overlap, transitions, and composition
over that governed membership — never a parallel cohort store. The human
**demographic lens** reads canonical profile facts (via the `profile360`
dependency) with configurable small-cell suppression; suppression is not
marketed as differential privacy.

### Canonical sources (read-only)

| Section | Canonical source read |
|---|---|
| `summary` | subject's population posture: definitions + membership states it participates in, counts, effective temporal mode, freshness |
| `state` | typed `SectionState` per membership/definition dimension — `available`/`missing`/`degraded`/`unknown`/`not_applicable`; a definition with no observation is `unknown`, never a fabricated `0` member count |
| `timeline` | membership join/leave/state-change history with valid interval + knowledge time + `EvidenceRef` per transition |
| `evidence` | the reused `EvidenceRef`s grounding every membership and count claim |
| `findings` | derived findings — definition transitions, membership-state anomalies, overlap surprises, stale definitions — with evidence |

Every read is defensive: an unavailable backing source degrades its section
(typed `degraded`/`missing`/`empty`), never raises, never fabricates, never leaks
exception detail. `requiresEvidence`, `requiresDimensionState`,
`requiresFreshness`, and `requiresLimitations` are honored.

### Dependency story (profile360 / relationship360 / temporal360)

`population360` declares `projectionDependencies: [profile360, relationship360,
temporal360]`. Sibling rows still `in_flight` compute as `missing` at the registry
level and the provider **degrades honestly**: until `temporal360` lands (Phase 2,
its declared upstream), membership timelines render from live graph truth with
valid-time provenance only (`supportedTemporalModes: [window, relative]`); the
demographic lens lifts when `profile360` lands; relationship-derived cohort
semantics lift when `relationship360` lands. The projection still returns a valid
`ProjectionResult` with `dependencyState` echoed from the registry. Population360
is itself the dependency that `cluster360` (and risk/fraud population subjects)
consume — flipping it raises those surfaces out of `missing`.

### No redefinition

The slice reuses canonical `EntityRef`, `GraphSnapshotRef`, `GraphResult`,
`PageRequest`, `TimeRangeFilter`, and `EvidenceRef`; `services/identity/` remains
the identity authority (population membership never merges/splits identities);
`services/consent/` + `services/dsr_propagation/` remain the consent/erasure
authorities; `shared/temporal/` remains the temporal authority. No second cohort
registry, no fraud-specific population store, no duplicate evidence model.

## What it means for the graph

Population360 projects *over* the graph's membership truth — and, by converging
membership itself onto the graph as a governed edge fact, it makes "who/what
set" **graph-canonical** for the first time: every membership is an evidence-
carrying, bitemporal, consent-gated `MEMBER_OF` edge that DSR can erase and any
projection can replay. The population tables stop being an unversioned side store
and become rebuildable materializations of graph facts. Because the provider is
fail-isolated and order-resilient, it can land before or after `cluster360` /
`profile360` / `relationship360` without corrupting them, and it lifts those
siblings out of `missing` when it does.

## Definition of Done

This slice follows the canonical vertical-slice checklist —
[docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md](../../docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md)
(registry row zero-pending + converged, shared-contract conformance, runtime
provider, evidence, tenant isolation, `read_only` graph policy, targeted tests,
source-linked review, and `make ci-check` green). The `implemented` flip
additionally requires governed membership edges through the gateway (P3.1),
immutable definition versioning + write-time consent (P3.2), `DSR_COMPONENT`
coverage for the population artifacts (P3.3), and the provider + demographic lens
(P3.4) to be live — with the `implemented` flip still carrying **no**
`production_ready` claim.

## Test surface

* Contract tests — membership carries `definition_version` + `membership_state` +
  reused `EvidenceRef`s; a definition with no members renders `unknown`, never a
  fabricated `0`; `extra="forbid"`; no redefinition of canonical primitives.
* Governance tests — membership writes require gateway + consent/policy
  evaluation; a definition version is immutable; hard delete is gone (close-and-
  append supersede only); DSR erasure of a member removes/degrades membership
  facts and table rows and recomputes counts honestly.
* Registry tests — zero-pending once `grouping_membership` resolves, DAG acyclic,
  bindings resolve (`/v1/population`, `comparison_workbench`, `cluster360`),
  order-resilient.
* Provider tests — valid `ProjectionResult` with snapshots/deltas/overlap/
  transitions/composition; missing-dep honest degradation (never raises); tenant
  isolation; registration (success / duplicate / version-mismatch / unknown id).
* Lens tests — demographic lens reads canonical profile facts; small-cell
  suppression is configurable and never labeled differential privacy; no
  `Demographic360` backend exists.
