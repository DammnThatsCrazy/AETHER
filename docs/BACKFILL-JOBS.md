---
title: Backfill Jobs
slug: data/backfill-jobs
section: data
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Backfill Jobs

Backfills re-derive or repopulate data after a schema change, a new feature, or a
correction. They are tenant-scoped, idempotent, and resumable.

## Pattern

1. **Scope**: select the tenants + resource + time window.
2. **Idempotency**: key by `(tenant_id, resource_id)` so re-runs don't duplicate
   (the metering layer already dedupes by `source_type/source_id/event_type`).
3. **Throttle**: bound throughput to protect the live path; run off-peak.
4. **Observe**: emit progress + a final reconciliation count; record an audit
   event for sensitive backfills.
5. **Verify**: re-run the relevant data-quality checks (see [Data Quality](DATA-QUALITY.md)).

## Examples

- Backfill OODA usage dimensions (e.g. historical `connector_sync`) into the
  metering store.
- Recompute Profile360 after an identity-resolution fix.
- Re-derive value-created events for a contract switched to value-based billing.

Backfills must respect retention + legal holds — see [Data Retention](DATA-RETENTION.md).
See [Data Migrations](DATA-MIGRATIONS.md) and [Data Durability](DATA-DURABILITY.md).
