---
title: "ADR-006: Alembic Adoption of Raw-SQL Migrations"
slug: decisions/adr-006-alembic-adoption-of-raw-sql-migrations
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/alembic/versions/20260708_derivatives_foundation_adoption.py
canonical_owner: platform@aether
last_synced_commit: "4e6fdad"
---

# ADR-006: Alembic Adoption of Raw-SQL Migrations

**Status**: Accepted (8.12.0)

## Context

Derivatives PR1 anomalously shipped its 11-table DDL as a raw SQL file
(`Backend Architecture/migrations/2026_07_derivatives_foundation.sql`)
outside Alembic, which owns every other schema change. Environments may
or may not have executed that file.

## Decision

Adopt, don't fork: revision `20260708_derivatives_foundation_adoption`
replays the PR1 DDL verbatim as idempotent `CREATE TABLE IF NOT EXISTS`
(plus a unique-index equivalent for the COALESCE-based uniqueness), so
it is correct whether or not the raw file ran. Alembic owns the tables
from this revision forward. The downgrade is a deliberate no-op —
dropping possibly pre-existing production tables from an adoption
revision would be destructive. The raw SQL file is marked SUPERSEDED in
place (deleting it would break environments that reference it).

## Consequences

- One linear migration chain again; `alembic upgrade head` is
  sufficient for every environment.
- Future derivatives schema changes are normal Alembic revisions.
- The no-op downgrade means rolling back past adoption requires a
  manual, environment-aware decision — documented in
  MIGRATION_AND_BACKFILL.
