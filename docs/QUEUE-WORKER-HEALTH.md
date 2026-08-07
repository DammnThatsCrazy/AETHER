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
last_synced_commit: "559be979"
---
# Queue & Worker Health

`QueueHealthService` tracks queue depth and worker health for the platform's
background processing surfaces. Because no unified queue broker abstraction
exists yet, records are seeded locally and updated through an adapter
`report(queue_key, metrics)` interface (mock/local until a live broker is wired).

Reported metrics are self-attestation — there is no real queue abstraction
observing them directly. `evaluate_queue_health` derives an *honest* verdict
from them: no workload signal and no worker/processing signal means the queue
was not observed at all, so it reports `unknown` / `no_coverage` (absence of
errors is not evidence of health); a self-reported `healthy` is never certified
and collapses to `unknown` with `unverified=true`; only self-reported *problem*
statuses (`degraded`/`critical`/`offline`) pass through. `list()` and `report()`
layer the verdict on every stored record and never mutate the caller's metrics
dict.

## Queue health model

| Field | Notes |
|---|---|
| `queue_key`, `label` | Identity |
| `status` | Honest verdict: `degraded`/`critical`/`offline` (self-reported problems pass through) or `unknown`. A self-reported `healthy` is **never certified** — it collapses to `unknown` with `unverified=true`. |
| `depth` | Messages waiting |
| `oldest_message_age_seconds` | Age of oldest message |
| `worker_count` / `active_worker_count` | Worker fleet + active |
| `retry_count` / `dead_letter_count` | Failure counters |
| `processing_latency_ms` | Per-message processing time |
| `verification` | `self_reported` after a `report()`; `unobserved` for rows never reported against |
| `unverified` | `true` — health is self-attestation, never directly observed |
| `coverage` / `coverage_reason` | Observation evidence: `covered`, `no_coverage`, or `self_reported_problem`, plus why |
| `reported_status` | The raw self-reported status, before the honesty verdict is layered on |

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
