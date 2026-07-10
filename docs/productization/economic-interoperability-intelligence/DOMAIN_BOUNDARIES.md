---
title: Domain Boundaries
slug: productization/economic-interoperability-intelligence/domain-boundaries
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/stablecoin.ts
  - packages/shared/derivatives.ts
  - packages/shared/interoperability.ts
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Domain Boundaries

## Aether MAY (all three domains)

Observe, normalize, correlate, analyze, explain, alert, reconcile,
aggregate, and surface evidence with provenance.

## Aether MUST NOT (enforced in code, not just policy)

- Custody funds or keys (credential references are read-only pointers).
- Execute, place, modify, or cancel trades/orders (no code path exists;
  conformance asserts `execution_by_aether == false`).
- Relay, retry, or recover cross-chain messages (adapters only scan).
- Mint, burn, or move stablecoins (observation intake only).
- Feed economic observations into model training
  (`allowModelTraining: false`; gold rows `model_training_eligible=0`).

## Boundaries between the domains

- **Stablecoin ↔ x402**: x402 owns settlement verification; stablecoin
  intelligence consumes its verified contract seeds and observes flows.
- **Stablecoin ↔ Interop**: a bridge transfer is a stablecoin
  observation (`bridge_in`/`bridge_out`) AND may attach to an interop
  message's asset legs — linked by transaction hash, never duplicated.
- **Derivatives ↔ Web3**: venue registries are derivatives-domain;
  chain/token identity reuses the web3 registries.
- **Interop providers**: provider-native vocabulary (GUID/EID/nonce)
  never leaks past `services/interop/providers/`.
