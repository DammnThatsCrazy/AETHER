---
title: Migrations
slug: ops-migrations
section: operations
visibility: I
audience: [dev-senior, ops]
status: experimental
since_version: "0.1.0"
---

# Migrations

## Overview

Database migrations for the Aether platform use Alembic for the Python
backend and standard migration tooling for service-specific stores.

## Running Migrations

```bash
# Apply all pending migrations
python scripts/run_migrations.py

# Check migration status
python scripts/run_migrations.py --status
```

## Migration Naming

Migrations follow the pattern: `YYYYMMDD_description`

Example: `20260713_card_linked_payments`

## Migration Safety Rules

- Migrations must be backwards-compatible (no column drops without a
  deprecation migration first).
- Large table alterations must use online DDL or background migration.
- All migrations must be tested against a snapshot of staging data.
- Migrations that add NOT NULL columns must include a default or
  backfill step.

## Rollback

Each migration must include a reverse operation. To rollback:

```bash
python scripts/run_migrations.py --rollback MIGRATION_NAME
```

## Current State

Migration tooling is in place. See individual service directories for
their migration histories.
