---
title: "ADR-005: Typed Financial Repositories over JSONB"
slug: decisions/adr-005-typed-financial-repositories
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/repositories/typed_repo.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# ADR-005: Typed Financial Repositories over JSONB

**Status**: Accepted (8.12.0)

## Context

The platform's `BaseRepository` stores rows as JSONB documents. The
derivatives PR1 DDL (and the new stablecoin/interop DDL) enforce
NUMERIC(38,18) amounts, `CHECK (execution_by_aether = FALSE)`, and
`UNIQUE(tenant_id, idempotency_key)` at the column level. Routing
financial rows through JSONB would forfeit those database-level
guarantees and coerce Decimals through JSON floats.

## Decision

Introduce `TypedTableRepository` (`repositories/typed_repo.py`):
explicit column specs per table, Decimal-preserving reads/writes,
asyncpg inserts with `ON CONFLICT (tenant_id, idempotency_key) DO
NOTHING` in staging/prod, shared in-memory list stores locally, and
`as_decimal()` that rejects binary floats. All three economic domains
use it; non-financial platform data stays on `BaseRepository`.

## Consequences

- Schema changes now require touching both the Alembic revision and the
  repo column spec (deliberate friction for financial tables).
- Idempotency is structural, so replays and retries are safe by default.
- The in-memory local mode makes the entire domain testable without
  Postgres (used by the gated suite).
