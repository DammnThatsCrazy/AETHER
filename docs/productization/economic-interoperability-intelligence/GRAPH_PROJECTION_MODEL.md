---
title: Graph Projection Model
slug: productization/economic-interoperability-intelligence/graph-projection-model
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/graph.py
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - packages/shared/graph-contract.ts
canonical_owner: platform@aether
last_synced_commit: "4a16247"
---

# Graph Projection Model

8.12.0 adds 8 vertex types and 87 edge types; the per-domain alignment
docs (`STABLECOIN_GRAPH_ALIGNMENT`, `DERIVATIVES_GRAPH_ALIGNMENT`,
`INTEROP_GRAPH_ALIGNMENT`) carry the full lists. The traffic-intelligence
acquisition/attribution edges are included: `ARRIVED_THROUGH_SOURCE`,
`USED_PLACEMENT`, `ORIGINATED_FROM_LINK`, and
`ATTRIBUTED_TO_PLATFORM_EVIDENCE` are `EXCLUDED`-layer topology edges, while
`REFERRED_ENTITY` (AI/agent → entity) participates in the `A2H` layer. All
five are mapped in `_EDGE_LAYER_MAP` and projected by `SilverGraphProjector`
from touchpoint facts (tenant-scoped, replay-safe).

Cross-domain rules:

- High-cardinality facts (observations, orders, fills, positions,
  messages) are NEVER vertices — they stay silver facts.
- Actor edges participate in the four layers (H2H/H2A/A2H/A2A); domain
  topology edges are `EXCLUDED`. Every new edge is mapped in
  `_EDGE_LAYER_MAP`; `assert_contract_valid()` and the exhaustiveness
  test fail on unmapped edges.
- A2H edges exist in BOTH `packages/shared/graph-contract.ts` and the
  Python map — `tests/unit/test_graph_contract_parity.py` asserts set
  equality (the 7 derivatives A2H edges and interop `RELAYED_FOR` are
  covered).
- All mutations flow through `build_edge_properties` (tenant, actor,
  provenance, valid_from, source_event_id, idempotency key) and
  `persist_mutations`, gated per domain by `*_graph_enabled` flags.
- Import rollback and replay use conservative ownership-aware garbage collection.
  A vertex is removed only when the failed import is its canonical owner, the
  vertex has no ownership history from another import, and no active edge still
  references it. Pre-existing or shared vertices are retained.

The card-linked payment rail slice adds 5 vertex types (`CARD_PROGRAM`,
`CARD_ISSUER`, `PAYMENT_NETWORK`, `CARD_LINKED_FLOW`, `CARD_BENCHMARK`)
and 9 edge types (`CAME_FROM`, `PARTICIPATED_IN`, `USED_PROVIDER`,
`FUNDED`, `OCCURRED_ON`, `USED_ASSET`, `RUNS_ON`, `FOLLOWED_BY`,
`INITIATED_OR_INFLUENCED`), every one mapped to
`RelationshipLayer.EXCLUDED` — card-linked behavior is intentionally
never usable as deterministic identity-merge evidence. PaymentScan
benchmark rows are never projected to the graph at all
(`services/card_linked_payments/graph_projector.py`).
