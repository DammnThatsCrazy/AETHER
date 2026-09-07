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
source_hashes:
  "Backend Architecture/aether-backend/services/derivatives/pnl.py": "sha256:349600f38d611b92cdd51bb28c1f8747cc57b88e43de9e7ea90d3face1aa8d33"
  "Backend Architecture/aether-backend/services/derivatives/runtime_reconciliation.py": "sha256:bf32bd026c4a4a03f3c7d74481b72db4527028b9543b28fa2f59c1da7b140f95"
  "Backend Architecture/aether-backend/services/interop/lifecycle.py": "sha256:336cf9da3f46ec6364bb47b23761292cf2fa52bb0cebdecb12ac20a209163090"
  "Backend Architecture/aether-backend/services/stablecoin/finality.py": "sha256:409db86b1b06aa9896b256acd4dc41cf9d358db48632cdb89f2b317599ff6a46"
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
