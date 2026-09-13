---
title: Provider Matrix
slug: archive/audits/provider_matrix
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Aether Provider Matrix

## Implemented Providers (24 total)

| Provider | Category | Auth Mode | Env Var | Base URL | Rate Limit | Status |
|----------|----------|-----------|---------|----------|-----------|--------|
| **QuickNode** | Blockchain RPC | API key header | `QUICKNODE_API_KEY` | Custom per-account | 100 RPS | ✅ Implemented |
| **Alchemy** | Blockchain RPC | Key in URL | `ALCHEMY_API_KEY` | `{chain}.g.alchemy.com/v2/{key}` | 330 CU/s | ✅ Implemented |
| **Infura** | Blockchain RPC | Key in URL | `INFURA_API_KEY` | `{network}.infura.io/v3/{key}` | 100K req/day | ✅ Implemented |
| **Generic RPC** | Blockchain RPC | Bearer token | `CUSTOM_RPC_KEY` | Custom | Varies | ✅ Implemented |
| **Etherscan** | Block Explorer | Query param | `ETHERSCAN_API_KEY` | `api.etherscan.io` | 5 req/s | ✅ Implemented |
| **Moralis** | Block Explorer | Header | `MORALIS_API_KEY` | `deep-index.moralis.io` | 25 req/s | ✅ Implemented |
| **Twitter/X** | Social | Bearer token | `TWITTER_BEARER_TOKEN` | `api.twitter.com/2` | 500K tweets/mo | ✅ Implemented |
| **Reddit** | Social | OAuth bearer | `REDDIT_API_KEY` | `oauth.reddit.com` | 60 req/min | ✅ Implemented |
| **Dune Analytics** | Analytics | Header | `DUNE_API_KEY` | `api.dune.com/api/v1` | Varies by plan | ✅ Implemented |
| **DeFiLlama** | Market Data | None (public) | — | `api.llama.fi` | ~300 req/5min | ✅ Implemented |
| **CoinGecko** | Market Data | Header (optional) | `COINGECKO_API_KEY` | `api.coingecko.com/api/v3` | 30 req/min (free) | ✅ Implemented |
| **Binance** | CEX Data | Header | `BINANCE_API_KEY` | `api.binance.com/api/v3` | 1200 req/min | ✅ Implemented |
| **Coinbase** | CEX Data | Header | `COINBASE_API_KEY` | `api.coinbase.com/v2` | 10K req/hr | ✅ Implemented |
| **Polymarket** | Prediction Mkt | Bearer (optional) | `POLYMARKET_API_KEY` | `gamma-api.polymarket.com` | Rate limited | ✅ Implemented |
| **Kalshi** | Prediction Mkt | Bearer | `KALSHI_API_KEY` | `trading-api.kalshi.com` | Rate limited | ✅ Implemented |
| **Farcaster** | Web3 Social | Header | `FARCASTER_API_KEY` | `api.neynar.com/v2/farcaster` | Varies by plan | ✅ Implemented |
| **Lens Protocol** | Web3 Social | Header | `LENS_API_KEY` | `api.lens.dev` | Rate limited | ✅ Implemented |
| **ENS** | Identity Enrichment | None (public) | — | `api.ensideas.com` | Rate limited | ✅ Implemented |
| **GitHub** | Developer | Bearer token | `GITHUB_API_TOKEN` | `api.github.com` | 5K req/hr | ✅ Implemented |
| **Snapshot** | Governance | None (public) | — | `hub.snapshot.org/graphql` | Rate limited | ✅ Implemented |
| **Chainalysis** | On-chain Intel | Header | `CHAINALYSIS_API_KEY` | `api.chainalysis.com/v1` | Contract-gated | ✅ Implemented |
| **Nansen** | On-chain Intel | Header | `NANSEN_API_KEY` | `api.nansen.ai/v1` | Contract-gated | ✅ Implemented |
| **Massive** | TradFi Data | Header | `MASSIVE_API_KEY` | `api.massive.io/v1` | Contract-gated | ✅ Implemented |
| **Databento** | TradFi Data | Header | `DATABENTO_API_KEY` | `hist.databento.com/v0` | Contract-gated | ✅ Implemented |

## Provider Health States

Every provider reports one of:
- `healthy` — credentials present, API reachable
- `degraded` — API reachable but experiencing errors
- `unavailable` — credentials missing or API unreachable
- `not_configured` — no env var set for this provider

## Adding a New Provider

1. Create class extending `Provider` in `shared/providers/categories.py`
2. Implement `execute()` with real httpx calls
3. Implement `health_check()` returning `ProviderStatus`
4. Add to `PROVIDER_FACTORY` dict
5. Add to `CATEGORY_PROVIDERS` mapping
6. Add env var to `.env.example`
7. Document in this matrix
