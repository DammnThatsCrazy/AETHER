---
title: Stablecoin Entity Model
slug: source-of-truth/stablecoin-entity-model
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/stablecoin-intelligence.ts
  - Backend Architecture/aether-backend/services/stablecoin/models.py
  - Backend Architecture/aether-backend/repositories/stablecoin_repos.py
canonical_owner: platform@aether
last_synced_commit: "03ab3a6"
---

# Stablecoin Entity Model

Canonical contracts live in `packages/shared/stablecoin-intelligence.ts`; the Python
mirrors in `services/stablecoin/models.py` are Pydantic v2 models with
Decimal fields serialized as strings and `execution_by_aether: Literal[False]`.

## Entities

| Entity | Identity | Notes |
|---|---|---|
| `StablecoinAssetCanonical` | `canonical_asset_id` | Issuer-level asset (e.g. `usdc`); peg currency + issuer metadata |
| `StablecoinDeployment` | `deployment_id` | Per-chain contract instance: chain_id, contract address, decimals |
| `StablecoinObservation` | `observation_id = sha256(chain_id, tx_hash, log_index, kind)` | Deterministic — replays dedupe structurally |
| `SupportAssertion` | `assertion_id` | Merchant/facilitator support claims with evidence |
| `ValuationSnapshot` | `valuation_id` | Peg price + deviation bps + `PegStatus` |
| `FlowAggregate` | `flow_aggregate_id` | Windowed volumes/counters, versioned by `metric_version` |
| `ReconciliationRecord` | append-only | Source-vs-projection comparison outcomes |
| `FinalityCheckpoint` | per (tenant, chain) | Confirmed block + confirmation horizon |

## Observation taxonomy

`StablecoinObservationType` covers transfer, payment, mint, burn,
bridge_in/bridge_out, swap, x402 settlement, treasury movement, payout,
and venue deposit/withdrawal kinds. Amounts are fixed-precision decimal
strings — never binary floats (`isDecimalString` rejects exponent and
float forms; the Python models reject float inputs).

## Finality states

`provisional → confirmed → finalized`, with `reorged` and `corrected` as
audited demotions. Finalized observations are never mutated; corrections
append new rows referencing the original observation.

## Storage

Typed repositories (`repositories/stablecoin_repos.py`) preserve Decimals
end-to-end: NUMERIC(38,18) columns, `UNIQUE(tenant_id, idempotency_key)`,
`CHECK (execution_by_aether = FALSE)` (Alembic `20260708_stablecoin_intelligence`).
