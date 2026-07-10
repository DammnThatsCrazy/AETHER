---
title: Derivatives Graph Alignment
slug: source-of-truth/derivatives-graph-alignment
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/graph.py
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - Backend Architecture/aether-backend/services/derivatives/graph_mutations.py
  - packages/shared/graph-contract.ts
canonical_owner: platform@aether
last_synced_commit: 1f19190
---
# Derivatives Graph Alignment

Derivatives extends the Universal Intelligence Graph without creating a derivatives-only graph. Actor relationships are classified into H2H, H2A, A2H, or A2A. Domain relationships such as Order to Fill, Position to Market, Market to Venue, Account to Position, and Fill to Instrument are explicitly classified as domain excluded from actor-layer semantics while remaining available to universal graph queries.

The authoritative PR1 TypeScript edge inventory is `DERIVATIVES_EDGE_LAYER_MAP` in `packages/shared/derivatives.ts`.
