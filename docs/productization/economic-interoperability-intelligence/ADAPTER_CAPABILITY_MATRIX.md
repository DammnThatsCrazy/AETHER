---
title: Adapter Capability Matrix
slug: productization/economic-interoperability-intelligence/adapter-capability-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/derivatives/adapters/venue_base.py
  - Backend Architecture/aether-backend/services/interop/providers/layerzero_v2.py
  - Backend Architecture/aether-backend/services/interop/providers/wormhole.py
  - Backend Architecture/aether-backend/services/interop/providers/axelar.py
  - Backend Architecture/aether-backend/services/interop/providers/chainlink_ccip.py
  - Backend Architecture/aether-backend/services/interop/providers/hyperlane.py
  - Backend Architecture/aether-backend/services/interop/providers/ibc.py
  - Backend Architecture/aether-backend/services/interop/providers/debridge.py
  - Backend Architecture/aether-backend/services/stablecoins/price_feed.py
canonical_owner: platform@aether
source_hashes:
  "Backend Architecture/aether-backend/services/derivatives/adapters/venue_base.py": "sha256:f6d471b0845c69191fa99eaceed7d83698bbad29c48cb7386e06360955d1f226"
  "Backend Architecture/aether-backend/services/interop/providers/axelar.py": "sha256:91d37bfe0c21d21111e9f15562ca5ab61b8638502e0e5c302ac638c0d4d6780d"
  "Backend Architecture/aether-backend/services/interop/providers/chainlink_ccip.py": "sha256:5bfac82aeec12bceb5968b76ddd35accdd557aeec59f5260752e1bf5266d9048"
  "Backend Architecture/aether-backend/services/interop/providers/debridge.py": "sha256:01d11f6dc109f44d8a01b6eb724476fc72e935449756f32fa05ff319807b705a"
  "Backend Architecture/aether-backend/services/interop/providers/hyperlane.py": "sha256:a894c6a64b73e7e74f99f5a6ae3ee39c9b801606eb7de79770251b7b37638857"
  "Backend Architecture/aether-backend/services/interop/providers/ibc.py": "sha256:f6208857120ee238a5af1f11169e2368b07b5a624b6d9ca552fe195864dcfe74"
  "Backend Architecture/aether-backend/services/interop/providers/layerzero_v2.py": "sha256:1da5037959fb2a91ad2febd5738cc84bf1edebf56ff41ffd0cebbb47f00d8d03"
  "Backend Architecture/aether-backend/services/interop/providers/wormhole.py": "sha256:df38b0a4c82eef4be2302456a48857786187421fb18b35622ddfa0183bbf57ba"
  "Backend Architecture/aether-backend/services/stablecoins/price_feed.py": "sha256:d575d0b5ad2f8991db7749a34b52cd1b3ef13c8fa047b56e8f1f0d8c2fa51636"
---

# Adapter Capability Matrix

`ImplementationStatus` is load-bearing and honest: nothing claims
`PROVIDER_LIVE` without live validation, which cannot happen in this
environment. The machine-readable, source-generated matrix lives at
`docs/_generated/adapter-certification-matrix.json`
(`make credentialless-certification`); this page is its operator narrative.

## Derivatives

| Adapter | Status | Capabilities | Blockers to live |
|---|---|---|---|
| `simulator` | `MOCKED_LOCAL` | Deterministic seeded scenario; full conformance (reference) | None (reference implementation) |
| `hyperliquid` | `CREDENTIAL_WAITING` | REST backfill (fills/funding/positions/margin/markets) + WebSocket account stream over an injectable client; read-only scope enforced | Venue read-only API key + staging validation |
| `dydx` | `CREDENTIAL_WAITING` | REST (Indexer: fills/orders/positions) + WebSocket | Venue read-only API key + staging validation |
| `gmx` | `CREDENTIAL_WAITING` | Public on-chain read path (subgraph GraphQL, timestamp pagination); no private API/WS (declared) | Subgraph endpoint + staging validation |
| `drift` | `CREDENTIAL_WAITING` | REST read path (trades/funding); WebSocket declared not-supported | Venue endpoint + staging validation |

All four venue adapters implement the conformance-tested `DerivativesAdapter`
interface, pass `run_conformance` + `run_certification` with zero failures,
reject mutating scopes, use exact `Decimal` arithmetic, and yield nothing until
a REST/WS client is injected (honest credential-waiting). The
CSV/JSON/NDJSON import path remains the explicit no-credential fallback.

## Interoperability

| Provider | Status | Capabilities | Blockers to live |
|---|---|---|---|
| `layerzero_v2` | `CREDENTIAL_GATED` | Fixture-proven decode (PacketSent/Verified/Delivered), GUID recompute + correlation, checkpointed scan, parent-hash reorg rollback | Hosted RPC per chain; staged scan validation |
| `wormhole` | `CREDENTIAL_GATED` | LogMessagePublished + signed-VAA (13/19 guardian quorum) + TransferRedeemed decode; `wh:<chain>/<emitter>/<seq>` correlation | Guardian/RPC access |
| `axelar` | `CREDENTIAL_GATED` | ContractCall(WithToken)/Approved/Executed decode, commandId→messageId binding, validator confirmation | Validator/Axelarscan + RPC access |
| `chainlink_ccip` | `CREDENTIAL_GATED` | CCIPSendRequested/CommitReport/ExecutionStateChanged decode, per-sequence commit-interval expansion, retry/failure classification | Per-lane RPC + DON metadata |
| `hyperlane` | `CREDENTIAL_GATED` | Mailbox Dispatch/Process decode, keccak message-id correlation (ISM verification intrinsic to process) | Per-chain RPC access |
| `ibc` | `CREDENTIAL_GATED` | CometBFT send/recv/ack/timeout packet decode over Tendermint RPC, ICS-04 tuple correlation, ICS-07 light-client security model | Chain RPC access |
| `debridge` | `CREDENTIAL_GATED` | DLN CreatedOrder/Fulfilled/ClaimedOrder + Gate Sent/Claimed decode, off-chain validator-set attestation (API) | API + per-chain RPC access |

Every provider normalizes into the protocol-neutral lifecycle
(source→verified/attested→delivered→settled) with out-of-order correlation,
checkpoint restart, cursor-drift/parent-hash rewind, rate-limit resume, and a
per-provider `security_model()` that is **not** flattened into false
equivalence. Live on-chain scanning fails closed (`NotImplementedError`) until a
RPC client is wired. A conformance suite and a provider-honesty test enforce that
statuses stay truthful; none is `SCAFFOLDED`.

## Stablecoin price sources

| Source | Status | Notes |
|---|---|---|
| Chainlink feeds | `CREDENTIAL_GATED` | `StablecoinChainlinkPriceConnector` decodes `latestRoundData`/`decimals` via `eth_call` over the injectable RPC gateway; exact `Decimal` value + peg classification; unavailable/stale → value withheld (never 0, never assumed 1 USD) |
| x402 verified contracts | live in-repo | Seeds the canonical asset/deployment registry |

A conformance suite (`adapters/conformance.py`), the credentialless certification
framework (`shared/certification`), and the provider-honesty tests enforce that
statuses stay truthful.
