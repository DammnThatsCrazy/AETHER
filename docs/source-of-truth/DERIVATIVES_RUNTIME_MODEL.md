---
title: Derivatives Runtime Model
slug: source-of-truth/derivatives-runtime-model
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: 0.1.0
source_files: [services/backend/services/derivatives/state_machines.py, services/backend/services/derivatives/streams.py, services/backend/services/derivatives/runtime_reconciliation.py, services/backend/services/derivatives/pnl.py, services/backend/services/derivatives/materializer.py, services/backend/services/derivatives/adapters/base.py, services/backend/services/derivatives/adapters/simulator.py, services/backend/services/derivatives/adapters/conformance.py]
canonical_owner: platform@aether
last_synced_commit: 03ab3a6
---

# Derivatives Runtime Model

The 8.12.0 runtime implements the PR1 (#395) contract foundation. It is
observation-only: adapters assert `authority_type == "read_only"` and no
code path constructs, signs, or transmits an order.

## State machines (`state_machines.py`)

Order and Position FSMs with explicit `LEGAL_TRANSITIONS` maps and
monotonic status ranks. Legal transitions always apply; out-of-order
lower-rank evidence attaches without status regression; corrections are
new rows, never mutations.

## Adapters (`adapters/`)

`DerivativesAdapter` ABC with an honest `ImplementationStatus` descriptor.
The deterministic seeded simulator is `MOCKED_LOCAL`; no venue adapter
claims `PROVIDER_LIVE` without live validation. `run_conformance()`
verifies checkpoint monotonicity, idempotent replay, Decimal-only
payloads, canonical event names, and `execution_by_aether == false`. It does not exercise the order/position FSMs.

## Streams (`streams.py`)

Per-(venue, market, channel) sequence tracking with a bounded buffer.
A gap opens when the hole exceeds the threshold → `StreamGapRepo` row +
`derivatives_stream_gap_detected` (event + meter) + backfill request.
Recovery requires progression past the revealing sequence. Kafka
provisioning is deferred; the local transport is asyncio.

## Reconciliation & P&L

`runtime_reconciliation.py` compares venue-reported snapshots against projected
state (size, realized/unrealized P&L, balance) and appends variances —
fills are never re-derived, so double counting is structurally
impossible. `pnl.py` computes Decimal realized/unrealized and exposure
(average-entry and venue-reported methods); nothing in the canonical
models is a binary float.

## Materializer (`materializer.py`)

The `derivatives_position_materializer` worker (role `materializer`; runs only
when `AETHER_DERIVATIVES_RUNTIME_ENABLED` and at least one of
`AETHER_DERIVATIVES_PNL_ENABLED` / `AETHER_DERIVATIVES_RECONCILIATION_ENABLED` is
on) replays each tenant's stored fills per (account, market) through
`position_engine.apply_fill` and writes, idempotently:

- closed position epochs (insert-only; an open epoch is never written, since the
  table has no `updated_at`);
- one P&L snapshot per change in the last fill, the latest mark observation or the
  open size, carrying `evidence.mark_price_available`; with no mark the
  unrealized figure is not claimed;
- a variance for each field where the replayed position disagrees with the
  venue's latest reported position (`<field>_mismatch`), keyed on the values so an
  unchanged disagreement is stored once.

A fill the engine cannot apply is skipped and counted, never fatal. Intake
(`POST /v1/derivatives/runtime/observations`) classifies each order/position
status against the furthest status already held (`first_observation`,
`advanced`, `reapplied`, `duplicate`, `stale`, `rejected_transition`) in the
response; the observation is stored either way. The kyber
`fleet` / `data-quality` / `graph-quality` routes report counters computed from
the durable tables, and `GET /v1/admin/kyber/derivatives/runtime/topic-contract`
reports the validation state of the declared stream-topic contract.

Still unwired: the entitlement guard (`guards.py`), the usage-meter sink
(`meter.py`) and the graph projections (`graph_mutations.py`); the first two wait
on a plan-entitlement resolver and a durable metering authority.
