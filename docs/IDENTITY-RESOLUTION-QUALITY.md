---
title: Identity Resolution Quality
slug: data/identity-resolution-quality
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

# Identity Resolution Quality

Tracks the health of identity resolution: merge rate, split rate, unresolved
entity rate, duplicate entity rate, identity confidence distribution,
wallet/email/device/account conflicts, identity graph churn, and (where
available) manual correction rate.

Sustained increases in unresolved or duplicate rates, or in cross-key conflicts,
produce `identity_resolution_drift`
[Drift Events](DRIFT-DETECTION.md). Cross-tenant identifiers are treated as a
contamination signal — see
[Tenant Data Contamination](TENANT-DATA-CONTAMINATION.md).

Tenant report: `GET /v1/data-quality/identity`. Operator report:
`GET /v1/admin/kyber/intelligence-quality/identity`.

See [Data Quality](DATA-QUALITY.md) and [Identity Resolution](IDENTITY-RESOLUTION.md).
