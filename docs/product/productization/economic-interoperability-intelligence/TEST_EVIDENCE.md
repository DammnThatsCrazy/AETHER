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
  "tests/unit/derivatives/": "sha256:dd3e5ebf9219f9a6e8e37526db2866b6e63ed4f5503df724667ec58921be6e55"
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
  idempotency; route perms/tenant isolation/flag-off 404; graph projection
  that links accounts and positions only to platform venue and market
  vertices projected from the registry, never to another tenant's account;
  idempotent registry projection. Real read-only
  venue adapters (Hyperliquid/dYdX REST+WebSocket, GMX/Drift read path) on
  the conformance-tested interface: mock-server REST backfill/pagination,
  WS reconnect + gap recovery, cursor resume, read-only-scope rejection.
  Linked-account sync (`test_account_sync.py`): live-captured Polymarket
  records admitted through provider raw rights admission into fills that carry
  their source, grant and decision refs; checkpoint resume without duplicates;
  a grant revoked behind an active link denies and keeps the checkpoint;
  tenant-pushed fills admitted under their link; client-forged governance refs
  stripped; fills wait (checkpoint held) until their market reference row
  exists. Market reference (`test_market_reference.py`): Olympus sources are
  `public_reference` grants with no tenant, cross-tenant, training or
  commercial rights; public market records are admitted before registry rows
  are written; a revoked source stops counting and a denied raw write writes
  nothing; dated futures with different expiries are separate instruments.
  Kalshi (`test_kalshi_account.py`): RSA-PSS signature verifies
  against the public key; signed portfolio reads project per-side
  event-contract fills and positions; no credential means no read;
  conformance and certification pass; key link then signed sync writes
  admitted fills; wallet links are refused. Bybit and Coinbase futures
  (`test_cex_futures_adapters.py`): HMAC signatures match the sent query,
  ES256 JWTs verify and name the exact request, OAuth tokens are sent as
  bearer, conformance and certification pass, the shared REST transport
  keeps a pre-signed query string, and Bybit HTTP-200 application errors
  (`retCode`) are classified failed reads, never healthy empty pages. Venue OAuth (`test_venue_oauth.py`): the app
  credential lives only under `olympus`; PKCE authorize URLs carry no secret;
  states are single-use and tenant-bound; mutating granted scopes are refused;
  expired tokens are refreshed and rotated in place.
  Event contracts (`test_event_contracts.py`): canonical instrument shape,
  Kalshi current dollar-price fields, and a Polymarket account adapter that
  passes conformance and credentialless certification; pseudonymized live
  captures from public Hyperliquid and Polymarket endpoints
  (`scripts/capture_venue_fixtures.py`) replay through the adapters and the
  position engine. This replay is recorded public data, not a tenant-linked
  live run.
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
