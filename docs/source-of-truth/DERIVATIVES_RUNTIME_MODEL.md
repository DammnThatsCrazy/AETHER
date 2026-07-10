---
title: Derivatives Runtime Model
slug: source-of-truth/derivatives-runtime-model
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/derivatives/state_machines.py
  - Backend Architecture/aether-backend/services/derivatives/streams.py
  - Backend Architecture/aether-backend/services/derivatives/reconciliation.py
  - Backend Architecture/aether-backend/services/derivatives/pnl.py
  - Backend Architecture/aether-backend/services/derivatives/adapters/base.py
  - Backend Architecture/aether-backend/services/derivatives/adapters/simulator.py
  - Backend Architecture/aether-backend/services/derivatives/adapters/conformance.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
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
payloads, FSM-legal orderings, and `execution_by_aether == false`.

## Streams (`streams.py`)

Per-(venue, market, channel) sequence tracking with a bounded buffer.
A gap opens when the hole exceeds the threshold → `StreamGapRepo` row +
`derivatives_stream_gap_detected` (event + meter) + backfill request.
Recovery requires progression past the revealing sequence. Kafka
provisioning is deferred; the local transport is asyncio.

## Reconciliation & P&L

`reconciliation.py` compares venue-reported snapshots against projected
state (size, realized/unrealized P&L, balance) and appends variances —
fills are never re-derived, so double counting is structurally
impossible. `pnl.py` computes Decimal realized/unrealized and exposure
(average-entry and venue-reported methods); nothing in the canonical
models is a binary float.
