---
title: Adapter Capability Matrix
slug: productization/economic-interoperability-intelligence/adapter-capability-matrix
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/api/value/derivatives/adapters/venue_base.py, services/api/graph/interop/providers/layerzero_v2.py, services/api/graph/interop/providers/wormhole.py, services/api/graph/interop/providers/axelar.py, services/api/graph/interop/providers/chainlink_ccip.py, services/api/graph/interop/providers/hyperlane.py, services/api/graph/interop/providers/ibc.py, services/api/graph/interop/providers/debridge.py, services/api/value/stablecoins/price_feed.py]
canonical_owner: platform@aether
source_hashes:
  "services/api/graph/interop/providers/axelar.py": "sha256:ce312d57c97b3af8f19d367ddb9d235a108e82bccb4fb1196b67ed40121fb24f"
  "services/api/graph/interop/providers/chainlink_ccip.py": "sha256:778b9d5cfd69cf333087a162c5e0a1c7dc1d29407f08463eabafa7f1131d6be4"
  "services/api/graph/interop/providers/debridge.py": "sha256:c0507abaf8dc3cf28916bff61d6c1dadd3c10c08cb91612c6d413991c8c37df5"
  "services/api/graph/interop/providers/hyperlane.py": "sha256:598c102da6eabf4a349419f57ecf5e697a5bf19041af2d6e727b37d32bce0906"
  "services/api/graph/interop/providers/ibc.py": "sha256:e3877b2a59b68ea507699246dc0d693dc3c3be3f281da2c7655f5e2da2234fee"
  "services/api/graph/interop/providers/layerzero_v2.py": "sha256:d0023a52c1d79801a9e635d224eee544f6c2cec9516b49cb6be8aa08c9d470e1"
  "services/api/graph/interop/providers/wormhole.py": "sha256:0bf5064d4968017fc3b2c386c10ab1b623dc08bb50221fb5527b2b9fe415cb90"
  "services/api/value/derivatives/adapters/venue_base.py": "sha256:a06c93e331962efc07f7943943809f42ebe140d946825c4feac84be7eec1654d"
  "services/api/value/stablecoins/price_feed.py": "sha256:2a88c6769b436ccd3931e73d8523cf15023440a2a9b43a532af0eec0816648f1"
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
