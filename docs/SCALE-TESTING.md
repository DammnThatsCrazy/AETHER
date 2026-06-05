---
title: Scale Testing
slug: operations/scale-testing
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Scale Testing

Scale tests validate behavior as tenant count and data volume grow.

## Dimensions

```bash
# tenants
python tests/load/generate_synthetic.py --tenants 10  --events 1000000
python tests/load/generate_synthetic.py --tenants 100 --events 10000000
# high-cardinality identities
python tests/load/generate_synthetic.py --scenario high_cardinality --events 1000000
```

| Axis | Targets |
| --- | --- |
| Tenants | 10 → 100 |
| Events | 1M → 10M |
| Identities | high-cardinality unique users |
| Volume | recommendation / outcome / playbook-run spikes |

## What to watch

Tenant isolation holds under load; per-tenant rate limits + quotas enforce; graph
mutation + identity resolution keep up (freshness SLOs); billing metering stays
accurate; audit ledger throughput. Feed results to Kyber reliability +
data-quality (see [Reliability Operations](RELIABILITY-OPERATIONS.md),
[Data Quality](DATA-QUALITY.md)).

See [Load Testing](LOAD-TESTING.md) and [Performance Baselines](PERFORMANCE-BASELINES.md).
