---
title: Performance Baselines
slug: operations/performance-baselines
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Performance Baselines

Target latency/throughput baselines used as load-test thresholds. **Internal
objectives, not external SLAs** (see [SLO Tracking](SLO-TRACKING.md)).

| Surface | Baseline (p95) |
| --- | --- |
| GraphQL / query | < 200 ms |
| Audit export create | < 500 ms |
| Agent/dispatch task | p99 < 1000 ms |
| SDK ingestion latency | < 500 ms |
| Event → graph mutation | < 2000 ms |
| Recommendation generation | < 5000 ms |
| Action dispatch delivery | < 10000 ms |
| Error rate (under load) | < 1% |
| Concurrent-write data loss | 0 |

## Method

Run the Locust profiles ([Load Testing](LOAD-TESTING.md)) headless with `--csv`,
compare p50/p95/p99 against the table, and record regressions. Baselines map to
the internal SLOs surfaced in Kyber reliability. Update baselines deliberately
with infra changes; treat regressions as bugs.

See [Scale Testing](SCALE-TESTING.md) and [Reliability Operations](RELIABILITY-OPERATIONS.md).
