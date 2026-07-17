---
title: Temporal Observatory & Decision Memory Source of Truth
status: stable
source_files:
  - packages/shared/contracts/graph-mutation-registry.json
  - packages/shared/graph-mutation.ts
  - Backend Architecture/aether-backend/shared/graph/mutation_models.py
  - Backend Architecture/aether-backend/shared/graph/generated_mutation_taxonomy.py
  - Backend Architecture/aether-backend/shared/graph/edge_properties.py
  - scripts/validate_graph_write_paths.py
  - scripts/allowlists/graph_write_paths.json
last_synced_commit: a500f1f
---

# Temporal Observatory & Decision Memory (PR 1 scope)

Immutable facts, mutable projections: every historically material graph
write will pass through one canonical mutation gateway producing an
append-only bitemporal ledger (valid time ≠ system knowledge time), enabling
known-then vs known-now reconstruction with deterministic digests.

## Ownership

| Concern | Canonical owner |
|---|---|
| Mutation taxonomy (23 types), actor kinds, causality classes, explanation types | `packages/shared/contracts/graph-mutation-registry.json` → generated TS/Py twins |
| `MutationRecord` / `DecisionRecord` / `ChangeSet` contracts | `shared/graph/mutation_models.py` ↔ `graph-mutation.ts` (parity-tested; bitemporal field names pinned to `edge_properties.py::BITEMPORAL_EDGE_PROPERTIES`) |
| Bitemporal field vocabulary (`valid_from`/`valid_to`/`recorded_at`/`superseded_at`) + edge idempotency keys | `shared/graph/edge_properties.py` (pre-existing; reused verbatim) |
| Write-path freeze until the gateway lands | `scripts/validate_graph_write_paths.py` — the 32 current direct-writer files are frozen in a shrink-only allowlist; any NEW direct writer fails CI |

## Sequencing

PR 2 delivers `shared/graph/mutation_gateway.py` (validate → idempotency →
bitemporal version close/append → Postgres append-only ledger → current
projection → `graph.mutated`), migrates all frozen writers, and shrinks the
allowlist to gateway internals. PR 3 delivers reconstruction
(checkpoint + ledger delta, digest verification), the temporal modes
(live/as-of/known-then/known-now/correction-diff/compare/playback/isolated
simulation), and the `/v1/temporal` API family. Explanations may never claim
more than their `causality_class` supports — correlation stays correlation.
