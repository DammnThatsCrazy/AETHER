---
title: Data Migrations
slug: data/data-migrations
section: data
visibility: I
audience: [dev-senior, ops, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Data Migrations

Schema migrations use **Alembic**
(`Backend Architecture/aether-backend/alembic/`). Locally the backend runs on
in-memory repositories; staging/production use PostgreSQL via asyncpg.

## Apply

```bash
alembic upgrade head        # against DATABASE_URL (or -x db_url=...)
alembic downgrade -1        # revert one revision
```

## Authoring

- One revision per change; name `YYYYMMDD_<rev>_<slug>.py`.
- Each migration defines `revision`, `down_revision`, `upgrade()`, `downgrade()`.
- Ruff auto-lints on creation (configured in `alembic.ini`).
- A CI smoke test (`tests/unit/test_migrations_smoke.py`) statically verifies
  every migration is well-formed (revision identity + reversible up/down) without
  a database.

## New tables in this productization pass

Connectors (`integration_connector_configs`), data-quality
(`data_quality_scores`, `data_quality_drift_events`), and reliability tables are
created by repositories in-memory locally; add Alembic revisions for them before
enabling the corresponding flags in production.

See [Backfill Jobs](BACKFILL-JOBS.md), [Backup & Restore](BACKUP-RESTORE.md),
[Data Durability](DATA-DURABILITY.md), and [Migration Runbook](MIGRATION-RUNBOOK.md).
