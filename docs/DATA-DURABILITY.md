---
title: Data Durability
slug: data/data-durability
section: data
visibility: I
audience: [architect, ops, dev-senior]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Data Durability

Every subsystem has an explicit storage + durability posture. Locally all
repositories run in-memory (`BaseRepository`); in staging/production they back
PostgreSQL (asyncpg), with the graph on Neptune and analytics on ClickHouse
where enabled.

## Storage map

| Domain | Store | Migration | Retention |
| --- | --- | --- | --- |
| OODA: recommendations/decisions/actions/dispatches/outcomes | PostgreSQL | alembic | per policy |
| Outcome ledger, playbooks | PostgreSQL | alembic | per policy |
| Billing/RevOps (contracts, usage, invoices, value) | PostgreSQL | `billing_tables`, `usage_tables` | preserve (billing) |
| Governance/security audit ledger | PostgreSQL | alembic | preserve (audit) |
| Reliability, data-quality, drift | PostgreSQL (in-memory local) | add revisions before prod | per policy |
| Connectors, integration configs | PostgreSQL (in-memory local) | add revisions | per policy |
| Secrets refs | secret manager / vault | n/a | rotate |
| Demo data | synthetic (MSW/in-memory) | n/a | ephemeral |

## Guarantees

- **Audit logs and billing records are never hard-deleted** when retention
  requires preservation.
- Tenant deletion / DSR erasure is governed (retention + legal holds) — see
  [Data Retention](DATA-RETENTION.md).
- Backups + restore drills — see [Backup & Restore](BACKUP-RESTORE.md).

See [Data Migrations](DATA-MIGRATIONS.md) and [Backfill Jobs](BACKFILL-JOBS.md).
