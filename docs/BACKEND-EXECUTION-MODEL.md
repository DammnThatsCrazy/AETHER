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
  - Backend Architecture/aether-backend/services/runtime/consumer_specs.py
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
last_synced_commit: "1c1b7416"
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
| `outbox-relay` | Outbox relay workers: the notification outbox, the ingestion `event_outbox` relay (FT-6), and the reward delivery outbox (drains `reward_delivery_jobs` through the rail-sender registry — the at-least-once delivery path for the reward plane). |
| `stream-worker` | Stream loops plus Bronze/Silver projection and notification consumers. |
| `identity-worker` | Identity-signal emission from validated SDK events. |
| `graph-writer` | Profile/graph projection and delegation mutation consumers. |
| `measurement-worker` | Identity merge/split journey rebuild and attribution restatement consumers. |
| `semantic-worker` | Semantic classification + identity-restatement consumers plus the `semantic_reconciler` (Gold recompute sweep, gated by `settings.semantic.reconciler_enabled`) and `semantic_retention` (Silver tombstone / Gold delete sweep, gated by `settings.semantic.retention_enabled`) loop workers. |
| `materializer` | Artifact materialization sweeps (export expiry, payment-rail sync, object-backed Bronze compaction + scheduled storage reconciler — FT-8, gated by the `settings.storage_plane` flags — and x402 settlement reconciliation, which advances verified PENDING settlements to on-chain finality, gated by the commerce control plane). |
| `maintenance` | Cross-cutting crons/sweepers (retention — including the flag-gated FT-8 storage-lifecycle retention pass, billing overage, SLA, jobs — plus the reward-plane/credential sweeps: stale reward-budget reservation release, reward DLQ depth gauge, expired credential rotation-overlap tombstoning, and the opt-in ledger chain verifier). |

The canonical role set lives in `config/settings.py::RUNTIME_ROLES`; the
role → loop-worker mapping lives in `services/runtime/roles.py`; canonical
stream ownership lives in `services/runtime/consumer_specs.py::CONSUMER_SPECS`.

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
  staging/production). It also selects and attaches only that role's canonical
  `ConsumerSpec` pipelines. Replicas use stable role-specific consumer groups.

## Lifespan gating (`WORKER_ROLES_ENABLED`)

`main.py`'s FastAPI lifespan is gated by `WORKER_ROLES_ENABLED`:

- **Off** (default in local/dev): `all` retains the historical single-process
  topology. An explicit `api` role remains pure and never attaches consumers.
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
| `DEPLOYMENT_PROFILE` | `local` | Drives compose/helm wiring & ops tooling. |

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

## Reward & commerce plane workers

Five supervised loops (`services/runtime/specs.py::build_worker_specs`, builders
in `services/rewards/workers.py` and `services/rewards/delivery_outbox.py`) close
the reward/x402/credential planes so activation stays credential-only rather than
depending on an operator manually draining a queue:

- **`reward_delivery_outbox`** (`outbox-relay`) — drains `reward_delivery_jobs`
  through the rail-sender registry each tick. It is the reward plane's
  at-least-once delivery path; before it was supervised a reward left the durable
  outbox only when an operator hit the drain route.
- **`x402_settlement_reconciliation`** (`materializer`, gated by
  `COMMERCE_CONTROL_PLANE_ENABLED`) — re-checks PENDING settlements against the
  tenant's RPC and advances the on-chain-final ones to SETTLED. Tenant-isolated,
  idempotent, kill-switch aware (skips SUSPENDED x402 capabilities), durable
  per-tenant cursor in `x402_reconciliation_cursor`.
- **`reward_reservation_release`** (`maintenance`) — returns stale,
  never-committed budget reservations to the tenant's available balance.
- **`reward_dlq_sweeper`** (`maintenance`) — samples reward-outbox dead-letter
  depth as a gauge; replay stays an explicit operator action.
- **`credential_expiry_sweep`** (`maintenance`) — tombstones expired PREVIOUS
  credential versions across tenants once their rotation-overlap window closes.

Every loop is cancellation-safe and isolates a failing tick (one bad tick logs
and continues rather than killing the supervised loop). The `/v1/ready`
component report (`services/gateway/component_status.py`) folds each plane's
worker roles into the `rewards`, `commerce`, and `provider_credentials`
component statuses, so an unsupervised or failed loop is observable rather than
silent.

## Production fail-closed rules

`Settings.__post_init__` (`config/settings.py`) enforces, at process start:

- **Every environment:** `AETHER_ROLE` must name a known role.
- **Staging & production:** `AETHER_ROLE=all` is rejected — run an explicit role.
- **Production:** `CACHE_BACKEND=memory` and `DATABASE_BACKEND=memory` are
  rejected — a memory backend is never a correctness source in production.

Local/dev keep the single-process default (`all`, memory cache) working.

## Remaining validation

The identity, graph, and measurement consumer boundaries are implemented and
covered by ownership tests. Broker-backed staging evidence for assignment,
processing lag, restart counts, and bounded deployment drain remains required;
the ledger therefore remains `implementation_in_progress` rather than claiming
production validation.
