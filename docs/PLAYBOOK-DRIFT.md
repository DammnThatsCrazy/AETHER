---
title: Playbook Drift
slug: data/playbook-drift
section: data
visibility: I
audience: [ai, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
  - AETHER_PLAYBOOKS_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Playbook Drift

Tracks playbook health and performance drift: trigger rate, run count, success
rate, stale run rate, incomplete run rate, observed value trend, average
confidence delta, and (where available) manual override / rejection trends.

A drop in success rate or a rise in stale/incomplete runs produces a
`playbook_performance_drift` [Drift Event](DRIFT-DETECTION.md) scoped to the
affected playbook id.

Tenant report: `GET /v1/data-quality/playbooks`. Operator report:
`GET /v1/admin/kyber/intelligence-quality/playbooks`.

See [Playbooks](PLAYBOOKS.md) and [Data Quality](DATA-QUALITY.md).
