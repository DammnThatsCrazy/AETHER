---
title: "Interoperability Intelligence — Domain Decisions"
slug: productization/economic-interoperability-intelligence/adr-interop-decisions
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/graph/interop/lifecycle.py
  - services/api/graph/interop/correlation.py
  - services/api/graph/interop/providers/layerzero_v2.py
canonical_owner: platform@aether
source_hashes:
  "services/api/graph/interop/correlation.py": "sha256:cb3c51e9093df2475a788a6fa98544b54bd8b9b6524a8980b19c2211aac1364d"
  "services/api/graph/interop/lifecycle.py": "sha256:fe1ed1b1ac51f233cc21cad9aa9aeb3af2f1b3721bcdad1a4b2a0a0ebfc8a759"
  "services/api/graph/interop/providers/layerzero_v2.py": "sha256:d0023a52c1d79801a9e635d224eee544f6c2cec9516b49cb6be8aa08c9d470e1"
---

# Interoperability Intelligence — Domain Decisions

| # | Decision | Rationale |
|---|---|---|
| I1 | Protocol-neutral canonical model; provider vocabulary stays in adapters | Seven providers with different vocabularies; GUID/EID/nonce leak nowhere |
| I2 | `INTEROP_LEGAL_TRANSITIONS` in TS is the single FSM source of truth; Python mirrors with regex-parity test | Two hand-maintained FSMs WILL drift; the test makes drift a CI failure |
| I3 | Legal transitions always apply; rank only classifies illegal arrivals | Retry cycles (delivery_failed → delivery_pending) are legal regressions; rank-blocking them was a real bug |
| I4 | Correlation key = `lz2:{guid}` with GUID recomputed from Origin fields | Verify/deliver legs don't carry the packet; recomputation joins legs in any order |
| I5 | `interop_message_correlated` emitted exactly once per completed join | Metering and downstream consumers need one signal, not one per leg |
| I6 | Pure-Python ABI decode, no web3py | Follows the x402 verification precedent; one fewer heavy dependency; byte offsets are fixture-tested |
| I7 | Fixtures share encoders with the decoder | Fixture/decoder drift becomes structurally impossible |
| I8 | Security policies content-hashed, unique per (path, hash) | Change detection is a hash compare; drift surfaces on the ops page and as a P1 alert |
| I9 | Reorg = parent-hash mismatch on re-scan → roll back provisional evidence | Provisional/finalized split mirrors the stablecoin finality model |
| I10 | LayerZero honest maximum is CREDENTIAL_GATED; six scaffolds refuse loudly | No PROVIDER_LIVE claims without live validation — enforced by the honesty test |
