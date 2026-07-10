---
title: Data Storage and Projection
slug: productization/economic-interoperability-intelligence/data-storage-and-projection
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/repositories/typed_repo.py
  - Backend Architecture/aether-backend/services/silver/dispatcher.py
  - Data Lake Architecture/schemas/gold_stablecoin_flows.py
  - Data Lake Architecture/schemas/gold_derivatives_exposure.py
  - Data Lake Architecture/schemas/gold_interop_paths.py
canonical_owner: platform@aether
last_synced_commit: "03ab3a6"
---

# Data Storage and Projection

## Bronze/operational — typed repositories

`repositories/typed_repo.py::TypedTableRepository`: explicit column
specs, Decimal-preserving round trips, asyncpg with
`ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` in staging/prod,
shared in-memory stores locally. Chosen over JSONB `BaseRepository`
because the PR1 DDL already enforces NUMERIC(38,18) and CHECK
constraints that JSONB would forfeit (ADR-005).

## Silver

Three projectors (`stablecoin`, `derivatives`, `interop`) subclass
`BaseProjector` with registry-derived `handles`, registered in the
dispatcher after `X402FlowProjector` and before `SilverGraphProjector`;
`SilverFactWriter` provides idempotent writes and drops unknown columns.

## Gold

ClickHouse `ReplacingMergeTree` DDL modules:
`gold_stablecoin_flows`, `gold_derivatives_exposure`,
`gold_interop_paths` — `Decimal(38,18)` columns and
`model_training_eligible = 0` on every row. Materialization goes through
`GoldRepository.materialize` from flows/pnl/correlation code. ClickHouse
execution is deferred (no instance in CI) — DDL is validated by
inspection tests only.
