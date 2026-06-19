---
title: Unique Signal Features
slug: architecture/unique-signal-features
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: ml@aether
source_files:
  - Backend Architecture/aether-backend/services/unique_signals/models.py
last_synced_commit: "pending"
estimated_read_minutes: 7
---

# Unique Signal Features

> Aether's intelligence edge comes from combining signals that no single provider
> offers. This document defines the five cross-source signal combinations that
> produce uniquely valuable features, including their source dependencies, model
> outputs, and the credentials required to unlock them.

## What makes a signal "unique"

A unique signal combination is one that:

1. Requires data from at least two independent provider sources.
2. Produces a feature that is not derivable from either source alone.
3. Feeds at least one ML model with materially improved prediction accuracy.
4. Cannot be purchased as a pre-built feature from any existing vendor.

---

## Signal 1: Prediction Market On-Chain Correlation

**Slug:** `pred_market_onchain_corr`

### Description

Correlates prediction market contract positions (Polymarket, Kalshi) with
on-chain wallet activity in the 48-hour window before and after market
resolution. This captures whether wallets that held winning positions also
transacted on-chain in ways consistent with having informed prior knowledge.

### Sources required

| Source | Data used |
|---|---|
| `polymarket_gamma` | Market contracts, positions, resolution outcomes |
| `kalshi` | Regulated market positions and resolution |
| `dune` | Wallet transaction history, token transfers |
| `coingecko` | Asset price time series for normalization |

### Output features

- `pred_market_alpha_score` — likelihood wallet has predictive edge
- `resolution_correlation_30d` — position accuracy rate over 30 days
- `onchain_pre_resolution_activity` — abnormal on-chain activity before resolution

### Models fed

`prediction_market`, `anomaly_detection`, `fraud_detection`

### Blocking credentials

Requires active credentials for `polymarket_gamma` and `kalshi`. Without both,
this feature falls back to single-market analysis only.

---

## Signal 2: Web3 Social Identity Graph

**Slug:** `web3_social_identity`

### Description

Builds a unified identity graph by linking ENS names, Farcaster profiles, and
Lens handles to on-chain wallet addresses. The resulting graph exposes
multi-platform identity clusters that are invisible when looking at any one
social protocol.

### Sources required

| Source | Data used |
|---|---|
| `ens_public` | ENS name to wallet address resolution |
| `farcaster_neynar` | Farcaster FID to connected wallets |
| `lens_protocol` | Lens handle to wallet address |
| `dune` | Wallet activity to validate identity linkages |

### Output features

- `identity_cluster_size` — number of cross-platform identities linked
- `social_graph_depth` — follower/following network depth
- `identity_confidence_score` — confidence that all linked handles are the same entity
- `multi_platform_presence` — boolean; presence on 2+ social protocols

### Models fed

`bot_detection`, `social_sentiment`, `intent_prediction`, `attribution`

### Blocking credentials

ENS is public (no credential required). Neynar API key required for Farcaster.
Lens Protocol public API available; Lens Pro key improves rate limits.

---

## Signal 3: CEX Funding Rate Behavioral Prediction

**Slug:** `cex_funding_behavioral`

### Description

Tracks perpetual contract funding rates on Binance and Coinbase against on-chain
wallet behavior of large holders. When funding rates diverge significantly from
spot price movements, the correlated on-chain activity often precedes a trend
reversal. This feature captures that pattern at the wallet level.

### Sources required

| Source | Data used |
|---|---|
| `binance_public` | Perpetual funding rates, open interest |
| `coinbase_public` | Spot price, order book imbalance |
| `dune` | Whale wallet on-chain accumulation and distribution |
| `coingecko` | Multi-exchange price normalization |

### Output features

- `funding_divergence_score` — magnitude of funding vs. spot divergence
- `whale_positioning` — net long/short positioning inferred from on-chain
- `reversal_probability_48h` — model prediction of trend reversal within 48h

### Models fed

`whale_detection`, `prediction_market`, `anomaly_detection`

### Blocking credentials

`binance_public` and `coinbase_public` are public APIs (no key required for
basic data). High-frequency access requires rate-limit management.

---

## Signal 4: GitHub Abandonment Risk

**Slug:** `github_abandonment_risk`

### Description

Combines GitHub repository activity (commit cadence, contributor departures,
issue aging) with protocol TVL trends from DeFiLlama. Protocols whose developer
activity is declining while TVL remains elevated represent an unrecognized risk:
the smart money has not moved yet, but the development signal suggests imminent
decline.

### Sources required

| Source | Data used |
|---|---|
| `github_api` | Commit frequency, contributor count, issue close rate |
| `defi_llama` | Protocol TVL time series, chain breakdown |
| `the_graph` | Protocol-specific on-chain usage metrics |

### Output features

- `dev_activity_trend_90d` — rolling 90-day developer activity direction
- `contributor_departure_rate` — percentage of core contributors who went silent
- `tvl_dev_divergence_score` — gap between TVL trend and dev activity trend
- `abandonment_risk_tier` — categorical: LOW / MEDIUM / HIGH / CRITICAL

### Models fed

`protocol_health`, `anomaly_detection`, `fraud_detection`

### Blocking credentials

GitHub API key required; without it, this feature is unavailable.
GitHub rate limits (5,000 req/hr authenticated) must be managed with caching.

---

## Signal 5: Social and Whale Coordination Detection

**Slug:** `social_whale_coordination`

### Description

Detects coordinated activity between large wallet holders (whales) and social
media amplification events. When a wallet cluster begins accumulating a token
within 24 hours of abnormal social graph activity around that token, it suggests
coordinated pump behavior or organized community buy campaigns.

### Sources required

| Source | Data used |
|---|---|
| `farcaster_neynar` | Cast volume and engagement spikes per token |
| `lens_protocol` | Lens publication frequency for token mentions |
| `dune` | Whale wallet accumulation events |
| `coingecko` | Volume and price anomaly detection |

### Output features

- `social_spike_detected` — boolean; abnormal social activity in 24h window
- `whale_accumulation_concurrent` — boolean; whale buys within same window
- `coordination_confidence_score` — 0.0–1.0 confidence of coordination
- `implicated_wallets` — list of wallet addresses in the coordination cluster

### Models fed

`whale_detection`, `social_sentiment`, `fraud_detection`, `anomaly_detection`

### Blocking credentials

Neynar API key required for Farcaster volume data. Lens public API sufficient
for publication frequency.

---

## Feature availability matrix

| Signal slug | Min sources needed | Degraded mode available? |
|---|---|---|
| `pred_market_onchain_corr` | polymarket + dune | Yes (single-market) |
| `web3_social_identity` | ens + 1 social | Yes (single-platform) |
| `cex_funding_behavioral` | binance + dune | Yes (no reversal prediction) |
| `github_abandonment_risk` | github + defi_llama | No (all three required) |
| `social_whale_coordination` | farcaster + dune | No (both required) |

---

## Related docs

- `SOURCE_TO_MODEL_MATRIX.md` — All provider-to-model dependencies.
- `OLYMPUS_PROVIDER_SOURCE_CATALOG.md` — Provider catalog with status.
- `ENRICHMENT_LINEAGE.md` — Lineage tracking for cross-source features.
