---
title: Adapter Capability Matrix
slug: productization/economic-interoperability-intelligence/adapter-capability-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/derivatives/adapters/simulator.py
  - Backend Architecture/aether-backend/services/interop/providers/layerzero_v2.py
  - Backend Architecture/aether-backend/services/interop/providers/scaffolds.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Adapter Capability Matrix

`ImplementationStatus` is load-bearing and honest: nothing claims
`PROVIDER_LIVE` without live validation, which cannot happen in this
environment.

## Derivatives

| Adapter | Status | Capabilities | Blockers to live |
|---|---|---|---|
| `simulator` | `MOCKED_LOCAL` | Deterministic seeded scenario: registry, orders, fills, positions, snapshots; full conformance | None (reference implementation) |
| venue adapters | none shipped | — | Venue read-only API credentials + staging validation |

## Interoperability

| Provider | Status | Capabilities | Blockers to live |
|---|---|---|---|
| `layerzero_v2` | `CREDENTIAL_GATED` | Full fixture-proven decode (PacketSent/Verified/Delivered), GUID recompute + correlation, path derivation, checkpointed scanning, parent-hash reorg rollback | Hosted RPC credentials per chain; then staged scan validation |
| `wormhole`, `axelar`, `ccip`, `hyperlane`, `ibc`, `debridge` | `SCAFFOLDED` | Descriptor + documented event/topic references; decode raises `NotImplementedError` | Per-provider decode implementation + fixtures + credentials |

## Stablecoin price sources

| Source | Status | Notes |
|---|---|---|
| Chainlink feeds | `CREDENTIAL_GATED` | Valuation accepts operator-submitted snapshots today; feed polling needs credentials |
| x402 verified contracts | live in-repo | Seeds the canonical asset/deployment registry |

A conformance suite (`adapters/conformance.py`) and a scaffold honesty
test enforce that statuses stay truthful.
