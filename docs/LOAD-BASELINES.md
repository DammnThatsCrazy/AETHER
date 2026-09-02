---
title: Load Baselines
slug: load-baselines
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.9.0"
source_files:
  - tests/load/thresholds.json
  - tests/load/locustfile.py
canonical_owner: platform@aether
estimated_read_minutes: 3
toc_depth: 2
last_synced_commit: "4e6fdad"
---

# Load Baselines

> Internal reference for staging load test thresholds and baseline results.
> Not customer-facing.

## SLA Thresholds

Defined in `tests/load/thresholds.json`. These are the acceptance criteria for
every staging load run before a production deployment.

| Endpoint | Metric | Threshold | Error Rate |
|----------|--------|-----------|------------|
| `POST /v1/ingest/events/batch` | p95 latency | ≤ 200 ms | ≤ 1% |
| `POST /sdk/identity/resolve` | p95 latency | ≤ 300 ms | ≤ 1% |
| `GET /v1/profile360/user/{id}` | p95 latency | ≤ 500 ms | ≤ 1% |
| `POST /v1/analytics/graphql` | p95 latency | ≤ 200 ms | ≤ 1% |
| `POST /v1/agent/tasks` | p99 latency | ≤ 1,000 ms | ≤ 1% |
| `POST /v1/fraud/evaluate` | p95 latency | ≤ 500 ms | ≤ 1% |
| `POST /v1/fraud/evaluate/batch` | p99 latency | ≤ 2,000 ms | ≤ 1% |
| `GET /v1/fraud/decisions` | p95 latency | ≤ 200 ms | ≤ 1% |
| `GET /v1/fraud/stats` | p95 latency | ≤ 100 ms | ≤ 1% |

## Running a Baseline

```bash
# Against staging (requires STAGING_URL env var)
make load-baselines
```

This runs Locust headless for 5 minutes with 50 users at 10 rps spawn rate
and writes CSV results to `tests/load/results/baseline_*.csv`.

## Recorded Baselines

Not yet recorded — run `make load-smoke` against staging to populate.

| Date | Endpoint | p95 / p99 ms | Error Rate | Result |
|------|----------|-------------|------------|--------|
| — | — | — | — | pending |

Once a staging run completes, commit the CSV from `tests/load/results/`
alongside an updated row in the table above and re-stamp this doc.
