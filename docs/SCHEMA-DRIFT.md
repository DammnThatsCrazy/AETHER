---
title: Schema Drift
slug: data/schema-drift
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

# Schema Drift

Schema stability is monitored on inbound SDK events. The detector classifies
changes as `field_removed`, `field_added`, `field_type_changed`,
`enum_value_changed`, `required_field_missing`, `timestamp_format_changed`,
`identity_key_changed`, or `payload_shape_changed`.

Additive, backward-compatible changes (e.g. a new optional field) are low
severity and informational. Removals, type changes, and missing required or
identity fields raise higher-severity `schema_drift`
[Drift Events](DRIFT-DETECTION.md) with a recommended action (pin schema version,
coordinate an SDK hotfix, drain the dead-letter queue after the fix).

The tenant-facing report is available at `GET /v1/data-quality/schema`; the
operator view at `GET /v1/admin/kyber/intelligence-quality/schema-drift`.

See [Event quality and Data Quality](DATA-QUALITY.md).
