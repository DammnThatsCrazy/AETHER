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
graph fact**, not a table row: this slice resolves the `grouping_membership`
authority (P3.1–P3.3), making membership versioned, bitemporal, evidence-carrying,
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

### The `grouping_membership` authority (resolved by this slice)

The row declared `hardDependencies: [contract_spine, grouping_membership]` and a
single `pendingAuthority` — `grouping_membership` began as that declaration:

```json
{ "id": "grouping_membership", "kind": "spine",
  "reason": "canonical grouping/membership contract not yet formalized",
  "resolvesInProjection": "population360" }
```

Phase 3 resolves that authority by converging membership onto the graph as a
first-class governed fact written **through the graph mutation gateway** — not a
standalone table row:

* **Membership is a `MEMBER_OF` edge with provenance.** Every join writes a
  `MEMBER_OF` edge (`entity -> population`) through `GraphMutationGateway`, and a
  leave is a soft-revoke (`edge_expired`), never a hard delete. Membership
  provenance keys — `definition_version`, `membership_state`, `membership_basis`,
  `population_type`, `evidence_refs` — ride on both the edge and the ledger
  record via the canonical optional-edge vocabulary
  (`services/population/governance.py` `PopulationMembershipGovernor` +
  `shared/graph/edge_properties.py`). The `population_memberships` table row is
  only the current-state materialisation the governed path maintains.
* **Close-and-append.** Joins and leaves are appended facts through the gateway
  ledger, never in-place idempotent updates; reads surface active memberships
  only (`MembershipRepository.count_active_members` /
  `active_memberships_for_subject`).
* **Definition versioning is immutable.** A population definition is a versioned
  contract: `PopulationDefinitionRepository` maintains an append-only
  `population_definition_versions` ledger with a deterministic per-version id
  (a version publishes at most once), and `revise_definition` is the only
  definition-change path — it refuses an identical no-op revision and advances
  the current projection only through a documented, supersedes-chained version
  (`services/population/registry.py`).
* **Consent is enforced where membership is written** (standing rule 8) — the
  governor evaluates consent for the member subject under the population's
  declared `consent_purpose` before any edge/row/ledger write; a denial raises
  `MembershipConsentDeniedError` and the batch route preflights the whole cohort
  so no partial join lands. A leave is always honored (a revoked subject can
  still exit a cohort).
* **Erasure is not a dead end** (standing rule 7) — the population artifacts
  gained `DSR_COMPONENT` coverage (`population_memberships`,
  `population_snapshots`, `populations`; `services/dsr_propagation/models.py`
  26 -> 29), and the consent erasure handler executes a **governed leave** for
  every active membership the subject holds and recomputes each affected
  population's materialised `member_count` from active memberships
  (`services/consent/erasure_jobs.py`).
* **Tenant isolation on every route** — every group-by-id population route
  resolves through a tenant-ownership guard (404 on foreign-or-missing ids),
  matching the campaign/entities guard (`services/population/routes.py`).

At P3.5 the row's `pendingAuthority` is emptied and `grouping_membership` is
formalized into the validator `SPINE_INDEX`, so the now-zero-pending row's
`hardDependency` still resolves — the designed spine-formalization step
(mirroring `graph_history_replay` at T2.4), not a validator weakening.

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
temporal360]`. Sibling rows compute as `missing` at the registry level while
`in_flight`, and the provider **degrades honestly** and never fabricates a
dependency it does not have:

* `temporal360` has landed (Phase 2, now `implemented`), so the temporal
  dependency reads live and its `dependencyState` is no longer `missing`.
  population360's own `supportedTemporalModes` stay `[window, relative]` — the
  provider renders those from governed membership current state and the
  snapshot history directly, and deliberately does **not** perform knowledge-time
  reconstruction (that belongs to the `temporal360` dep, which only projections
  declaring `as_of`/`known_then` modes consume).
* `profile360` remains `in_flight`, so the human **demographic lens** degrades to
  a typed `missing` state until canonical profile facts exist — it lifts when
  `profile360` lands and is never fabricated meanwhile.
* `relationship360` remains `in_flight`; relationship-derived cohort semantics
  degrade honestly until it lands.

The projection still returns a valid `ProjectionResult` with `dependencyState`
echoed from the registry. Population360 is itself the dependency that
`cluster360` (and risk/fraud population subjects) consume — flipping it raises
those surfaces out of `missing`.

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
source-linked review, and `make ci-check` green). The `implemented` flip is
gated on the prerequisites having **shipped**: governed membership edges through
the gateway (P3.1), immutable definition versioning + write-time consent (P3.2),
`DSR_COMPONENT` coverage for the population artifacts (P3.3), and the provider +
demographic lens (P3.4) — with the `implemented` flip still carrying **no**
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
