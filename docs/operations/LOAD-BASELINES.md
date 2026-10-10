---
title: Load Baselines
slug: load-baselines
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "0.1.0"
source_files:
  - tests/load/thresholds.json
  - tests/load/locustfile.py
canonical_owner: platform@aether
estimated_read_minutes: 3
toc_depth: 2
source_hashes:
  "tests/load/locustfile.py": "sha256:33a63220889f777908b0448dbefd56e9e9902393cd215c69ac79f208551525c2"
  "tests/load/thresholds.json": "sha256:aee0927999630736a9eb307900b102bf1548600d9814caa262a49591902a4fd0"
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
# Against staging: pass the reviewed API origin and a run-scoped tenant key.
# The key is never written to the CSV evidence.
AETHER_LOAD_API_KEY="$RUN_SCOPED_TENANT_API_KEY" \
  make load-baselines STAGING_URL="$AETHER_API_URL"
```

This runs Locust headless for 5 minutes with 50 users at 10 rps spawn rate
and writes CSV results to `tests/load/results/baseline_*.csv`. Every request
uses `AETHER_LOAD_API_KEY` through the `X-API-Key` header; the deterministic
`test-key-*` fallback is for local-only runs and is not staging evidence.

Every task set yields back to its Locust user (`interrupt()`), so each user
keeps re-drawing from its weighted task sets. Without that, a user stays in
the first set it draws: a short `make load-smoke` run can miss whole request
types and fail with "configured threshold never appeared", and if only some
sets yielded, mixed users would drain into the rest and skew the baseline mix.

## Recorded Baselines

Not yet recorded — run `make load-smoke` against staging to populate.

| Date | Endpoint | p95 / p99 ms | Error Rate | Result |
|------|----------|-------------|------------|--------|
| — | — | — | — | pending |

Once a staging run completes, commit the CSV from `tests/load/results/`
alongside an updated row in the table above and run
`make docs-generate-changed` after reviewing this doc's declared sources.
