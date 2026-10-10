---
title: Test Evidence
slug: productization/economic-interoperability-intelligence/test-evidence
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [tests/unit/stablecoin/, tests/unit/derivatives/, tests/unit/interop/, tests/unit/test_economic_noesis_ooda_wiring.py]
canonical_owner: platform@aether
source_hashes:
  "tests/unit/derivatives/": "sha256:f6ca894077e8c764cd72f0e1e83378c6276fc698883cd1b633a0363189b2035e"
  "tests/unit/interop/": "sha256:85e975ceab4eca12f6a8fd2e687766d835cf4c82c8b47aac78fe4723ff78363e"
  "tests/unit/stablecoin/": "sha256:31f421e4ae176a9b83f7041ad24a85f0cbb1cf360fdb3394ad9c928956cd7f8f"
  "tests/unit/test_economic_noesis_ooda_wiring.py": "sha256:2572a83e0c806eac355d7a0edb1efe8d0f9bf2bfd2ec586c73c535454f10303e"
---

# Test Evidence

## Gated suites (all green at release commit)

- Root `pytest tests/` — all green at the release commit, including the
  credential-waiting adapter suites added across payment rails, card-linked,
  stablecoin chain connectors, interop (seven providers), and derivatives
  venues (mock-server integration only; no live network).
- `npm test` (packages/shared + workspaces) — passing, including
  `stablecoin.test.ts`, `interoperability.test.ts`, and updated
  `events-registry.test.ts` / `consent-model.test.ts` counts.
- `apps/aether`: typecheck + vitest (79 tests / 21 files).
- `apps/kyber`: typecheck + vitest (179 tests / 26 files).

## Domain coverage highlights

- Derivatives: every legal Order/Position FSM transition + illegal
  rejections; out-of-order; corrections; simulator determinism; adapter
  conformance; stream gap detect/recover/bounded-buffer (a real recovery
  bug was found and fixed by these tests); reconciliation; Decimal
  38,18 round-trips + no-float model introspection; typed-repo
  idempotency; route perms/tenant isolation/flag-off 404. Real read-only
  venue adapters (Hyperliquid/dYdX REST+WebSocket, GMX/Drift read path) on
  the conformance-tested interface: mock-server REST backfill/pagination,
  WS reconnect + gap recovery, cursor resume, read-only-scope rejection.
- Stablecoin: observation dedupe/resolution; depeg classification;
  finality reorg rollback (finalized immutable, corrections append);
  projector routing; routes; graph mutation shapes.
- Interop: TS↔Python lifecycle parity (regex over
  `INTEROP_LEGAL_TRANSITIONS`); all seven providers (LayerZero, Wormhole,
  Axelar, Chainlink CCIP, Hyperlane, IBC, deBridge) with real event decode +
  fixtures that share encoders with the decoder so they cannot drift;
  out-of-order correlation; reorg / parent-hash / cursor-drift rewind;
  provider honesty (every provider credential-gated, none scaffolded); routes.
- Cross-cutting: event-registry well-formedness (purposes exist,
  silverProjection tokens map to registered projectors),
  consent-enforcement registry sync, Noesis/OODA/alert wiring (15
  tests), graph parity/exhaustiveness (existing tests extended
  automatically).

## Explicitly deferred (documented, never faked)

Load/chaos tests, live-RPC integration, live venue WebSockets,
ClickHouse gold query execution, staging soak.
