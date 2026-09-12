---
title: Domain Boundaries
slug: productization/economic-interoperability-intelligence/domain-boundaries
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [packages/shared/stablecoin-intelligence.ts, packages/shared/derivatives.ts, packages/shared/interoperability.ts]
canonical_owner: platform@aether
source_hashes:
  packages/shared/derivatives.ts: sha256:f1aa8933c643877fa2472f6d7dd0703eb67661c441a29372bf3817a8b05a4d26
  packages/shared/interoperability.ts: sha256:fe72abcf3f2c2570871689112419971832674e6d74fa8259a2d9c057b2a7b049
  packages/shared/stablecoin-intelligence.ts: sha256:e7fc796932dafd5dc1c900f2a5468913f534b129cf418144b5b2716e1a538138
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
