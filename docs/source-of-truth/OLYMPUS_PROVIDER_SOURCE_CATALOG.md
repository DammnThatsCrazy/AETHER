---
title: Olympus Provider Source Catalog
slug: architecture/olympus-provider-source-catalog
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: data@aether
source_files:
  - Backend Architecture/aether-backend/services/provider_catalog/catalog.py
last_synced_commit: "pending"
estimated_read_minutes: 8
---

# Olympus Provider Source Catalog

> Aether's intelligence platform is fed by a curated set of external data
> providers managed under the Olympus umbrella. This document is the definitive
> catalog of those providers, their build phase, and their activation status.
> No provider should be connected outside this catalog without an architecture
> review.

## Why a catalog?

Without a single list, providers proliferate organically. The catalog enforces:

- A single source of truth for which providers are active vs. planned.
- Phase discipline: shipping P3 sources before P1 sources wastes capacity.
- Compliance gating: some providers are disabled due to data-licensing or
  regulatory exposure, not technical limitations.
- Cost visibility: each provider has a cost tier that gates budget approval.

---

## P1 Foundation — Core Data Backbone

These providers are required for MVP. Every downstream intelligence product
depends on at least one P1 source. Ship these before any P2 work begins.

| Slug | Description | Priority reason |
|---|---|---|
| `dune` | Parameterized SQL over all major chains | Historical on-chain core |
| `defi_llama` | Protocol TVL, yield, stablecoin circulation | DeFi market context |
| `coingecko` | Spot prices, market cap, volume | Price normalization |
| `polymarket_gamma` | Prediction market contracts and probabilities | Prediction signal |
| `kalshi` | Regulated prediction market data (US) | Regulated signal layer |
| `binance_public` | Public CEX order book and funding rates | CEX context |
| `coinbase_public` | Public exchange data and asset listings | Asset reference |

---

## P2 Enrichment — Signal Depth

P2 providers add context and identity enrichment on top of the P1 backbone.
They should not block P1 launches but should follow within the same quarter.

| Slug | Description | Depends on |
|---|---|---|
| `etherscan` | Ethereum address labels, contract metadata | Dune (dedup) |
| `the_graph` | Subgraph queries for protocol-specific data | Dune (complement) |
| `farcaster_neynar` | Farcaster social graph via Neynar API | Identity bridge |
| `lens_protocol` | Lens social graph and publication data | Identity bridge |
| `ens_public` | ENS name resolution and reverse lookup | Identity bridge |
| `snapshot` | DAO governance proposals and votes | Social signal |
| `github_api` | Repository activity and contributor graph | Social signal |
| `alchemy` | Enhanced APIs, NFT metadata, simulations | Enrichment layer |
| `moralis` | Cross-chain NFT and token metadata | Enrichment layer |
| `solscan` | Solana address labels and program data | Chain enrichment |

---

## P3 Depth — Specialized and Gated Sources

P3 providers require either elevated budget approval, legal review, or both.
Several are disabled due to compliance exposure from their data-licensing terms.

| Slug | Status | Category | Blocker |
|---|---|---|---|
| `twitter_x` | DISABLED_COMPLIANCE | Social | API ToS prohibits derived signals |
| `reddit` | DISABLED_COMPLIANCE | Social | Content license conflict |
| `telegram` | DISABLED_COMPLIANCE | Social | No legitimate API for bulk data |
| `discord` | DISABLED_COMPLIANCE | Social | Bot ToS restricts data retention |
| `covalent` | PLANNED | Multi-chain | Budget approval pending |
| `flipside` | PLANNED | Analytics | Overlaps with Dune; needs scope review |
| `opensea` | PLANNED | NFT | Rate-limit and cost evaluation |
| `reservoir` | PLANNED | NFT | Aggregator overlap with OpenSea |
| `token_terminal` | PLANNED | Protocol metrics | Licensing cost review |
| `nansen` | PLANNED | Wallet labels | High cost; BYOK path preferred |
| `arkham` | PLANNED | Entity intel | Competitive positioning review |
| `chainalysis` | PLANNED | Compliance | Enterprise contract required |
| `elliptic` | PLANNED | Compliance | Enterprise contract required |

---

## Compliance-disabled providers

The four social providers (`twitter_x`, `reddit`, `telegram`, `discord`) are
intentionally disabled, not deprioritized. Their APIs prohibit scraping,
secondary use, or bulk data export in ways that would expose Aether to:

- Terms-of-service breach and account suspension.
- GDPR Article 6 lawful basis challenges for non-consensual processing.
- Potential CFAA exposure for automated access beyond allowed scopes.

Re-enabling any of these requires a written legal opinion from Aether's counsel
and a DataRightsGrant record that documents the lawful basis. Do not enable
them under a BYOK arrangement without this review.

---

## Provider registration rules

1. Every provider must have a catalog entry before any code references it.
2. `ImplementationStatus = ACTIVE` requires a successful smoke test and a
   documented SLA expectation.
3. Providers with `DISABLED_COMPLIANCE` status must not appear in feature flags,
   routing config, or UI dropdowns without explicit re-enablement approval.
4. Cost tier changes must be reviewed by the data engineering lead before
   any new provider reaches `ACTIVE` status.

---

## Related docs

- `DUNE_DATA_LAKE_STRATEGY.md` — Dune's special role within the P1 set.
- `CONNECTOR_TAXONOMY.md` — ConnectorClass and policy classification.
- `DATA_RIGHTS_LEDGER.md` — Grant model governing what Olympus data may be used for.
