---
title: Reconciled Control Plane — Phases
slug: plans/reconciled-control-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---

# Reconciled Control Plane — Implementation Program

Program ledger for Aether's Reconciled Control Plane (managed-integration
convergence). Architecture + invariants:
[`docs/architecture/RECONCILED_CONTROL_PLANE.md`](../architecture/RECONCILED_CONTROL_PLANE.md).

Phase 0 is delivered on a stacked lane (`feat/reconciled-control-plane`,
base `ws/lane0-basefix` = the SDK-universal-ingestion integration head) so it
rides the same merged program as the lanes it composes onto. The canonical
completion gate is `make ci-check` at the lane tip (docs drift strict clean,
generated docs regenerated, `git status` empty).

## Phase 0 — Managed-integration abstraction + reconcile skeleton (this lane)

| Deliverable | Status |
|---|---|
| `ManagedIntegration` abstraction: 21 kinds (§6) + CP-12 typed availability | ✅ implemented |
| Contract-Spine twin extension: `packages/shared/managed-integrations.ts` ↔ `services/managed_integrations/contracts.py`, parity-gated | ✅ implemented |
| Governance domain `reconciled_control` (operator-only, explicit grants, out of `ALL_DOMAINS`) | ✅ implemented |
| Config + flags `AETHER_RECONCILED_CONTROL_*` (all default OFF) | ✅ implemented |
| Desired-state assembly from release-channel policy (`desired_policy.py`) | ✅ implemented |
| Read-only observed-state adapters over SDK-health / provider-runtime / capability authorities (`sensors.py`) | ✅ implemented |
| Reconcile classification (§32 steps 1–11): `reconcile` pure function + DRAFT change summary | ✅ implemented |
| Durable `managed_integrations` + `reconcile_runs` tables (additive alembic) + direct-SQL repositories | ✅ implemented |
| Read-only operator surface `GET /v1/admin/kyber/managed-integrations[/{id}]` (flag-gated OFF) | ✅ implemented |
| Registries + docs (ownership category, this page + architecture + EXECUTION_STATE) | ✅ implemented |
| Tests: CP-12 distinctness, reconcile classification, flag-OFF parity, repo round-trip, twin/domain parity | ✅ targeted tests pass |
| Full env-stripped `make ci-check` = 0 | ⏳ gate |

### Phase-0 boundary (explicit non-goals)

- **No live reconcile trigger.** Nothing periodically reconciles a real
  integration in Phase 0; the reconcile machinery is exercised by tests only.
- **No actuator.** A reconcile never applies a ChangeSet; drift evidence is
  persisted and read, never acted on (CP-08 boundary).
- **No route registry capability declaration.** The route is covered by
  `/v1/admin/kyber/*` default-deny classification + the handler Kyber-operator
  gate; a `kyber_routes` capability declaration awaits a Kyber workforce
  capability for the reconciled-control domain (a later-phase console task).

## Phase 1 — Live reconcile hook + drift evidence feed (reserved)

Wire the reconcile function to a scheduler and the existing authorities:

- Scheduled reconcile per registered integration (flag-gated, tenant-scoped),
  honouring the §32 freshness window; persisted `reconcile_runs` already land
  the evidence.
- `mark_reconciled` stamping and drift back-fill become exercised by the
  scheduler rather than tests.
- Health/lifecycle states transition from registration facts to observed-state
  projections.
- Register integrations from the existing authorities (SDK installations,
  provider connections, connectors, imports) into `managed_integrations`.

## Phase 2 — ChangeSet / actuator engine (reserved, CP-08 lift)

Lift the CP-08 boundary for scoped, safe mutation:

- ChangeSet generation from actionable drift (§32 step 12+) with blast radius,
  risk scoring, automation authority.
- Simulate/shadow + approval workflow; execution with verify/rollback and
  last-known-good.
- Dry-run/digital-twin reconciliation view.

## Phase 3+ — Drift automation + console (reserved)

- Drift auto-remediation for low-risk classes (managed_stable floor holds).
- Kyber workforce console surface incl. a `reconciled_control` capability in
  the Kyber capability vocabulary and `kyber_routes` registry declarations.
- Blueprint §41+ review gates everything that follows (the spec was truncated
  at §40 at Phase-0 planning time).

No phase is claimed complete ahead of `make ci-check` at that phase's tip.
