---
title: Derivatives Graph Alignment
slug: source-of-truth/derivatives-graph-alignment
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: 0.1.0
source_files: [services/api/shared/graph/graph.py, services/api/shared/graph/relationship_layers.py, services/api/value/derivatives/graph_mutations.py, packages/shared/graph-contract.ts]
canonical_owner: platform@aether
last_synced_commit: 1f19190
---
# Derivatives Graph Alignment

Derivatives extends the Universal Intelligence Graph without creating a derivatives-only graph. Actor relationships are classified into H2H, H2A, A2H, or A2A. Domain relationships such as Order to Fill, Position to Market, Market to Venue, Account to Position, and Fill to Instrument are explicitly classified as domain excluded from actor-layer semantics while remaining available to universal graph queries.

Venue and market vertices (`market_venue:`, `derivative_market:`) are platform
reference data projected from the venue and market registry by
`make derivatives-registry-graph`. Tenant account links and position
observations write only the tenant's `trading_account:` vertex and add
AUTHENTICATES / HOLDS_POSITION edges once the venue or market vertex exists.

The authoritative PR1 TypeScript edge inventory is `DERIVATIVES_EDGE_LAYER_MAP` in `packages/shared/derivatives.ts`.
