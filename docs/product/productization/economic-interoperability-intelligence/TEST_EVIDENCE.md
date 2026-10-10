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
  "tests/unit/derivatives/": "sha256:815a6200bc36602517ec8e2f3065a20b849ed8dae51ab4abd4ef57692a82d768"
  "tests/unit/interop/": "sha256:bcd2fb4f4ef848a76e7ddb843a7f423167469b93f598468df28586e99a38e86e"
  "tests/unit/stablecoin/": "sha256:22b6ec6271545c603ccdc2950387ed959afc6b04433787a7f4148d9b7718eac6"
  "tests/unit/test_economic_noesis_ooda_wiring.py": "sha256:fcf7ac56e7e4fb008fae05e265d60703dea60bce1581f005a91972eb67b8839d"
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
- `apps/aether-web`: typecheck + vitest (79 tests / 21 files).
- `apps/kyber-web`: typecheck + vitest (179 tests / 26 files).

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
