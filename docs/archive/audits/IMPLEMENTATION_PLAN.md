---
title: Implementation Plan
slug: archive/audits/implementation_plan
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Aether Implementation Plan — Repo Truth to Production

**Based on:** REPO_AUDIT.md ground truth inspection
**Goal:** Complete the data ingestion → lake → features → graph → training → serving → intelligence pipeline

## Execution Priority Order

### Phase 1: Provider Connectors (Tier 1)
**Why first:** Without data flowing in, nothing downstream works.

| Provider | Category | Auth | Ingestion Mode | Landing Zone | Priority |
|----------|----------|------|---------------|-------------|----------|
| DeFiLlama | Market Data | None (public API) | REST polling | `bronze/market/defillama/` | **P0** |
| CoinGecko | Market Data | API key | REST polling | `bronze/market/coingecko/` | **P0** |
| Binance | CEX Data | API key + secret | REST + WebSocket | `bronze/cex/binance/` | **P0** |
| Coinbase | CEX Data | API key + secret | REST | `bronze/cex/coinbase/` | **P0** |
| Polymarket | Prediction Market | API key | REST polling | `bronze/prediction/polymarket/` | **P1** |
| Kalshi | Prediction Market | API key + secret | REST | `bronze/prediction/kalshi/` | **P1** |
| Farcaster | Social/Web3 | Hub API | REST/gRPC | `bronze/social/farcaster/` | **P1** |
| Lens | Social/Web3 | API key | GraphQL | `bronze/social/lens/` | **P2** |
| GitHub | Developer | PAT | REST/GraphQL | `bronze/social/github/` | **P2** |

**Implementation pattern:** Extend `shared/providers/categories.py` with new provider classes following the existing `_BaseRPCProvider` / httpx pattern.

### Phase 2: Lake Formation (Bronze → Silver → Gold)
**Why second:** Data must be organized before features/graph/training can consume it.

The Data Lake Architecture has real ETL code in TypeScript. The Python backend has PostgreSQL repos.

**Decision:** Use Python-side PostgreSQL JSONB tables for the lake tiers, matching the existing repo pattern. The TypeScript ETL can feed into the same tables or S3.

| Tier | Purpose | Storage | Implementation |
|------|---------|---------|---------------|
| Bronze | Raw provider responses | PostgreSQL JSONB + S3 Parquet | New `LakeRepository` extending `BaseRepository` |
| Silver | Validated, typed, deduped | PostgreSQL JSONB | Transform functions per provider |
| Gold | Features, metrics, highlights | PostgreSQL JSONB + Redis cache | Materialization jobs |

### Phase 3: Feature Materialization
**Why third:** ML training needs features.

The feature pipeline exists in `ML Models/aether-ml/features/pipeline.py`. It needs:
- Connection to the lake tiers for input data
- Scheduling for periodic materialization
- Online feature serving via Redis (already implemented)

### Phase 4: Graph Mutations from Lake
**Why fourth:** Intelligence graph should be fueled by lake data, not ad-hoc.

- Enable Intelligence Graph feature flags in staging config
- Add lake-to-graph mutation jobs that create edges from Silver/Gold data
- Wire graph scoring (trust, bytecode) to use lake-derived features

### Phase 5: ML Training Pipeline
**Why fifth:** Features and lake must exist before training.

- Wire feature pipeline to lake
- Run training with real data (blocked until data flows)
- Register artifacts in S3
- Version models

### Phase 6: Intelligence Outputs
**Why last:** Everything upstream must work first.

- Wallet risk scores via trust scorer + graph
- Protocol analytics via lake Gold tier
- Identity clusters via resolution service + graph
- Anomaly alerts via anomaly detection model
- Cross-domain intelligence via graph relationship layers

## Responsibility Map

| Responsibility | Owner | Technology |
|---------------|-------|-----------|
| API serving | Python/FastAPI backend | FastAPI, Pydantic |
| Identity/auth | Python/FastAPI backend | Redis, PostgreSQL |
| Graph mutations | Python/FastAPI backend | Neptune/gremlinpython |
| ML inference | Python/ML serving | FastAPI, sklearn, xgboost |
| Provider connectors | Python/FastAPI backend | httpx |
| Lake write path | Python/FastAPI backend | PostgreSQL JSONB, S3 |
| ETL/transforms | Python + TypeScript ETL | asyncpg, Node scheduler |
| Feature generation | Python ML pipeline | pandas, numpy, Redis |
| Training orchestration | Python training pipeline | sklearn, xgboost, mlflow |
| Model artifacts | S3 | boto3 |
| Observability | Prometheus + logging | prometheus_client |
| Governance/rollback | PostgreSQL audit trail | source_tag, timestamps |

## What Can Be Built Now vs What Requires External Resources

### Buildable Now (in repo)
- Provider connector code for all Tier 1/2/3 providers
- Lake repository classes and table schemas
- Feature materialization scheduling
- Graph mutation jobs
- Provider health/status reporting
- Source tag auditing
- PROVIDER_MATRIX.md and DATAFLOW_MATRIX.md

### Requires External Resources
- Provider API credentials (per-provider)
- AWS infrastructure (for managed services)
- Training data (for ML model artifacts)
- Snowflake account (for warehouse path)
