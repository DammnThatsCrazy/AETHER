---
title: Reconciliation and Financial Correctness
slug: productization/economic-interoperability-intelligence/reconciliation-and-financial-correctness
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/derivatives/runtime_reconciliation.py
  - Backend Architecture/aether-backend/services/derivatives/pnl.py
  - Backend Architecture/aether-backend/services/stablecoin/finality.py
  - Backend Architecture/aether-backend/services/interop/lifecycle.py
canonical_owner: platform@aether
last_synced_commit: "4e6fdad"
---

# Reconciliation and Financial Correctness

## Decimal discipline

NUMERIC(38,18) columns; `TypedTableRepository` preserves `Decimal`
end-to-end; `as_decimal()` rejects floats; TS validators reject float
and exponent string forms; a model-introspection test asserts no
canonical model field is a float.

## Derivatives

Snapshot-to-snapshot reconciliation only — fills are never re-derived,
so order/fill/position double counting is structurally impossible.
Variances (size, realized/unrealized P&L, balance) append with severity
and tolerance `1e-12`; P&L supports average-entry and venue-reported
methods and labels which was used.

## Stablecoin

Deterministic observation identity dedupes replays; finality checkpoints
gate `finalized`; reorgs demote only non-finalized rows and append
corrections; flow aggregates are versioned (`metric_version`) so
recomputation never silently overwrites history.

## Interoperability

The lifecycle FSM encodes legal retry/recovery regressions explicitly;
terminal states are immutable; late evidence attaches without status
regression; reorged messages re-derive from surviving evidence. The
append-only `interop_message_events` log is the audit trail — the
current-state row is always reconstructible from it.
