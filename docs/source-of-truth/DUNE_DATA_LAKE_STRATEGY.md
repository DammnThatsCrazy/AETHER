---
title: Dune Data Lake Strategy
slug: architecture/dune-data-lake-strategy
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: data@aether
source_files:
  - Backend Architecture/aether-backend/services/provider_catalog/catalog.py
last_synced_commit: "pending"
estimated_read_minutes: 5
---

# Dune Data Lake Strategy

> Dune is Aether's primary historical on-chain data source, but it is not the
> sole backbone of the intelligence platform. This document explains what Dune
> provides, where it falls short, and why the multi-provider model exists.

## Dune's role

Dune is the connective tissue for historical on-chain analytics. It provides
SQL-accessible tables covering transactions, traces, logs, and decoded contract
events across all major EVM chains and Solana. For Aether, this means:

- Batch extraction of historical wallet behavior without building custom
  chain indexers.
- Parameterized SQL queries that can be reused across tenants and time ranges.
- Curated spellbook tables (e.g., `dex.trades`, `nft.trades`) that normalize
  cross-protocol data.
- A Datashare path (via Snowflake) that allows bulk warehouse bootstrap without
  per-query API costs.

Dune is classified as `OLYMPUS_PROVIDER`, `HISTORICAL_ONCHAIN`, `P1_FOUNDATION`,
`CRITICAL` risk tier.

---

## Three access modes

Dune exposes three distinct access surfaces, each suited to a different use case.
See `DUNE_ACCESS_MODES.md` for detailed specs.

| Mode | Best for | Cost model |
|---|---|---|
| `dune_api` | Parameterized queries, prototyping, per-wallet lookups | Per-execution credit |
| `dune_datashare` | Warehouse bootstrap, bulk historical extraction | Fixed subscription |
| `dune_sim` | Realtime wallet simulation and enrichment | Per-simulation credit |

The platform uses all three modes simultaneously. Using only the API for bulk
extraction would exhaust credits and introduce per-query latency on hot paths.

---

## Why Dune is not the only backbone

Dune has structural gaps that make it insufficient as a sole data source:

**Coverage gaps:** Dune's Solana coverage is growing but incomplete for program
logs and inner instructions. Bitcoin UTXO data is limited. Some L2s have
indexing lag.

**Latency:** The API is optimized for analytical queries, not sub-second
enrichment. Real-time wallet state must come from simulation (dune_sim) or
complementary providers like Alchemy or Moralis.

**Cost at scale:** Per-query credit costs are appropriate for prototyping.
At production query volumes across tens of thousands of wallets, the credit
burn rate exceeds budget. The Datashare path mitigates this for historical
data but does not cover realtime paths.

**Labeled data:** Dune provides raw on-chain data. Entity labels (exchange
wallets, known contracts, CEX hot wallets) come from separate providers:
Etherscan, Nansen (BYOK), Arkham (planned).

**Social and governance signals:** Dune does not index off-chain data. Farcaster,
Lens, Snapshot, and GitHub are required for social and governance enrichment.

**Prediction markets:** Polymarket and Kalshi are separate integrations. Dune
has some Polymarket data via community spellbooks, but the authoritative source
for odds and resolution is the provider API.

---

## Dependency policy

Because Dune is `CRITICAL` risk tier, the platform must maintain:

1. **Fallback behavior:** when Dune API is degraded, cached results from the
   last successful extraction should be served with a staleness flag rather than
   returning errors.
2. **Datashare independence:** the Datashare (warehouse) tables are refreshed
   on a schedule. Intelligence products that can tolerate T+1 latency should
   consume from the warehouse, not the API, to reduce credit consumption.
3. **Monitoring:** Dune API response times and credit consumption are tracked
   as platform-level metrics. Alerts fire at 80% monthly credit usage.

---

## What Dune does not replace

| Need | Correct source |
|---|---|
| Realtime price feeds | `coingecko`, `binance_public` |
| NFT metadata | `alchemy`, `moralis`, `opensea` |
| Social identity | `farcaster_neynar`, `lens_protocol`, `ens_public` |
| Compliance labels | `chainalysis`, `elliptic` (planned) |
| Prediction market odds | `polymarket_gamma`, `kalshi` |
| Governance votes | `snapshot` |

---

## Related docs

- `DUNE_ACCESS_MODES.md` — Detailed API, Datashare, and Sim specs.
- `DUNE_CHAIN_EXTRACTION_PLAN.md` — Which chains are prioritized and why.
- `OLYMPUS_PROVIDER_SOURCE_CATALOG.md` — Full catalog with all providers.
