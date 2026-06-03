---
title: Graph Quality
slug: data/graph-quality
section: data
visibility: I
audience: [ai, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Graph Quality

Monitors the health of graph mutation: vertex and edge creation/deletion rates,
edge-type distribution, orphaned vertices, dangling edges, unexpected
relationship spikes, missing expected edges, graph density drift, degree
distribution drift, and cluster/community drift.

Anomalies (e.g. a spike in dangling edges or a collapse in expected edges)
produce `graph_mutation_drift` [Drift Events](DRIFT-DETECTION.md).

Tenant report: `GET /v1/data-quality/graph`. Operator report:
`GET /v1/admin/kyber/intelligence-quality/graph`.

See [Data Quality](DATA-QUALITY.md) and
[Graph Intelligence Reliability](GRAPH-INTELLIGENCE-RELIABILITY.md).
