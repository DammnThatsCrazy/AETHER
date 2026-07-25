---
source_files:
  - Backend Architecture/aether-backend/services/agent/runtime_repository.py
  - Backend Architecture/aether-backend/services/agent/worker_bridge.py
  - Backend Architecture/aether-backend/services/agent/worker_routes.py
  - Backend Architecture/aether-backend/services/agent/mutation_commit.py
  - Backend Architecture/aether-backend/services/agent/briefings.py
  - Backend Architecture/aether-backend/services/agent/ops_alerts.py
  - scripts/ops_readiness.py
last_synced_commit: HEAD
---

# Aether / Kyber One-Person Operations — Source of Truth

## Overview

One operator supervises, approves, recovers, and steers Aether through Kyber
without babysitting every subsystem. One-person ops **reduces operator load;
it never removes human control** — approval gates are mandatory and cannot be
disabled by these features.

Execution loop:

```txt
Kyber/operator objective → backend dispatch → durable run record
→ queue publish (Celery) → worker execution → heartbeat/status callbacks
→ timeline/checkpoint/review output → operator approval → governed commit
```

## Worker execution bridge

- `services/agent/worker_bridge.py` publishes objective steps to the Agent
  Layer's Celery broker **by task name** (`aether.agent.execute_objective_step`)
  with a canonical envelope: `tenant_id, objective_id, run_id, controller,
  queue, idempotency_key, attempt, payload, created_at, request_id`
  (+ optional `plan_id`/`step_id`). No cross-package import — the Agent Layer
  remains separately deployable.
- Dispatch (`POST /v1/agent/dispatch`) publishes only when the runtime
  repository reports a **newly created** run (`record_dispatch` idempotency);
  duplicate dispatch with the same idempotency key never enqueues twice.
  Paused/cancelled/blocked/awaiting-review/failed/completed objectives cannot
  dispatch; the kill switch blocks all dispatch.
- **Hosted fail-closed:** a missing/unreachable broker raises
  `BridgeUnavailableError` outside local mode and the run is marked
  `dispatch_failed`; local mode logs and continues (in-memory development).
- Workers report back over HTTP with a **worker service credential**
  (`agent:run_update` permission, mirroring the `agent:heartbeat` precedent):
  `POST /v1/agent/runs/{run_id}/status` (`running|completed|failed|retry`)
  with sanitized output/error. Operator tokens cannot spoof worker updates.
- Stuck-run detection: runs in `queued|running` beyond `RUN_STALE_SECONDS`
  surface via `GET /v1/agent/runs/stuck` and `sweep_stale_runs`; replay
  helpers create a fresh run from the same envelope. `GET /v1/agent/health`
  exposes queue depth, worker count, stale workers, and active/failed/stuck
  run counts.

## Approval-to-commit graph mutation pipeline

`services/agent/mutation_commit.py` (flag
`AETHER_STAGED_GRAPH_MUTATION_REVIEW_ENABLED`):

- Commit runs **only after an explicit operator approval** of a review batch;
  there is no path from staged → committed that skips approval.
- Each approved mutation is validated (`GraphWriteValidator`, mutation-class
  checks, edge idempotency keys) and — when CIS is enabled — evaluated by the
  CIS mutation gateway; quarantine-band mutations become `quarantined`, never
  committed.
- Per-mutation transitions `approved → committed | quarantined | failed_commit
  | rolled_back` are transaction-safe and fully audited; partial batch
  failures are reported per-mutation, never as silent partial success.
  `rollback_mutation` records `rolled_back` with best-effort inverse ops.
- Rejected batches never commit anything.

## Durable briefings, alerts, and Catalyst/Cycle

- `services/agent/briefings.py` — operator briefings persisted in the
  `agent_briefings` durable store (replacing the Agent Layer's in-memory
  prototype for backend surfaces): generated from live state (objectives by
  status, stuck runs, pending review batches, staged mutation counts,
  kill-switch state, recent alerts). `GET /v1/agent/briefings` +
  `POST /v1/agent/briefings/generate`.
- `services/agent/ops_alerts.py` — alert compression (same `dedupe_key`
  within the window increments a count instead of duplicating) + notification
  routing through the existing notification service seam; per-channel state
  in `ops_notification_state`.
- Catalyst wake triggers (durable since migration `20260604`) and Cycle
  runtime consume the same governed dispatch path — automation stages and
  proposes; operators approve.

## Kyber Agent Command Center (flag `KYBER_AGENT_COMMAND_CENTER_ENABLED` /
`enableAgentCommandCenter`)

Live operator surfaces across `local | staging | production`
(`VITE_KYBER_ENV` + `VITE_API_BASE_URL`): worker/runtime health
strip (queue depth, workers, stale, active/failed/stuck runs), run history
with stuck highlighting, review queue with confirm-gated approve/reject,
staged-mutation commit visibility, kill-switch state and control, briefings
feed with on-demand generation, compressed ops alerts.

## Storage

Migration `20260712_ops_runtime.py`: `agent_briefings`, `ops_alerts`,
`ops_notification_state` store-backing tables + additive stale-run index on
`agent_worker_runs`. All runtime stores fail closed outside local mode when
Redis/durable backing is missing (`shared/store.py` invariant).

## Feature flags (default OFF)

`AETHER_AGENT_RUNTIME_DURABLE_ENABLED`, `AETHER_AGENT_WORKER_BRIDGE_ENABLED`,
`AETHER_STAGED_GRAPH_MUTATION_REVIEW_ENABLED`,
`AETHER_CATALYST_CYCLE_AUTOMATION_ENABLED`,
`KYBER_AGENT_COMMAND_CENTER_ENABLED`, `KYBER_ONE_PERSON_OPS_ENABLED`.

## Release gates

- `make ops-readiness` (`scripts/ops_readiness.py`): flags present +
  default-OFF, ops modules importable, runtime stores reachable, worker
  bridge fails closed in hosted mode, mutation commit approval-gated,
  all six source-of-truth docs present. Wired into `make release-gate`
  after repo consistency and strict production status.
- Backend suites: `BE/tests/one_person_ops/` (dispatch idempotency,
  lifecycle-state dispatch blocks, kill switch, fail-closed bridge, worker
  callback permissions, run lifecycle + stuck sweep + replay, commit/
  quarantine/rollback/rejection, briefing durability, alert compression,
  flag gating) plus `tests/agent/` regression.

## Known limitations / non-goals

- Live Celery round-trips require a Redis broker; this environment verifies
  the bridge contract with fail-closed/fail-open tests and an in-memory
  broker fallback. The worker task executes the controller seam where
  cleanly reachable and otherwise acknowledges the envelope — the
  bridge/callback contract is the release surface.
- Notification routing uses the existing delivery/notification seams;
  channel credentials remain tenant/operator-configured.
- No autonomous approval: Catalyst/Cycle automation stages work and
  generates briefs; humans approve every canonical commit.
