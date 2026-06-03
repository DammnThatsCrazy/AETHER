---
title: Load Testing
slug: operations/load-testing
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Load Testing

Load tests run **separately from normal CI** (only a lightweight smoke runs in
the standard path). The harness is Locust (`tests/load/locustfile.py`) plus a
dependency-free synthetic generator (`tests/load/generate_synthetic.py`).

## Commands

```bash
npm run load:smoke        # generate synthetic data (no server) — CI-safe smoke
npm run load:gen          # python tests/load/generate_synthetic.py (NDJSON)
npm run load:ingestion    # locust against $AETHER_HOST (requires locust)
```

Direct: `locust -f tests/load/locustfile.py --host http://localhost:8000`
(headless: add `--headless -u <users> -r <ramp> -t <time> --csv results/load`).

## Profiles

The locustfile exercises GraphQL/query, export, agent-task, and campaign
workloads with steady-state, burst, and export-heavy user classes. The synthetic
generator produces tenant-scoped events for ingestion/profile/recommendation/
dispatch/audit-export/billing/tenant-isolation profiles.

## Safety

Never run load tests against production without authorization. Use a dedicated
load environment + synthetic tenants. See [Scale Testing](SCALE-TESTING.md),
[Stress-Test Scenarios](STRESS-TEST-SCENARIOS.md), and
[Performance Baselines](PERFORMANCE-BASELINES.md).
