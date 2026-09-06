---
title: Reconciled Control Plane — Phase 0 Architecture
slug: architecture/reconciled-control-plane
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/managed_integrations/
  - Backend Architecture/aether-backend/alembic/versions/20260906_rcp_managed_integrations.py
  - Backend Architecture/aether-backend/main.py
  - Backend Architecture/aether-backend/config/settings.py
  - packages/shared/managed-integrations.ts
---

# Reconciled Control Plane — Phase 0 Architecture

The **Reconciled Control Plane** is Aether's operational authority that
continuously converges every managed integration — SDKs, connectors, provider
connections, webhooks, imports, curated feeds — toward an authorized, healthy,
supportable desired state: *install once, continuously reconcile*. Its doctrine
is: **the SDK observes; the control plane manages; the backend reasons.**

This page records what Phase 0 actually built (the `ManagedIntegration`
abstraction + Contract-Spine twin extension + a reconciliation *skeleton*) and
— just as importantly — the boundary of what Phase 0 deliberately does **not**
do. Program sequencing and the reserved later phases live in
[`docs/plans/RECONCILED_CONTROL_PHASES.md`](../plans/RECONCILED_CONTROL_PHASES.md);
close-out evidence is in
[`docs/productization/reconciled-control-plane/EXECUTION_STATE.md`](../productization/reconciled-control-plane/EXECUTION_STATE.md).

## Governing spec

The canonical spec is the external *Aether Reconciled Control Plane Blueprint*
(sections 0–40 reviewed at Phase-0 planning time; the §41+ remainder is
reserved and needed before later phases). Vocabulary provenance is cited inline
per symbol. Phase 0 implements the **managed-integration abstraction** (§6,
CP-12) and the **reconcile steps 1–11 of §32**: load desired state, assemble
observed state, validate freshness, compute a typed per-dimension diff, and
classify the result. Everything from §32 step 12 onward (ChangeSet generation,
blast radius / risk, automation authority, simulate/shadow, approval,
execution, verify/rollback, last-known-good, evidence, action-required) is out
of scope for Phase 0 — there is **no actuator and no live reconcile trigger**.

## Phase-0 boundary

| In scope | Out of scope (explicit) |
|---|---|
| `ManagedIntegration` typed model, 21 kinds (§6), typed availability (CP-12) | Entity resolver / graph / 360 / decision logic (product planes untouched) |
| Desired-state assembly from existing release-channel + capability policy | A new collection authority or any SDK behavior change |
| Drift **classification** (`match` / `acceptable_drift` / `actionable_drift` / `blocked` / `unknown`) | Any applied `ChangeSet` / actuator / remote mutation (CP-08, deferred) |
| Read-only operator surface (`GET /v1/admin/kyber/managed-integrations[/{id}]`) | Any live scheduler that triggers reconcile on production integrations |
| Additive durable tables + contract twins (Data-Exchange pattern) | New event family, renumbered planes, parallel manifest service |

The reconcile machinery is **exercised by tests only** in Phase 0. Nothing in
the running service periodically reconciles a real integration until a later
phase mounts a scheduler behind an explicit flag.

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
    reconciler.py        pure desired-vs-observed classification (§32 steps 1–11)
    repository.py        durable managed_integrations + reconcile_runs stores
    routes.py            read-only operator router
  config/settings.py     ReconciledControlPlaneConfig (3 flags, all default OFF)
  main.py                flag-gated router mount (default OFF)
  alembic/versions/
    20260906_rcp_managed_integrations.py   additive tables (SCHEMA_SQL-identical to repository.py)
tests/contracts/test_managed_integrations_parity.py   twin parity gate
tests/unit/reconciled_control/             CP-12 + classification + flag-OFF parity tests
Backend Architecture/aether-backend/tests/managed_integrations/   repo round-trip tests
```

## Key decisions

**Governance domain `reconciled_control`.** The surface is an Olympus
operator-only domain added to the `GovernanceDomain` twin (TS union + Python
Literal) and granted explicitly to `olympus_operator` (read, aggregate) and
`olympus_admin` (full) — but **not** added to `ALL_DOMAINS`, mirroring the
`kyber_*` operating-plane domains. Real enforcement at the route is the Kyber
operator gate (`require_kyber_operator`), the same gate provider-catalog and
provider-runtime admin routes use. Route-level default-deny classification
covers `/v1/admin/kyber/*` via the registry `known_prefixes`; the route is not
added to the optional `kyber_routes` capability declarations because that
vocabulary (a separate Kyber workforce capability list) has no
reconciled-control capability yet — adding one is deferred to the phase that
builds the Kyber workforce console surface.

**CP-12 distinctness.** `missing`, `empty`, `zero`, `degraded` and
`not_applicable` remain distinct — no operator surface fabricates
zero/empty for missing evidence. `availability.py` only ever emits a value it
can defend; ambiguity resolves to `unknown`. The reconciler never classifies
`actionable` from missing evidence: an absent observation yields `unknown` with
a note, never a fabricated drift.

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

**Durable, decoupled stores.** `managed_integrations` and `reconcile_runs`
are additive tables (migration is `SCHEMA_SQL`-identical to the repository so
the in-memory path under `AETHER_ENV=local` mirrors the columnar path). No
foreign key links `reconcile_runs` to `managed_integrations`: the reconciler
must record an evidence-backed `unknown`/`missing` run for an integration that
has never been registered. Tenancy is enforced in repository SQL.

## Reconcile result semantics (§32)

| Result | Meaning |
|---|---|
| `match` | Desired == observed on every reconciled dimension. |
| `acceptable_drift` | Only tracked-but-tolerated drift (e.g. a deprecated-but-served runtime at the `managed_stable` floor → `release_support_drift`). |
| `actionable_drift` | Drift a later phase would turn into a ChangeSet: version, capability, schema, health, fleet-identity, or below-served release support. Phase 0 summarizes this evidence only. |
| `blocked` | An upstream authority is fail-closed (required provider credential absent). |
| `unknown` | Evidence is stale or entirely absent — never classified from missing evidence. |

## Invariants honored

1. No operator surface fabricates `zero`/`empty` for missing evidence (CP-12).
2. Phase 0 never applies a ChangeSet and never triggers reconcile on a live
   integration (CP-08 boundary; reconcile exercised by tests only).
3. All behavior is flag-gated OFF (`AETHER_RECONCILED_CONTROL_*`), defaulting to
   byte-identical existing behavior.
4. Registered rows carry tenant scope and reads are tenant-scoped (operator
   aggregate reads are explicit and gated by the Kyber operator identity).
5. The `reconciled_control` domain never implies authority to mutate
   integration state — it is kept out of `kyber_admin` aggregates.
