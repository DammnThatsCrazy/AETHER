---
title: Kyber Mission Aggregate & Monitoring
slug: kyber/missions
section: kyber
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/kyber/ops/mission_contracts.py
  - Backend Architecture/aether-backend/services/kyber/ops/mission_repository.py
  - Backend Architecture/aether-backend/services/kyber/ops/missions.py
  - Backend Architecture/aether-backend/services/kyber/ops/monitoring_service.py
  - Backend Architecture/aether-backend/services/kyber/ops/mission_routes.py
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 3
last_synced_commit: "fffcd7dc5f02"
---

# Kyber Mission Aggregate & Monitoring

A **Mission** is the unified operator-plane view of a unit of governed work. It
is a *thin persisted root* plus *read-time composition* over the existing durable
planes — not a second runtime and not a dual-write. Mounted at
`/v1/kyber/missions` **only when `KYBER_MISSIONS_ENABLED=true`** (default OFF);
the monitoring loop runs only when `KYBER_MISSION_MONITORING_ENABLED=true`.

## Composition (no dual-write)

`MissionService.reconstruct(mission_id)` assembles a `MissionView` from:

- Objective / Plan / PlanSteps / WorkerRuns / review-batch approvals — via
  `services.agent.runtime_repository`.
- Jobs and job events — via `repositories.jobs_repo`.
- Observed tool calls — the `agent_events` stream.
- Evidence & `VerificationResult` — `Agent Layer/models/evidence.py`.
- Commands — `services.kyber.ops.command_repository`.

Only mission identity, lifecycle `status`, `verification_gate`, `MissionResult`,
and `MonitoringCondition`s are persisted (`kyber_missions`,
`kyber_monitoring_conditions`). Everything else is read from its owning plane, so
there is a single source of truth per fact.

## Lifecycle & the completed ≠ verified gate

`MissionStatus` has 19 states (`detected … monitoring … completed … cancelled`).
`MissionService.transition()` uses an explicit `allowed_from` map that
**structurally forbids** entering `completed` unless the verification gate is not
required, or the latest `VerificationResult.decision == "passed"`. Until then the
mission rests in `verifying`/`awaiting_review` — the mission analogue of the
command plane's `executed_unverified` discipline.

## MonitoringConditions & escalation

`MonitoringService.check_due(now=None)` (invoked by the flag-gated loop in
`main.py`) evaluates each due condition's `expected_state` against live state; on
mismatch it bumps `failure_count` and reschedules `next_check_at`. When the
`escalation_policy` threshold is crossed it escalates via
`report_operational_signal(...)` (the reopen path — `transition_objective` has no
`reopen` action), sets the condition to `escalated`, and moves the mission to
`monitoring`. The loop is idempotent and stateless per tick.

## Access control

Routes use **workforce identity only** — `require_kyber_access` +
`resolve_access_context(tenant_scope="required")` + `_assert_tenants_within_scope`
against the mission's tenant. Capability is the existing `kyber.incident.read`
(no new capability minted). A plain Aether tenant — even an admin — is denied.
Never uses `request.state.tenant`.

## Endpoints

`GET /v1/kyber/missions`, `GET /v1/kyber/missions/{id}` (full `MissionView`),
`GET /v1/kyber/missions/{id}/timeline`, and `GET`/`POST
/v1/kyber/missions/{id}/monitoring`.

## Temporal correctness

All instant handling goes through `shared.temporal.instant.ensure_aware_utc`;
timezone-naive datetimes are rejected, not silently assumed UTC.

## Known limitations

- Flag-gated OFF; no live operator exercise yet — coverage is unit-level
  (`tests/kyber/`, 12 tests: reconstruction, completion gate, monitoring reopen,
  scope enforcement).
- Evidence/verification are composed read-time from `agent_events` + `MissionResult`
  refs; a dedicated durable evidence plane is a future seam, not a dual-write here.
- Jobs are composed via `mission.command_ids` (no list-by-correlation index).
