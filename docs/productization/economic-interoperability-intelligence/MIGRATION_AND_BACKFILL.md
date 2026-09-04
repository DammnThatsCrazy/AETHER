---
title: Migration and Backfill
slug: productization/economic-interoperability-intelligence/migration-and-backfill
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/alembic/versions/20260708_derivatives_foundation_adoption.py
  - Backend Architecture/aether-backend/alembic/versions/20260708_derivatives_runtime.py
  - Backend Architecture/aether-backend/alembic/versions/20260708_stablecoin_intelligence.py
  - Backend Architecture/aether-backend/alembic/versions/20260708_interop_intelligence.py
canonical_owner: platform@aether
last_synced_commit: "4e6fdad"
---

# Migration and Backfill

## Migrations (chained from main's head `20260712_ops_runtime` after the #404–#416 merge)

1. `20260708_derivatives_foundation_adoption` — replays PR1's raw-SQL
   tables as idempotent `CREATE TABLE IF NOT EXISTS`; Alembic owns them
   henceforth. Downgrade is intentionally a no-op (adoption of possibly
   pre-existing production tables must not drop them). The raw SQL file
   is marked SUPERSEDED. See ADR-006.
2. `20260708_derivatives_runtime` — strategy/economics/market-state
   tables + `silver_derivatives_facts`.
3. `20260708_stablecoin_intelligence` — 8 domain tables +
   `silver_stablecoin_facts`.
4. `20260708_interop_intelligence` — 13 domain tables +
   `silver_interop_facts`.

All tables: `tenant_id TEXT NOT NULL`, NUMERIC(38,18) amounts,
`UNIQUE(tenant_id, idempotency_key)`, `CHECK (execution_by_aether =
FALSE)` where applicable, TIMESTAMPTZ audit columns, tenant-scoped
indexes, full downgrades (except the adoption revision).

## Backfill

No historical backfill ships in 8.12.0. When enabled in staging:
stablecoin/interop scanning is checkpoint-driven, so backfill = seeding
checkpoints at a historical block and letting governed scans walk
forward (idempotent identity makes re-scans safe); derivatives backfill
replays adapter snapshots (conformance guarantees idempotent replay).
