---
title: Stablecoin Graph Alignment
slug: source-of-truth/stablecoin-graph-alignment
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/graph.py
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - Backend Architecture/aether-backend/services/stablecoin/graph_mutations.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Stablecoin Graph Alignment

## Vertices

Reuses the existing `STABLECOIN_ASSET`, `CHAIN`, and `BRIDGE_ROUTE`
vertex types; 8.12.0 adds `STABLECOIN_DEPLOYMENT` (per-chain contract
instance). Observations are silver facts, never vertices (cardinality).

## Edges

Domain edges are `EXCLUDED` from the four relationship layers (they are
asset topology, not actor relationships): `TRANSFERRED_STABLECOIN`,
`BRIDGED_STABLECOIN`, `SWAPPED_STABLECOIN`, `ISSUED_BY`,
`DEPLOYED_ON_CHAIN`, `SUPPORTS_ASSET`, `PEGGED_TO`. Support assertions
reuse the pre-existing `ACCEPTS_ASSET` edge.

Every edge is registered in `relationship_layers.py::_EDGE_LAYER_MAP`
(exhaustiveness enforced by `assert_contract_valid()` and the parity
tests); mutations flow through `graph_mutations.py` using
`build_edge_properties` (tenant, provenance, idempotency key,
`source_event_id`) and are persisted via `foundation.persist_mutations`,
gated by `settings.stablecoin.graph_enabled`.
