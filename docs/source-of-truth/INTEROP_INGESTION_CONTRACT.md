---
title: Interoperability Ingestion Contract
slug: source-of-truth/interop-ingestion-contract
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/interop/correlation.py
  - Backend Architecture/aether-backend/services/interop/providers/base.py
  - Backend Architecture/aether-backend/services/interop/providers/layerzero_v2.py
  - Backend Architecture/aether-backend/services/interop/providers/layerzero_abi.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Interoperability Ingestion Contract

## Provider adapters

`InteropProviderAdapter` ABC: `scan(checkpoint)`, `decode_observation`,
`derive_path`, `derive_guid`, `snapshot_security_policy`, plus an honest
`ImplementationStatus` descriptor. Registered adapters: **LayerZero V2**
(`CREDENTIAL_GATED` — fixture-proven decode; live scanning requires RPC
credentials) and six `SCAFFOLDED` providers (Wormhole, Axelar, CCIP,
Hyperlane, IBC, deBridge) whose decode paths raise `NotImplementedError`
and are covered by an honesty test asserting non-live status.

## LayerZero V2 decode

Pure-Python ABI slicing (`layerzero_abi.py`, no web3py): topic0 constants
are keccak hashes of `PacketSent(bytes,bytes,address)`,
`PacketVerified((uint32,bytes32,uint64),address,bytes32)`, and
`PacketDelivered((uint32,bytes32,uint64),address)`. The packet header is
byte-offset decoded (version u8, nonce u64, srcEid u32, sender bytes32,
dstEid u32, receiver bytes32, guid bytes32, message). GUID =
keccak(nonce ‖ srcEid ‖ sender ‖ dstEid ‖ receiver) is recomputed for
verify/deliver legs → `correlation_key = "lz2:{guid}"`.

## Correlation & reorg

`CorrelationEngine.ingest_observation` joins source/verify/deliver legs
in any order under the GUID key, appends transition rows through the
lifecycle FSM, and emits `interop_message_correlated` exactly once.
Scanning is checkpointed per (provider, chain) with a confirmation
horizon; in-horizon observations are provisional, and a parent-hash
mismatch on re-scan rolls back provisional evidence and emits reorg
events. Aether never relays, retries, or recovers messages.
