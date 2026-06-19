---
title: Source to Model Matrix
slug: architecture/source-to-model-matrix
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: ml@aether
source_files:
  - Backend Architecture/aether-backend/services/provider_catalog/catalog.py
last_synced_commit: "pending"
estimated_read_minutes: 6
---

# Source to Model Matrix

> Each data provider feeds specific ML models. This matrix is the authoritative
> mapping between provider sources and the model consumers that depend on them.
> Use this document to assess the blast radius of a provider outage and to plan
> model retraining schedules.

## How to read this matrix

Rows are provider sources. Columns are ML model consumers. A checkmark indicates
that the model's training pipeline consumes signals derived from that source.
An "R" indicates the model uses the source for real-time inference only (not
training). Blank means no dependency.

---

## Model consumer definitions

| Model slug | Purpose |
|---|---|
| `intent_prediction` | Predicts user's next on-chain or protocol action |
| `bot_detection` | Classifies wallets and sessions as bot vs. human |
| `anomaly_detection` | Flags statistically unusual activity patterns |
| `fraud_detection` | Identifies high-confidence fraud signals |
| `session_scoring` | Scores session quality and engagement depth |
| `attribution` | Assigns credit to touchpoints in conversion journeys |
| `protocol_health` | Assesses protocol TVL, liquidity, and risk health |
| `social_sentiment` | Extracts sentiment from social graph signals |
| `whale_detection` | Identifies large-holder accumulation and distribution |
| `prediction_market` | Synthesizes prediction market probabilities |

---

## Source-to-model dependency matrix

| Source | intent | bot | anomaly | fraud | session | attribution | protocol | social | whale | pred_mkt |
|---|---|---|---|---|---|---|---|---|---|---|
| `dune` (on-chain txns) | T | T | T | T | | T | T | | T | |
| `dune` (wallet summary) | T | T | T | T | | | | | T | |
| `dune` (bridge flows) | | | T | T | | | T | | T | |
| `defi_llama` | | | T | | | | T | | | |
| `coingecko` | R | | T | | | | T | | T | T |
| `polymarket_gamma` | T | | T | | | | | | | T |
| `kalshi` | | | | | | | | | | T |
| `binance_public` | R | | T | | | | | | T | T |
| `coinbase_public` | R | | | | | | | | | |
| `etherscan` | | T | | T | | | | | | |
| `the_graph` | T | | T | | | | T | | | |
| `farcaster_neynar` | T | T | | | T | T | | T | | |
| `lens_protocol` | T | T | | | T | T | | T | | |
| `ens_public` | | T | | | | | | T | | |
| `snapshot` | | | | | | | T | T | | |
| `github_api` | | | | | | | T | T | | |
| `alchemy` | R | T | | | | | | | | |
| `moralis` | R | T | | | | | | | | |
| `solscan` | | T | T | T | | | | | T | |

**T** = used in training pipeline
**R** = used for real-time inference only

---

## High-blast-radius sources

The following sources feed four or more models. Outages have the widest impact
and should be treated as `CRITICAL` severity in on-call runbooks.

| Source | Models affected |
|---|---|
| `dune` (all modes) | intent, bot, anomaly, fraud, attribution, protocol, whale |
| `coingecko` | anomaly, protocol, whale, prediction_market |
| `binance_public` | anomaly, whale, prediction_market |
| `farcaster_neynar` | intent, bot, session, attribution, social |

---

## Model retraining schedule dependencies

When a source changes (schema migration, historical restatement, new provider
contract), the following retraining decisions apply:

| Change type | Action required |
|---|---|
| Provider backfills historical data | Retrain all T-marked models for that source |
| Provider changes schema | Update extraction, validate feature parity, retrain |
| Provider grant revoked | Mark tainted training batches; retrain without them |
| New source added | Retrain after 30+ days of data accumulation |

---

## Real-time inference source availability SLA

Models marked "R" for a source require that source at inference time. If the
source is unavailable, the model must either:

1. Serve a degraded result with a `signal_coverage: PARTIAL` flag, or
2. Fall back to a stale cached result with a `stale_since` timestamp.

The model must never return an inference result without flagging missing signals.
Silently degraded predictions are treated as incidents.

---

## Related docs

- `OLYMPUS_PROVIDER_SOURCE_CATALOG.md` — Full provider catalog.
- `DUNE_CHAIN_EXTRACTION_PLAN.md` — Chain extraction feeding dune-sourced models.
- `ENRICHMENT_LINEAGE.md` — Training lineage requirements per batch.
- `UNIQUE_SIGNAL_FEATURES.md` — Cross-source signals that feed multiple models.
