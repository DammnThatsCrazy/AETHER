---
title: Stablecoin Ingestion Contract
slug: source-of-truth/stablecoin-ingestion-contract
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/stablecoin/service.py
  - Backend Architecture/aether-backend/services/stablecoin/finality.py
  - Backend Architecture/aether-backend/services/stablecoin/routes.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Stablecoin Ingestion Contract

## Intake

`POST /v1/stablecoins/observations` (flag `AETHER_STABLECOIN_INGESTION_ENABLED`
+ `stablecoins:read` write path guarded by `check_no_execution`):
normalizes provider payloads into canonical observations. Asset resolution
reuses the web3 Token/Chain registries seeded from the x402 verified
contract set; unresolved observations persist with
`canonical_asset_id="unresolved"` for operator review (never dropped).

## Determinism & idempotency

`observation_id = sha256(chain_id | tx_hash | log_index | kind)` — replays
are structural no-ops (`ON CONFLICT DO NOTHING` on
`(tenant_id, idempotency_key)`).

## Finality

Per-chain confirmation horizons; observations inside the horizon are
`provisional`. `FinalityEngine.advance_checkpoint` promotes to
`confirmed`/`finalized`; `handle_reorg(from_block)` demotes non-finalized
observations at/above the fork block to `reorged` and emits correction
events. Finalized rows are immutable.

## Metering

`stablecoin_observation_ingested` at intake;
`stablecoin_flow_materialized` when flow aggregates materialize.
