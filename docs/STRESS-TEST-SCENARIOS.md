---
title: Stress-Test Scenarios
slug: operations/stress-test-scenarios
section: operations
visibility: I
audience: [ops, dev-senior]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Stress-Test Scenarios

Adversarial scenarios to validate resilience. The synthetic generator
(`tests/load/generate_synthetic.py --scenario <name>`) produces the inputs.

| Scenario | Generator | Expected behavior |
| --- | --- | --- |
| Duplicate event spike | `duplicate_spike` | Idempotency dedupes; no double-count |
| Schema drift | `schema_drift` | Drift detected + surfaced; no crash |
| Out-of-order events | `out_of_order` | Timestamps honored; freshness tracked |
| High-cardinality identities | `high_cardinality` | Identity resolution bounded |
| Queue backlog | (sustained load) | Backpressure; queue health degraded, not lost |
| Failed integration retries | (force failures) | Retry/backoff; failure telemetry + alerts |
| Large audit export | (big window) | Export completes or degrades gracefully |
| High outcome / recommendation / playbook volume | (volume) | SLOs tracked; no isolation breach |

Each scenario should leave **tenant isolation intact**, surface health in Kyber
reliability/data-quality, and never leak secrets or cross-tenant data.

See [Load Testing](LOAD-TESTING.md), [Scale Testing](SCALE-TESTING.md),
[Drift Detection](DRIFT-DETECTION.md), and [Queue & Worker Health](QUEUE-WORKER-HEALTH.md).
