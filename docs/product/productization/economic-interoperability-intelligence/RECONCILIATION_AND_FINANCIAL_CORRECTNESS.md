---
title: Reconciliation and Financial Correctness
slug: productization/economic-interoperability-intelligence/reconciliation-and-financial-correctness
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/api/value/derivatives/runtime_reconciliation.py, services/api/value/derivatives/pnl.py, services/api/value/stablecoin/finality.py, services/api/graph/interop/lifecycle.py]
canonical_owner: platform@aether
source_hashes:
  "services/api/graph/interop/lifecycle.py": "sha256:fe1ed1b1ac51f233cc21cad9aa9aeb3af2f1b3721bcdad1a4b2a0a0ebfc8a759"
  "services/api/value/derivatives/pnl.py": "sha256:349600f38d611b92cdd51bb28c1f8747cc57b88e43de9e7ea90d3face1aa8d33"
  "services/api/value/derivatives/runtime_reconciliation.py": "sha256:2a6d91a88ff5b9da68a891ec5ca5725c9e896e6a2dab3971f0c851520c9d38d0"
  "services/api/value/stablecoin/finality.py": "sha256:c6c38565444a6ba7fc8204e6485a103cfea4bf16b7ee9ffc8a3384165d2f29d7"
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
