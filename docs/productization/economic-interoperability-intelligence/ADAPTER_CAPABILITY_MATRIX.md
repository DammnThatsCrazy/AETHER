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
