---
title: Queue & Worker Health
slug: reliability/queue-worker-health
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/reliability/definitions.py
  - Backend Architecture/aether-backend/services/reliability/service.py
related:
  - reliability/operations
  - reliability/pipeline-health
canonical_owner: platform@aether
estimated_read_minutes: 3
last_synced_commit: 401ceb7
---
# Queue & Worker Health

`QueueHealthService` tracks queue depth and worker health for the platform's
background processing surfaces. Because no unified queue broker abstraction
exists yet, records are seeded locally and updated through an adapter
`report(queue_key, metrics)` interface (mock/local until a live broker is wired).

## Queue health model

| Field | Notes |
|---|---|
| `queue_key`, `label` | Identity |
| `status` | `healthy`/`degraded`/`critical`/`offline`/`unknown` |
| `depth` | Messages waiting |
| `oldest_message_age_seconds` | Age of oldest message |
| `worker_count` / `active_worker_count` | Worker fleet + active |
| `retry_count` / `dead_letter_count` | Failure counters |
| `processing_latency_ms` | Per-message processing time |

## Tracked queues

graph mutations · recommendation generation · action dispatch · audit export
generation · billing metering · customer success triggers · governance evidence
packs.

## APIs

- `GET /v1/admin/kyber/reliability/queues`

## Tenant-safe vs internal

Queue/worker health is **internal only** and is never exposed on any tenant
route — verified by no-leakage tests.

## Known gaps

- Metrics are adapter/mock-seeded; live broker integration is planned.

## Rollout notes

- Queue records seed lazily with `unknown` status and zero depth.
