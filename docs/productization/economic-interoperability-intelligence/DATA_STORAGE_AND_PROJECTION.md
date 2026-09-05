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
last_synced_commit: "b89edb3f"
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

The card-linked payment rail slice adds `CardLinkedProjector`
(`card_linked_flow_facts`), registered after the economic projectors in
`_ALL_PROJECTORS` — it observes card-context SDK events after every
canonical economic projector has run and is never the canonical-activity
owner for an event. (The Social Silver plane's six observation-only
social projectors are registered after it; they too are never
canonical-activity owners.)

`_ALL_PROJECTORS` is not the whole of what the dispatcher does per
result. After each successful projection it also fires **out-of-band,
fire-and-forget hooks** via `asyncio.create_task`: `SilverGraphProjector.
maybe_emit` (graph mutations) and `CapabilityCatalogService.maybe_record`
(the agent-access capability inventory). These are deliberately **not**
projectors — they are absent from `_ALL_PROJECTORS` and from the
projector-ownership registry, never own canonical activity, and swallow
their own errors so they can neither block nor fail a Silver write. The
trade-off is explicit: a dropped task is a missed derived-read-model
update, never a lost fact. Silver remains the system of record, and a
derived read-model is rebuildable from it.

## Gold

ClickHouse `ReplacingMergeTree` DDL modules:
`gold_stablecoin_flows`, `gold_derivatives_exposure`,
`gold_interop_paths` — `Decimal(38,18)` columns and
`model_training_eligible = 0` on every row. Materialization goes through
`GoldRepository.materialize` from flows/pnl/correlation code. ClickHouse
execution is deferred (no instance in CI) — DDL is validated by
inspection tests only.
