---
title: Reconciled Control Plane — Architecture (§0–40 lane)
slug: architecture/reconciled-control-plane
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/managed_integrations/
  - Backend Architecture/aether-backend/services/kyber/access/
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_managed_integrations.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_change_sets.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_execution.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_admission.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_simulation.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_schema_mapping.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_source_authority.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_rollouts.py
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_fleet_update.py
  - config/route_registry.yaml
  - Backend Architecture/aether-backend/main.py
  - Backend Architecture/aether-backend/config/settings.py
  - packages/shared/managed-integrations.ts
---

# Reconciled Control Plane — Architecture (§0–40 lane)

The **Reconciled Control Plane** is Aether's operational authority that
continuously converges every managed integration — SDKs, connectors, provider
connections, webhooks, imports, curated feeds — toward an authorized, healthy,
supportable desired state: *install once, continuously reconcile*. Its doctrine
is: **the SDK observes; the control plane manages; the backend reasons.**

This page records the architecture of the §0–40 build as it stands after Phases
0–4 landed on the `feat/reconciled-control-plane` lane — the full loop from
drift classification through planning, approval-gated execution, and
progressive delivery — and, just as importantly, the boundary of what the lane
deliberately does **not** do. Phase-by-phase sequencing and evidence live in
[`docs/plans/RECONCILED_CONTROL_PHASES.md`](../plans/RECONCILED_CONTROL_PHASES.md)
and
[`docs/productization/reconciled-control-plane/EXECUTION_STATE.md`](../productization/reconciled-control-plane/EXECUTION_STATE.md).

## Governing spec

The canonical spec is the external *Aether Reconciled Control Plane Blueprint*
(sections 0–40 reviewed at Phase-0 planning time; the §41+ remainder is
reserved and governs day-1 production activation). Vocabulary provenance is
cited inline per symbol. What each phase contributed to the architecture:

| Phase | Architectural contribution |
|---|---|
| 0 | Managed-integration abstraction (§6, CP-12 typed availability), desired-state assembly (§22/§28), evidence-backed observed-state sensors (§24/§15), reconcile **classification** (§32 steps 1–11), durable `managed_integrations` + `reconcile_runs` |
| 1 | ChangeSet **planning**: §33 taxonomy, §34 status vocabulary, §39 risk engine + automation authority, blast-radius over the managed-integration graph, §35 concurrency/idempotency guards, durable `change_sets` |
| 2 | ChangeSet **execution** (CP-08 lifted, scoped): §36 typed actuator registry, §34 state-machine executor, verify-or-rollback (§32.19–20), LKG only after verification, evidence records + ActionRequired (§12.13–12.14), approval gating by §21 role, durable execution tables |
| 3 | Loop closing from real integrations: §16 admission, §17 discovery, §18 mapping candidates, §19 source authority + equivalence keys, §25/§38 schema pipeline with auto-promotion gates, §20 dry-run/digital twin, §37 simulation/shadow (no-mutation), flag-gated §32/§35 scheduler |
| 4 | Progressive delivery: §40 rings as generic rollout infrastructure, §12.8 rollout engine with §12.9 health-gated canary, §29 fleet controller over §28 channels + §30 platform-behavior policy, Kyber console capability vocabulary (§21, §3.2) |

Everything from §32 step 12 onward (ChangeSet generation, blast radius, risk,
automation authority, simulate/shadow, approval, execution, verify/rollback,
last-known-good, evidence, action-required, progressive rings) is therefore **in
scope of the lane** — but every capability ships flag-gated OFF and is exercised
by tests only until a §41+ review lifts the boundary.

## Lane boundary

| The lane is | The lane is not |
|---|---|
| Plan → approve → execute → progressively deliver change over managed integrations, through typed actuators on governed paths | Production activation: no switch is flipped; the scheduler is idle until its master switch + kill-switch turn on behind the §41+ review |
| Operator-only review surface (read-only GETs: integrations, change-sets, approvals, action-required) | A tenant console: the `reconciled_control` domain carries no tenant grant (Phase-0 governance decision, unchanged) |
| Actuators / executor / rollout engine / fleet planner — exercised by tests only | Autonomous tenant delivery: rings above 0% reach tenants only under tenant update policy + approvals; the fleet controller composes plans and never self-executes |
| Additive durable tables + contract twins (Data-Exchange pattern) | New event family, renumbered planes, parallel manifest service, new collection authority, or any SDK behavior change |

## Layout

```
packages/shared/managed-integrations.ts            TS contract twin (canonical const arrays + interfaces)
Backend Architecture/aether-backend/services/
  managed_integrations/
    contracts.py         Python mirror (tuples + pydantic view models)
    flags.py             function-local OFF-by-default flag reads
    availability.py      CP-12 typed-availability helpers (never fabricate)
    desired_policy.py    desired-state assembly from release-channel policy (§28)
    sensors.py           read-only observed-state adapters over existing authorities (§12.2)
    reconciler.py        desired-vs-observed classification (§32 steps 1–11)
    change_planning.py   candidate ChangeSet generation + blast radius + risk + authority (§32.12–15)
    actuators.py         typed actuator registry (§36, day-1 kinds)
    executor.py          §34 state-machine executor: verify / commit / rollback / LKG-after-verify
    admission.py         §16 admission lifecycle (no forced exit)
    simulation.py        §37 compare-paths shadow plane (never mutates canonical state)
    schema_mapping.py    §25 profile→diff→compile→candidate pipeline, §38 promotion gates
    source_authority.py  §19 authority rules + observation-equivalence keys
    scheduler.py         flag-gated periodic reconcile+plan+execute loop (rides `maintenance`)
    rollout.py           §12.8 rollout engine: rings, stage/percentage law, pause/resume
    fleet_controller.py  §29 planner over §28 channels + §30 platform behavior (composes only)
    *_repository.py      one module-local store per engine (in-memory mirror of the tables)
    routes.py            read-only operator router (6 GETs, operator-gated)
  kyber/access/
    capabilities.py      `kyber.reconciled_control.read` (D4 evidence vocabulary)
    roles.py             `_READ_EVIDENCE` template grant (rides with kyber.audit.read)
  config/settings.py     ReconciledControlPlaneConfig (flags, all default OFF)
  main.py                flag-gated router mount (default OFF)
  alembic/versions/      20260906_rcp_{managed_integrations,change_sets,execution,
                         admission,simulation,schema_mapping,source_authority,
                         rollouts,fleet_update}.py — additive tables
config/route_registry.yaml     six kyber_routes declarations (D4, action_class 0)
config/storage_policies.yaml   17-field rows for every RCP table
tests/contracts/test_managed_integrations_parity.py   twin parity gate
tests/unit/reconciled_control/   vocab + engine + console + flag-OFF parity tests
Backend Architecture/aether-backend/tests/managed_integrations/   repo round-trip tests
```

## Key decisions

**Governance domain `reconciled_control`.** The surface is an Olympus
operator-only domain added to the `GovernanceDomain` twin (TS union + Python
Literal) and granted explicitly to `olympus_operator` (read, aggregate) and
`olympus_admin` (full) — but **not** added to `ALL_DOMAINS`, mirroring the
`kyber_*` operating-plane domains. Real enforcement at the route is the Kyber
operator gate (`require_kyber_operator`), the same gate provider-catalog and
provider-runtime admin routes use.

**Console surfacing (Phase 4).** The Phase-0 decision to hold back any
`kyber_routes` capability declaration is closed: `kyber.reconciled_control.read`
is a first-class Kyber console capability (domain `reconciled_control`, action
read, scope `all_tenants_aggregate`, disclosure D4 event evidence), rides the
`_READ_EVIDENCE` role-template grant beside `kyber.audit.read` (the
operator-derived-records precedent), and backs six `kyber_routes` declarations
over the operator GET surface. The declarations are ADD-authority only; they
engage denial when the routes are mounted **and**
`KYBER_BACKEND_AUTHZ_ENFORCED` is on (default OFF in local/dev, default ON for
deploy targets). The capability never implies mutation authority and stays out
of `kyber_admin` aggregates.

**CP-12 distinctness.** `missing`, `empty`, `zero`, `degraded` and
`not_applicable` remain distinct — no operator surface fabricates
zero/empty for missing evidence. `availability.py` only ever emits a value it
can defend; ambiguity resolves to `unknown`. The reconciler never classifies
`actionable` from missing evidence: an absent observation yields `unknown` with
a note, never a fabricated drift. Health gates (Phase 4) inherit this:
missing evidence is a `not_observable` violation, and the only availability
values a gate may pass are `available` and `empty`.

**Evidence-backed observed state.** `sensors.py` adapters are read-only and
pure over already-fetched authority records (SDK health/heartbeat, provider
runtime connection, capability activation). Missing records → availability
`missing` + provenance `unknown`/`backend_verified`; nothing is inferred from
the absence of bytes. A provider connection that needs a credential but has
none surfaces `provider_state=credential_missing` — a fail-closed sentinel the
reconciler treats as `blocked`, not as drift to auto-remediate.

**Desired state is policy, not invention.** `build_desired_state` assembles a
`DesiredStateSpec` from the tenant's release channel (§28, default
`managed_stable`) — the channel resolves to an inclusive floor inside the
canonical SDK version bands — plus capability requirements the caller asserts
explicitly. Nothing auto-derives a capability set; that would invent policy.

**Execution is a state machine, not a script.** The §34 ChangeSet state
machine is the single transition authority (Phase 2); illegal transitions fail
closed from the start. Verification (technical + semantic) precedes
commit-or-rollback, and last-known-good is established **only after**
verification passes (§12.12) — a rolled-back or unverified change never
becomes the LKG reference. Every attempted change leaves an evidence record
(§12.13) with its epistemic kind labeled (§12.15); a rollback carries the
LKG ref and queue/replay policy.

**Progressive delivery follows the ring law (§40).** Ring order is fixed —
`olympus_internal → test_tenants → 1% → 5% → 20% → 50% → 100%` — one ring at a
time, and the delivered percentage always tracks the current stage
(`ring_percentage` helper, contracts.py). Rollout state is durable: `rollouts`
rows carry the §12.8 contract fields plus coordinator-approved `paused_reason`
and `end_state` (`completed`/`rolled_back`) columns, so an auto-pause or
auto-rollback from a §12.9 health-gate breach is never an in-memory accident.

**Channel semantics and platform behavior (§28–§30).** A release channel
auto-delivers exactly the classes its name promises — `security_auto` delivers
security-class updates, `patch_auto` patches, `compatible_auto` compatible,
`managed_stable` the managed-stable band — and `latest` is rejected on
**every** channel: managed_stable is never uncontrolled latest. §30
platform-upgrade behaviors are mirrored only where a kind is evidenced; an
unmapped kind resolves to `review`/`unknown`, never a guessed token, and
host-mediated rows resolve to the `action` execution path (no hidden promise
rewriting customer-controlled binaries). No-policy tenants default to
`review`.

**Durable, decoupled stores.** Each engine owns a module-local store that is
the in-memory mirror of its additive table (migration files are
`SCHEMA_SQL`-identical to the repositories, so the in-memory path under
`AETHER_ENV=local` mirrors the columnar path). No foreign key links
`reconcile_runs` to `managed_integrations`: the reconciler must record an
evidence-backed `unknown`/`missing` run for an integration that has never been
registered. Tenancy is enforced in repository SQL.

## Reconcile result semantics (§32)

| Result | Meaning |
|---|---|
| `match` | Desired == observed on every reconciled dimension. |
| `acceptable_drift` | Only tracked-but-tolerated drift (e.g. a deprecated-but-served runtime at the `managed_stable` floor → `release_support_drift`). |
| `actionable_drift` | Drift the lane turns into a ChangeSet: version, capability, schema, health, fleet-identity, or below-served release support. |
| `blocked` | An upstream authority is fail-closed (required provider credential absent). |
| `unknown` | Evidence is stale or entirely absent — never classified from missing evidence. |

## Invariants honored

1. No operator surface fabricates `zero`/`empty` for missing evidence (CP-12);
   health gates pass only `available`/`empty` and treat missing evidence as
   `not_observable`.
2. No mutation outside the governed executor path: the plane applies change
   only through typed actuators on an approved, flag-gated path (Phase-2
   scoped CP-08 lift); the scheduler stays idle while its master switch is OFF,
   and the fleet controller composes plans but never self-executes.
3. All behavior is flag-gated OFF (`AETHER_RECONCILED_CONTROL_*`), defaulting
   to byte-identical existing behavior; production flips require the §41+
   review.
4. Registered rows carry tenant scope and reads are tenant-scoped (operator
   aggregate reads are explicit and gated by the Kyber operator identity).
5. The `reconciled_control` domain never implies authority to mutate
   integration state — it is kept out of `ALL_DOMAINS` and `kyber_admin`
   aggregates; the console capability is read-only (D4) evidence.
6. Progressive rings never bypass policy: delivery above 0% reaches tenants
   only under tenant update policy + §21 approvals, and no channel ever
   resolves to uncontrolled `latest`.
7. Unknowns are never coerced: an unmapped §30 behavior, an unknown drift
   type, or missing evidence resolves to `review`/`unknown`/`not_observable`
   — never to a fabricated token.
