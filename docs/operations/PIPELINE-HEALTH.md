---
title: Pipeline Health
slug: reliability/pipeline-health
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "0.1.0"
source_files:
  - services/api/governance/reliability/definitions.py
  - services/api/governance/reliability/service.py
related:
  - reliability/operations
  - reliability/queue-worker-health
canonical_owner: platform@aether
estimated_read_minutes: 3
source_hashes:
  "services/api/governance/reliability/definitions.py": "sha256:c8fd781bb882c1306acf959751c9c4b7535227bc67544d6e41c4d72b6a33728e"
  "services/api/governance/reliability/service.py": "sha256:71fe39c503316a915a02f154dececd6385e7e07ed074ddea7ddb24915551d20c"
---
# Pipeline Health

`PipelineHealthService` tracks the platform's critical data pipelines end to end.

## Pipeline health model

| Field | Notes |
|---|---|
| `pipeline_key`, `label` | Identity |
| `source`, `destination` | Service endpoints |
| `status` | health status |
| `throughput_per_minute`, `latency_ms`, `error_rate` | flow metrics |
| `retry_count`, `dead_letter_count` | failure counters |
| `last_successful_run_at`, `freshness_seconds` | recency |
| `affected_tenant_count` | blast radius |

`freshness_seconds` is derived from `last_successful_run_at` when not explicitly
reported.

## Tracked pipelines

SDK ingestion → event store · event store → identity resolution · identity →
graph mutation · graph mutation → Profile360 · Profile360 → recommendation
generation · recommendation → decision/action lifecycle · action → dispatch ·
dispatch → outcome · outcome → confidence update · outcome → outcome ledger ·
usage event → billing metering · audit event → audit ledger · validated event →
semantic classification.

## APIs

- `GET /v1/admin/kyber/reliability/pipelines`

## Tenant-safe vs internal

Pipeline internals are **internal only**. Tenants see only a derived
`data_freshness` label, never pipeline keys, throughput, or dead-letter counts.

## Known gaps

- Metrics are reported via `report(pipeline_key, metrics)`; an automatic metric
  feed is planned.

## Rollout notes

- Pipelines seed lazily with `unknown` status.
