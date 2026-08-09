---
title: "Interoperability Intelligence — Domain Decisions"
slug: productization/economic-interoperability-intelligence/adr-interop-decisions
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/interop/lifecycle.py
  - Backend Architecture/aether-backend/services/interop/correlation.py
  - Backend Architecture/aether-backend/services/interop/providers/layerzero_v2.py
canonical_owner: platform@aether
last_synced_commit: "41c79d4"
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
| I10 | All seven adapters (LayerZero, Wormhole, Axelar, CCIP, Hyperlane, IBC, deBridge) are CREDENTIAL_GATED: fixture-proven decode + correlation; live scanning requires a wired per-network RPC client, otherwise the credential-gated guard raises | No PROVIDER_LIVE claims without live validation — enforced by the honesty test; none is SCAFFOLDED, none claims provider-live status |
| I11 | Operational fields (`operational_state`) derived from the persisted checkpoint, never a live call | Runtime telemetry survives worker restarts; a provider-health answer never requires network access |
| I12 | Supervised `ScanWorker.run_cycle`: checkpoint-load → scan → correlation → dead-letter quarantine → reconciliation evidence → graph projection → security snapshot → checkpoint persist → publish → metering | One durable, idempotent cycle; a crash restarts from the last persisted checkpoint, never from scratch; `skipped`/`rate_limited`/`error`/`ok` reporting |
| I13 | Interop usage recorded as billable `metering_evidence` dimensions with dedupe-safe replay | A restart replay of the same checkpoint reproduces the same dedupe key and is recorded non-billable — retries can never double-bill |
