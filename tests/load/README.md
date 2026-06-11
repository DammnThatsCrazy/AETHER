# Load & Soak Testing

## Quick Start

```bash
pip install locust
locust -f tests/load/locustfile.py --host http://localhost:8000
```

Open http://localhost:8089 to control the test.

## Synthetic Baseline (no external services required)

Run without any running Aether instance — uses an in-process mock server:

```bash
# Default: 500 requests per scenario, concurrency 8
python tests/load/synthetic_baseline.py

# Custom volume
python tests/load/synthetic_baseline.py --requests 1000 --concurrency 10

# Override p95 threshold for all scenarios
python tests/load/synthetic_baseline.py --requests 500 --p95-threshold-ms 150
```

Output:
- Human-readable latency table on stdout
- `tests/load/baseline_results.json` — machine-readable results

Exit codes:
- `0` — all p95 latencies are below threshold
- `1` — at least one p95 latency exceeded threshold (scale concern)

## Headless Mode (CI / Staging)

```bash
# Steady-state: 50 users, 10/s ramp, 5 minutes
locust -f tests/load/locustfile.py --host http://localhost:8000 \
       --headless -u 50 -r 10 --run-time 5m \
       --csv results/steady-state

# Burst: 200 users, 50/s ramp, 2 minutes
locust -f tests/load/locustfile.py --host http://localhost:8000 \
       --headless -u 200 -r 50 --run-time 2m \
       --csv results/burst \
       --class-picker BurstUser

# Soak: 20 users, slow ramp, 30 minutes
locust -f tests/load/locustfile.py --host http://localhost:8000 \
       --headless -u 20 -r 2 --run-time 30m \
       --csv results/soak

# Ingest-heavy: batch ingest + identity resolution at peak volume
locust -f tests/load/locustfile.py --host http://localhost:8000 \
       --headless -u 100 -r 20 --run-time 10m \
       --csv results/ingest-heavy \
       --class-picker IngestHeavyUser

# Operator dashboard: Kyber summaries + Profile360
locust -f tests/load/locustfile.py --host http://localhost:8000 \
       --headless -u 20 -r 5 --run-time 10m \
       --csv results/operator \
       --class-picker OperatorUser
```

## Staging Load Test

Full signoff run against a staging environment:

```bash
export AETHER_STAGING_HOST=https://staging.aether.internal

# 1. Warm up
locust -f tests/load/locustfile.py --host $AETHER_STAGING_HOST \
       --headless -u 10 -r 2 --run-time 2m

# 2. Steady-state signoff
locust -f tests/load/locustfile.py --host $AETHER_STAGING_HOST \
       --headless -u 50 -r 10 --run-time 5m \
       --csv results/staging-signoff-$(date +%Y%m%d)

# 3. Burst signoff
locust -f tests/load/locustfile.py --host $AETHER_STAGING_HOST \
       --headless -u 200 -r 50 --run-time 2m \
       --csv results/staging-burst-$(date +%Y%m%d)
```

Compare CSV output against thresholds in `tests/load/thresholds.json`.

## Threshold Definitions

Canonical thresholds live in `tests/load/thresholds.json`. Summary:

| Endpoint | p95 threshold | p99 threshold | Max error rate |
|----------|--------------|--------------|----------------|
| `/v1/ingest/batch` | 200ms | — | 1% |
| `/v1/resolution/resolve` | 300ms | — | 1% |
| `/v1/profile/profile360` | 500ms | — | 1% |
| `/v1/analytics/graphql` | 200ms | — | 1% |
| `/v1/agent/tasks` | — | 1000ms | 1% |

Additional staging signoff criteria:
- Zero data loss on concurrent touchpoint writes
- Memory growth < 20% over 30-minute soak (check for store leaks / missing TTL eviction)

## User Profiles

| Profile | Use Case | Recommended Users | Wait |
|---------|----------|-------------------|------|
| `SteadyStateUser` | Normal production mix across all subsystems | 50 | 0.5–2.0s |
| `BurstUser` | Spike traffic (GraphQL + agent tasks + batch ingest) | 200 | 0.1–0.5s |
| `ExportHeavyUser` | Export idempotency stress | 20 | 0.2–1.0s |
| `IngestHeavyUser` | SDK batch flush pattern (ingest + identity) | 100 | 0.05–0.3s |
| `OperatorUser` | Operator dashboard (Kyber summaries + Profile360) | 20 | 1.0–3.0s |

## Task Sets

| Task Set | Endpoint(s) | What It Validates |
|----------|-------------|-------------------|
| `GraphQLTasks` | `/v1/analytics/graphql` | Resolver performance, field projection, security rejections |
| `ExportTasks` | `/v1/analytics/export` | Job creation, idempotency, status polling, 404 handling |
| `AgentTaskTasks` | `/v1/agent/tasks`, `/v1/agent/audit` | UUID generation, lock contention, audit append, read-after-write |
| `BatchIngestTasks` | `/v1/ingest/batch`, `/v1/ingest/feed` | High-volume ingest, duplicate handling, schema validation |
| `IdentityResolveTasks` | `/v1/resolution/resolve`, `/v1/sdk/batch` | Multi-anchor merge, anonymous→known resolution latency SLA |
| `Profile360Tasks` | `/v1/profile/profile360` | Operator queries, intelligence windows, tenant isolation |
| `KyberSummaryTasks` | `/v1/admin/kyber/*` | Operator dashboard throughput, tenant list, SDK fleet health |
| `CampaignTasks` | `/v1/campaigns`, `/v1/campaigns/{id}/touchpoints` | Write/read-after-write consistency, attribution model computation |

## Baseline Artifact Format

`tests/load/baseline_results.json` schema:

```json
{
  "version": "1.0",
  "timestamp": "<ISO-8601 UTC>",
  "config": {
    "requests_per_scenario": 500,
    "concurrency": 8
  },
  "results": [
    {
      "scenario": "/v1/ingest/batch",
      "requests": 500,
      "errors": 0,
      "error_rate": 0.0,
      "rps": 142.3,
      "p50_ms": 5.8,
      "p95_ms": 9.2,
      "p99_ms": 11.4,
      "threshold_ms": 200,
      "passed": true,
      "elapsed_s": 3.51
    }
  ],
  "overall_passed": true
}
```

Each result entry corresponds to one scenario (one endpoint). `passed` is `true` when `p95_ms < threshold_ms`.
