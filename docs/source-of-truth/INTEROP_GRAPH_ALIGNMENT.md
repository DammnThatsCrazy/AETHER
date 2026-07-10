---
title: Interoperability Graph Alignment
slug: source-of-truth/interop-graph-alignment
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/graph.py
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - Backend Architecture/aether-backend/services/interop/graph_mutations.py
  - packages/shared/graph-contract.ts
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Interoperability Graph Alignment

## Vertices

`INTEROP_PROVIDER`, `INTEROP_GATEWAY`, `INTEROP_PATH`,
`INTEROP_APPLICATION`, `VERIFICATION_ACTOR`, `DELIVERY_ACTOR`. Messages
are silver facts, never vertices (cardinality).

## Edges

Domain topology edges are layer-`EXCLUDED`: `SENT_VIA_PATH`,
`DELIVERED_VIA_GATEWAY`, `VERIFIED_BY`, `ROUTES_THROUGH`,
`CONNECTS_CHAIN`, `SECURED_BY_POLICY`, `USES_PROVIDER`,
`ORIGINATES_FROM_APP`, `DELIVERS_TO_APP`. Actor edges participate in
layers: `REQUESTED_DELIVERY_FROM` (H2A) and `RELAYED_FOR` (A2H — present
in BOTH `packages/shared/graph-contract.ts` `EDGE_LAYER_MAP` and the
Python `_EDGE_LAYER_MAP`; the A2H parity test asserts set equality).

Mutations (`graph_mutations.py`) build provider/gateway/path topology in
the public reference scope and tenant-scoped message links
(`SENT_VIA_PATH` from originating application/wallet,
`SECURED_BY_POLICY` when a snapshot is attached), all via
`build_edge_properties` with idempotency keys, gated by
`settings.interop.graph_enabled`.
