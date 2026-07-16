---
title: Backend Execution Model
slug: architecture/backend-execution-model
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: beta
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/config/settings.py
  - Backend Architecture/aether-backend/main.py
  - Backend Architecture/aether-backend/services/runtime/roles.py
  - Backend Architecture/aether-backend/services/runtime/run_role.py
  - Backend Architecture/aether-backend/services/runtime/specs.py
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
last_synced_commit: "9223aaa4"
---

# Backend Execution Model

Aether's backend is a single codebase that runs in one of several **runtime
roles**. Local and dev run everything in one process (`AETHER_ROLE=all`);
staging and production split the HTTP API from the background workers so the
API process no longer starts every worker, consumer, and cron in-request.

## Runtime roles (`AETHER_ROLE`)

| Role | Runs |
| --- | --- |
| `all` | Everything in one process (local/dev default). Rejected in staging/production. |
| `api` | The FastAPI HTTP server only — no supervised workers, no stream consumers. |
| `outbox-relay` | Outbox relay workers: the notification outbox and the ingestion `event_outbox` relay (FT-6). |
| `stream-worker` | Stream loops (event replay, Dune polling) + stream consumers. |
| `identity-worker` | Identity resolution (shared consumer today — dedicated loop deferred). |
| `graph-writer` | Graph/profile writes (shared consumer today — dedicated loop deferred). |
| `measurement-worker` | Measurement/attribution (shared consumer today — dedicated loop deferred). |
| `materializer` | Artifact materialization sweeps (export expiry, payment-rail sync). |
| `maintenance` | Cross-cutting crons/sweepers (retention, billing overage, SLA, jobs). |

The canonical role set lives in `config/settings.py::RUNTIME_ROLES`; the
role → worker mapping lives in `services/runtime/roles.py::ROLE_TO_SPEC_NAMES`.

## Entry point

Boot exactly one role:

```bash
python -m services.runtime.run_role api            # HTTP server (uvicorn main:app)
python -m services.runtime.run_role stream-worker  # supervised stream workers
python -m services.runtime.run_role maintenance    # cron/sweeper workers
```

- `api` boots `uvicorn main:app` (host/port from `AETHER_API_HOST` /
  `AETHER_API_PORT`, defaults `0.0.0.0:8000`).
- A worker role builds `services/runtime/specs.py::build_worker_specs`, filters
  it to the specs that role owns, and runs them under the existing
  `WorkerSupervisor` (crash → backoff restart; required workers fail-closed in
  staging/production).

## Lifespan gating (`WORKER_ROLES_ENABLED`)

`main.py`'s FastAPI lifespan is gated by `WORKER_ROLES_ENABLED`:

- **Off** (default in local/dev): byte-identical to the historical lifespan —
  the process attaches every consumer and starts every supervised worker.
- **On** (default in staging/production): an `api` process starts **no** stream
  consumers and **no** supervised workers; the `all` role still starts
  everything; workers run in their own role processes.

`should_start_workers(role)` and `should_start_consumers(role)`
(`services/runtime/roles.py`) are the pure gates the lifespan consults.

## Backend selectors

Each subsystem binds an explicit backend, declared via env and surfaced on
`settings.runtime`:

| Env var | Default | Notes |
| --- | --- | --- |
| `DATABASE_BACKEND` | `postgres` | `memory` rejected in production. |
| `CACHE_BACKEND` | `memory` | Local convenience; `memory` rejected in production. |
| `EVENT_BACKEND` | `sns_sqs` | e.g. `sns_sqs`, `kafka`. |
| `GRAPH_BACKEND` | `postgres` | |
| `ANALYTICS_BACKEND` | `postgres` | |
| `OBJECT_BACKEND` | `s3` | |
| `ML_MODE` | `inline` | `inline` or `remote`. |
| `DEPLOYMENT_PROFILE` | `local-live` | Drives compose/helm wiring & ops tooling. |

## Ingestion event-outbox relay (FT-6)

The `/v1/batch` V2 path (FT-5) writes typed Bronze rows plus a transactional
`event_outbox` row in one transaction and never publishes in-request. The
**event-outbox relay** (`services/ingestion/outbox_relay.py`, WorkerSpec
`event_outbox_relay`, owned by the `outbox-relay` role, gated by
`OUTBOX_RELAY_ENABLED`) drains that table and publishes each row to the event
bus, where the existing idempotent consumers (`services/ingestion/workers.py`)
run the Bronze→Silver projection, identity signals, and measurement fan-out —
downstream work becomes replayable instead of riding the request.

- **Claiming:** one `UPDATE … FROM (SELECT … FOR UPDATE SKIP LOCKED)` claims a
  batch, so any number of relay processes cooperate without double-claiming.
- **Leases:** a claim pushes `available_at` forward by
  `OUTBOX_RELAY_LEASE_SECONDS`; a crashed relay's rows are reclaimed when the
  lease lapses.
- **Backoff / dead-letter:** publish failures move rows to `retry` with
  exponential backoff; after `OUTBOX_RELAY_MAX_ATTEMPTS` a row parks in
  `dead_letter` (terminal, kept for ops). `attempt_count` increments at claim
  time, so poison rows converge instead of looping.
- **Delivery:** at-least-once. Relay-published events carry
  `source_service="ingestion.outbox_relay"`; the Bronze-writer consumer skips
  them because the V2 ingest transaction already persisted the typed Bronze row.

Tuning env vars: `OUTBOX_RELAY_BATCH_SIZE` (100),
`OUTBOX_RELAY_POLL_INTERVAL_S` (2), `OUTBOX_RELAY_LEASE_SECONDS` (60),
`OUTBOX_RELAY_MAX_ATTEMPTS` (8) — all on `settings.ingestion_v2`.

## Production fail-closed rules

`Settings.__post_init__` (`config/settings.py`) enforces, at process start:

- **Every environment:** `AETHER_ROLE` must name a known role.
- **Staging & production:** `AETHER_ROLE=all` is rejected — run an explicit role.
- **Production:** `CACHE_BACKEND=memory` and `DATABASE_BACKEND=memory` are
  rejected — a memory backend is never a correctness source in production.

Local/dev keep the single-process default (`all`, memory cache) working.

## Deferred

Dedicated supervised loops and stream-consumer attachment for the
`identity-worker`, `graph-writer`, and `measurement-worker` roles are deferred;
their work currently rides the shared consumer, and `run_role` starts an empty
supervisor for them. Tracked in `config/implementation_ledger.yaml`
(`FT-4-RUNTIME-ROLES`).
