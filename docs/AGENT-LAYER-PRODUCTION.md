---
title: Agent Layer Production Readiness
slug: operations/agent-layer-production
section: operations
visibility: I
audience: [ops, architect]
status: stable
---

# Agent Layer production readiness

As of June 4, 2026, the Agent Layer is **not production-ready unless the hosted control-plane additions are enabled and backed by durable storage**. The controller model remains intact (Governance, Nous, Intake, Discovery, Enrichment, Verification, Commit, Recovery, Kinesis, Catalyst, and Cycle), but production operation requires Kyber to use the `/v1/agent/*` control-plane routes and the durable repository boundary.

## What is now durable

The hosted control plane persists tenant-scoped records for:

- `agent_objectives`
- `agent_plans`
- `agent_plan_steps`
- `agent_checkpoints`
- `agent_events`
- `agent_review_batches`
- `agent_staged_mutations`
- `agent_controller_heartbeats`
- `agent_worker_runs`
- `catalyst_wake_triggers`

Local mode (`AETHER_ENV=local`) may use the in-memory store for demos and mocked Kyber. Hosted modes must configure Redis through `REDIS_HOST`/`REDIS_URL` or another implementation of the shared durable store. In-memory fallback outside local mode is blocked unless `AETHER_ALLOW_INMEMORY_STORE=1` is deliberately set.

## Kyber operator workflows

Kyber points to the backend with `VITE_API_BASE_URL` when `VITE_KYBER_ENV` is `local`, `staging`, or `production`. The Agent Command Center can use:

- `GET /v1/agent/health` for aggregate health, queues, kill switch, active/blocked/failed objectives, and review counts.
- `POST /v1/agent/objectives` to submit objectives.
- `GET /v1/agent/objectives` and `GET /v1/agent/objectives/{id}` for the Objective Board and Run History.
- `POST /v1/agent/objectives/{id}/pause|resume|cancel` for supervised lifecycle control.
- `POST /v1/agent/dispatch` to dispatch a controller step.
- `GET /v1/agent/review-batches` plus approve/reject routes for the Review Queue.
- `GET /v1/agent/events` for the Feed / Timeline.
- `POST /v1/agent/kill-switch` for tenant-scoped emergency stop/release.
- `POST /v1/agent/controllers/heartbeat` and `GET /v1/agent/controllers/status` for worker/controller status.

All routes require an authenticated tenant context. Mutating routes require action-specific permissions such as `agent:dispatch`, `agent:pause`, `agent:approve`, `agent:heartbeat`, or `admin` for the kill switch.

## Worker operation

Local worker examples:

```bash
cd "Agent Layer"
celery -A queue.celery_app worker -l info -Q discovery,enrichment,verification,commit,recovery,default
celery -A queue.celery_app beat -l info
```

Hosted workers should run separate queue pools for `discovery`, `enrichment`, `verification`, `commit`, `recovery`, and `default`. Workers must heartbeat through `/v1/agent/controllers/heartbeat` with controller name, worker id, status, queue depth, and non-secret metadata. Catalyst cron/wake scheduling should persist triggers in `catalyst_wake_triggers` and replay missed fires after restart.

## Graph mutation safety

Agents must never write canonical graph state directly. They stage mutation proposals with mutation classes 1-5 into review batches. Human approval or rejection is required before any canonical commit path runs. Every staged, approved, rejected, committed, quarantined, or rolled-back mutation must emit an agent timeline event and an audit record. Secrets are redacted before persistence and before Kyber display.

## Failure modes and recovery

- **Process restart:** objectives, runs, review batches, events, and heartbeats are reloadable from the durable store.
- **Worker lost/stuck:** queue depth and heartbeat age identify stale controllers; recovery should create a new worker run with the same idempotency key.
- **Redis unavailable in hosted mode:** startup/request handling fails closed instead of silently switching to in-memory state.
- **Kill switch engaged:** objective submission and dispatch are blocked until an admin releases the switch.
- **Rejected mutation:** mutation remains non-canonical and is auditable in the timeline.

## Launch checklist

1. Run migrations, including `20260604_agent_control_plane`.
2. Set `IG_AGENT_LAYER=true` and configure Auth/RBAC for operator-only routes.
3. Set Redis/Celery URLs and start all queue pools.
4. Configure Kyber with `VITE_KYBER_ENV=staging|production` and `VITE_API_BASE_URL`.
5. Verify tenant isolation by listing objectives/events/reviews from two tenants.
6. Submit a staged mutation and confirm it requires approval before commit.
7. Engage and release the kill switch.
8. Confirm Prometheus metrics and structured logs include request correlation IDs and no secrets.
