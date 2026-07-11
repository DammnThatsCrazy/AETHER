---
title: Durable Jobs Platform Source of Truth
status: stable
source_files:
  - Backend Architecture/aether-backend/services/jobs/handlers.py
  - Backend Architecture/aether-backend/services/jobs/service.py
  - Backend Architecture/aether-backend/services/jobs/worker.py
  - Backend Architecture/aether-backend/services/jobs/scheduler.py
  - Backend Architecture/aether-backend/services/jobs/routes.py
  - Backend Architecture/aether-backend/services/jobs/kyber_routes.py
  - Backend Architecture/aether-backend/repositories/jobs_repo.py
last_synced_commit: pending
---

# Durable Jobs Platform

The generic jobs platform runs durable, tenant-scoped background work with
at-least-once delivery, leasing, retries, a dead-letter path, and an operator
console. It is the substrate for exports, notifications delivery, scheduled
sweeps, and the Import Engine's commit/replay — anything that must survive a
process restart and be auditable end to end.

## Model

`repositories/jobs_repo.py` (direct-SQL over `jobs` / `job_events` / `job_schedules`,
migration `20260713_platform_control_plane`):

- **Claim** is `FOR UPDATE SKIP LOCKED` with a lease (`lease_expires_at`,
  `leased_by`); a worker heartbeats to extend its lease, and a lease sweeper
  requeues jobs whose worker died. In local mode an in-memory repo mirrors the
  same semantics (DDL-parity tested).
- **Idempotency**: a partial unique index on `(tenant_id, job_type, idempotency_key)`
  means an idempotent enqueue returns the existing job (`replayed=True`) instead
  of duplicating work; a previously-*failed* row with the same key is re-queued
  in place.
- **States** (`services/jobs/models.py::JobStatus`): `accepted → queued → running`
  → `succeeded` / `partially_succeeded` / `failed`, plus `cancel_requested` →
  `cancelled` and `expired`. A terminal `failed` job dead-letters (a
  `job.dead_lettered` event + an inbox notification).

## Handlers

`services/jobs/handlers.py` — a handler is registered per `job_type`:

```python
@register_handler("exports.generate", tenant_invocable=True)
async def generate_export(payload: dict, ctx: JobContext) -> JobOutcome:
    ...
    return JobOutcome(status="succeeded", result={...})
```

- The handler returns a `JobOutcome` whose status is `succeeded` /
  `partially_succeeded` / `failed`.
- `JobContext` exposes `await ctx.heartbeat()` (extends the lease, raises
  `JobCancelled` on operator cancel) and `await ctx.emit_event(type, payload)`
  (a `job_events` timeline row, best-effort).
- `tenant_invocable=True` allows a tenant to enqueue the type via
  `POST /v1/jobs`; every other type is internal-only (schedules, other services,
  Kyber). Handlers are module-level functions and are registered at startup
  before the supervised worker starts claiming.

## Surfaces

`services/jobs/service.py::JobsService.enqueue(tenant_id, job_type, payload, *,
idempotency_key, correlation_id, requested_by, priority, max_attempts,
scheduled_for)` is the enqueue entry point. Routes:

| Route | Purpose |
|---|---|
| `POST /v1/jobs`, `GET /v1/jobs`, `GET /v1/jobs/{id}`, `/{id}/events`, `/{id}/cancel` | tenant job center |
| `GET /v1/kyber/jobs/timeline`, `POST /v1/kyber/jobs/{id}/requeue` | operator console (`require_kyber_operator`) |

`services/jobs/scheduler.py` fires cron/one-shot schedules (croniter + zoneinfo,
misfire/overlap policy, `schedule_id:fire_time` idempotency) onto the same queue.

## Boundary — the jobs platform does NOT run agent work

The **agent runtime** (`services/agent/runtime_repository.py`,
`worker_bridge.py`, `worker_routes.py`, `mutation_commit.py`) is a **separate,
Redis-backed** execution system for the agent domain (agent step execution,
mutation-commit approvals). It has its own store, its own worker bridge, and its
own operator surfaces, and it is intentionally **not** routed through this
generic Postgres-backed jobs platform:

- Agent execution has a different actor/approval model (operator mutation
  commits) and latency profile than durable batch jobs.
- Coupling them would force one ret/lease/DLQ policy onto two very different
  workloads.

So: register a new `job_type` + handler here for durable batch/background work
(exports, sweeps, import commit, notifications delivery). Do **not** move agent
step execution onto this platform — the boundary is deliberate and load-bearing.

## Non-goals

- No cross-tenant job execution: every job is tenant-scoped; only the Kyber
  operator surfaces read across tenants.
- The platform delivers at-least-once — handlers must be idempotent (enqueue
  idempotency keys + `ON CONFLICT`-style handler writes).
