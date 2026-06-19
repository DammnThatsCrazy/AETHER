---
title: Dune Chain Extraction Plan
slug: architecture/dune-chain-extraction-plan
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: data@aether
source_files:
  - Backend Architecture/aether-backend/services/provider_catalog/catalog.py
last_synced_commit: "pending"
estimated_read_minutes: 6
---

# Dune Chain Extraction Plan

> Aether's on-chain intelligence requires explicit chain coverage decisions.
> Not all chains are equal in signal density, platform priority, or extraction
> complexity. This document defines which chains are extracted, in what order,
> and what products each chain extraction feeds.

## Prioritization criteria

Chains are prioritized by:

1. **User wallet concentration** — chains where Aether's tenants have the most
   active users.
2. **Signal density** — chains with rich decodable event logs and DeFi activity.
3. **Dune coverage maturity** — chains with well-maintained Dune spellbooks.
4. **Cross-chain signal value** — chains whose data enriches other chains
   (e.g., bridge activity).

---

## P0 Critical — Must have at launch

These chains are required for core product functionality. Extraction pipelines
for P0 chains must be in production before any intelligence product ships.

| Chain | Primary signal | Dune table prefix |
|---|---|---|
| Ethereum | Wallets, DeFi, NFT, DAO, ERC-20 | `ethereum.*` |
| Solana | SPL tokens, DEX, NFT, program activity | `solana.*` |
| BNB Chain | PancakeSwap, BEP-20, bridge flows | `bnb.*` |
| Polygon | Polygon PoS activity, bridged assets | `polygon.*` |
| Arbitrum | L2 DeFi, GMX, bridge receipts | `arbitrum.*` |
| Base | Coinbase ecosystem, new wallet onboarding | `base.*` |

---

## P1 High — Ship within 60 days of P0

These chains add significant coverage for multi-chain users and protocol health
signals. Begin extraction pipeline work in parallel with P0 hardening.

| Chain | Primary signal | Dune table prefix |
|---|---|---|
| Optimism | OP ecosystem, Velodrome, bridge | `optimism.*` |
| Avalanche | Avalanche C-chain DeFi, subnet activity | `avalanche_c.*` |
| TRON | USDT volume, cross-chain stablecoin flows | `tron.*` |
| Bitcoin | UTXO flow, whale accumulation patterns | `bitcoin.*` |
| NEAR | NEAR Protocol activity and developer adoption | `near.*` |
| Sui | Move VM ecosystem, growing wallet activity | `sui.*` |

---

## P2 Medium — Ship within quarter 2

P2 chains provide depth signals for specific intelligence products (NFT, gaming,
cross-chain arbitrage detection). They are not required for core scoring.

| Chain | Primary signal |
|---|---|
| Fantom | DeFi ecosystem remnant, bridge data |
| Ronin | Axie ecosystem, gaming wallet behavior |
| zkSync Era | ZK rollup adoption metrics |
| Linea | ConsenSys ecosystem growth |
| Scroll | ZK L2 developer activity |
| Starknet | Cairo ecosystem adoption |
| Mantle | BitDAO/Bybit ecosystem |
| Celo | Mobile-first payments, stablecoin activity |

---

## Extraction products

Each chain extraction produces a set of standardized outputs. Not every product
is available for every chain — availability depends on Dune spellbook coverage.

| Product | Description | Required for |
|---|---|---|
| `wallet_summary` | 30/90/180-day activity summary per wallet | Profile 360, bot detection |
| `token_holdings` | ERC-20/SPL token balances and value | Whale detection, risk scoring |
| `dex_trades` | DEX swap history and volume | Behavioral prediction, wash trading |
| `nft_activity` | NFT mints, transfers, sales | NFT whale detection |
| `bridge_flows` | Cross-chain bridge deposits and withdrawals | Cross-chain graph edges |
| `protocol_interactions` | Protocol-level call frequency | Intent prediction |
| `funding_rate_exposure` | CEX perp positions linked to on-chain wallets | Liquidation risk |
| `governance_votes` | DAO proposal votes linked to wallets | Social identity graph |
| `stablecoin_flows` | USDC/USDT/DAI inflow and outflow | Fiat off-ramp detection |
| `contract_deployments` | Developer activity by wallet | Developer persona tagging |

---

## Extraction pipeline design principles

1. **Idempotent by block range:** each extraction run specifies a block range and
   produces deterministic output. Re-running any range does not create duplicates.
2. **Incremental by default:** pipelines maintain a high-water-mark checkpoint.
   Full reloads are scheduled only when spellbook tables change incompatibly.
3. **Chain-agnostic schema:** extraction outputs conform to a common schema with
   a `chain` field, enabling cross-chain joins without pipeline-specific logic.
4. **Lineage attached:** every extracted record carries a `lineage_id` referencing
   the Dune query ID, execution timestamp, and block range.
5. **Spellbook version pinned:** the Dune spellbook version used for each table
   is logged alongside each extraction batch. Breaking spellbook changes trigger
   an alert before the pipeline runs against the new schema.

---

## Chain gap policy

If a P0 or P1 chain experiences a Dune extraction outage (table unavailable,
spellbook broken, credit exhaustion), the platform must:

1. Mark affected intelligence products as `DATA_STALE` in the API response.
2. Continue serving cached results with a staleness timestamp.
3. Page the on-call data engineer within 30 minutes of gap detection.
4. Attempt automated recovery after 2 hours; escalate to Dune support after 4.

---

## Related docs

- `DUNE_DATA_LAKE_STRATEGY.md` — Strategic context for Dune's role.
- `DUNE_ACCESS_MODES.md` — API, Datashare, and Sim mode specifications.
- `SOURCE_TO_MODEL_MATRIX.md` — Which models consume each chain's data.
