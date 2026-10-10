"""Derivatives Intelligence — bounded observation-only domain.

Two complementary layers share this package:

- Ingestion/accounting services (models, position_engine, reconciliation,
  routes, connectors/) — venue evidence normalization and product surfaces.
- The runtime for the PR1 foundation contracts (runtime_models,
  state_machines, streams, adapters/, runtime_reconciliation, pnl,
  runtime_routes) — read-only adapter framework + conformance suite,
  order/position state machines, bounded market-stream sequence tracking,
  and Decimal-safe P&L.

AETHER OBSERVES. AETHER DOES NOT EXECUTE: no code path places, amends,
cancels, or closes anything, and no adapter may hold credentials beyond
read-only authority.
"""
