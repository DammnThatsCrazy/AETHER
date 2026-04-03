# Aether

Cross-platform Unified Intelligence Graph with Web3 wallet tracking, cross-device identity resolution, data lake, ML-powered intelligence, and on-chain reward automation.

## Architecture

Aether is a **hybrid Python/FastAPI + Node/TypeScript** monorepo with three operational planes:

```
┌─────────────────────────────┐     ┌──────────────────────────────────────┐
│   Client SDKs               │     │   Python/FastAPI Backend              │
│   (Web/iOS/Android/RN)      │     │   31 service routers + intelligence  │
│                             │     │                                      │
│   Raw events, fingerprints  │ ──> │   /v1/ingest/*    Event ingestion    │
│   Wallet connections        │     │   /v1/lake/*      Data lake CRUD     │
│   Session + identity        │     │   /v1/intelligence/* Live outputs    │
│   Consent gates             │     │   /v1/identity/*  Identity/graph     │
│                             │     │   /v1/ml/*        ML inference       │
└─────────────────────────────┘     │   /v1/admin/*     Tenant/key mgmt   │
                                    │   /v1/providers/*  BYOK gateway      │
┌─────────────────────────────┐     │   /v1/agent/*     Agent orchestration│
│   External Data Providers   │     │   /v1/rewards/*   On-chain rewards   │
│   (24 connectors)           │ ──> │   /v1/analytics/* Dashboards/export  │
│                             │     │   /v1/profile/*   Profile 360        │
│                             │     │   /v1/population/* Group intelligence │
│                             │     │   /v1/expectations/* Negative-space  │
│                             │     │   /v1/behavioral/* Friction signals  │
│                             │     │   /v1/rwa/*       RWA intelligence   │
│   Market, social, on-chain  │     └──────────────────────────────────────┘
│   TradFi, prediction mkts   │                    │
│   Identity enrichment       │     ┌──────────────┴───────────────────────┐
└─────────────────────────────┘     │   Infrastructure                     │
                                    │   PostgreSQL (asyncpg)               │
                                    │   Redis (redis.asyncio)              │
                                    │   Neptune (gremlinpython)            │
                                    │   Kafka (aiokafka)                   │
                                    │   S3 (model artifacts + lake)        │
                                    │   Prometheus (metrics)               │
                                    └──────────────────────────────────────┘
```

### Data Flow: Extraction to Intelligence

```
Provider connectors (24) → POST /v1/lake/ingest → Bronze (raw, immutable)
                                                       ↓
                                                  Silver (validated, normalized)
                                                       ↓
                                                  Gold (features, metrics, highlights)
                                                       ↓
                                        ┌──── Redis (online features)
                                        ├──── Neptune (graph edges)
                                        ├──── ML Training → Model Registry
                                        └──── Intelligence API
                                               ├── /v1/intelligence/wallet/{addr}/risk
                                               ├── /v1/intelligence/protocol/{id}/analytics
                                               ├── /v1/intelligence/entity/{id}/cluster
                                               └── /v1/intelligence/alerts
```

## Infrastructure

| Store | Backend | Purpose | Env Var |
|-------|---------|---------|---------|
| **PostgreSQL** | asyncpg | Lake tiers, repos, model registry | `DATABASE_URL` |
| **Redis** | redis.asyncio | Cache, features, rate limiting, auth | `REDIS_HOST` |
| **Neptune** | gremlinpython | Intelligence graph (4 relationship layers) | `NEPTUNE_ENDPOINT` |
| **Kafka** | aiokafka | Event streaming (40+ topics) | `KAFKA_BOOTSTRAP_SERVERS` |
| **S3** | boto3 | Model artifacts, lake objects | AWS credentials |
| **Prometheus** | prometheus_client | Metrics at `/v1/metrics` | Auto-detected |

All stores auto-select real backends in staging/production and fall back to in-memory in `AETHER_ENV=local`.

## SDKs

| Platform | Package | Size |
|---|---|---|
| **Web** | `@aether/web` | ~5,200 LOC |
| **iOS** | `AetherSDK` (Swift) | ~535 LOC |
| **Android** | `io.aether:sdk-android` (Kotlin) | ~493 LOC |
| **React Native** | `@aether/react-native` | ~497 LOC |

## Provider Connectors (24)

| Category | Providers | Auth |
|----------|-----------|------|
| Blockchain RPC | QuickNode, Alchemy, Infura, Generic | API key |
| Block Explorer | Etherscan, Moralis | API key |
| Social | Twitter, Reddit | OAuth/Bearer |
| Analytics | Dune Analytics | API key |
| Market Data | DeFiLlama (free), CoinGecko, Binance, Coinbase | API key |
| Prediction Markets | Polymarket, Kalshi | Bearer |
| Web3 Social | Farcaster, Lens Protocol | API key |
| Identity Enrichment | ENS (free), GitHub | PAT |
| Governance | Snapshot (free) | None |
| On-Chain Intel | Chainalysis, Nansen | Contract required |
| TradFi | Massive, Databento | Contract required |

All connectors use real httpx HTTP calls. Unconfigured providers report `not_configured`. See `PROVIDER_MATRIX.md` for details.

## Intelligence Graph

4 relationship layers powered by Neptune graph:

| Layer | Description |
|---|---|
| **H2H** | Human-to-Human — referral chains, shared wallets, social graph |
| **H2A** | Human-to-Agent — delegation, tool invocations, approval flows |
| **A2H** | Agent-to-Human — notifications, recommendations, escalations |
| **A2A** | Agent-to-Agent — orchestration, payments, protocol composition |

**V1 activation:** Intelligence Graph services are available and can be enabled per-environment via `IG_AGENT_LAYER=true`, `IG_COMMERCE_LAYER=true`, `IG_ONCHAIN_LAYER=true`, `IG_X402_LAYER=true`. Graph mutations are fueled by the lake Silver/Gold tiers, not ad-hoc scripts.

## ML Models (11)

| Model | Type | Status |
|-------|------|--------|
| Intent Prediction | LogisticRegression | Training pipeline ready |
| Bot Detection | RandomForest | Training pipeline ready |
| Session Scoring | LogisticRegression | Training pipeline ready |
| Identity Resolution | Binary classification | Training pipeline ready |
| Journey Prediction | Multi-class | Training pipeline ready |
| Churn Prediction | XGBoost | Training pipeline ready |
| LTV Prediction | XGBoost | Training pipeline ready |
| Anomaly Detection | IsolationForest | Training pipeline ready |
| Campaign Attribution | Multi-touch | Training pipeline ready |
| Bytecode Risk | Rule-based | Active |
| Trust Score | Composite (weighted ML outputs) | Active |

Model artifacts require training run before serving. See `docs/ML-TRAINING-GUIDE.md`.

## Quick Start

```bash
# Local development (no infrastructure required)
pip install -e ".[dev,backend]"
export AETHER_ENV=local
make test                              # 191+ tests pass

# Staging with Docker
cd deploy/staging
./bootstrap.sh                         # starts PostgreSQL, Redis, Kafka, backend, ML serving
curl http://localhost:8000/v1/health   # verify all dependencies healthy
```

## Project Structure

```
Backend Architecture/aether-backend/   Python/FastAPI backend (31 services)
  services/
    ingestion/     SDK event ingestion + IP enrichment
    lake/          Data lake API (Bronze/Silver/Gold + audit + rollback)
    intelligence/  Intelligence outputs (risk, analytics, clusters, alerts)
    identity/      Identity management + graph
    resolution/    Cross-device identity resolution
    analytics/     Dashboard queries, GraphQL, export
    ml_serving/    ML model inference
    agent/         Agent orchestration + A2H
    rewards/       On-chain reward automation
    admin/         Tenant + API key management
    providers/     BYOK provider gateway
    ...            + 13 more service routers
  repositories/
    repos.py       Base repository (asyncpg PostgreSQL)
    lake.py        Bronze/Silver/Gold repositories
  shared/
    graph/         Neptune graph client + relationship layers
    events/        Kafka event bus
    cache/         Redis cache
    providers/     24 provider adapters (11 categories)
    auth/          API key validation + JWT
    scoring/       Trust score + bytecode risk

ML Models/aether-ml/                   ML training + serving
  training/        9 model training pipelines
  serving/         FastAPI inference API (port 8080)
  features/        Feature engineering pipeline

packages/                              Client SDKs
  web/             Web SDK (TypeScript)
  ios/             iOS SDK (Swift)
  android/         Android SDK (Kotlin)
  react-native/    React Native SDK

deploy/staging/                        Staging deployment package
  bootstrap.sh     One-command staging setup
  docker-compose.staging.yml

Agent Layer/                           Autonomous agent workers
  agent_controller/      Multi-controller autonomy hierarchy
  workers/               10 specialist workers (discovery + enrichment)
  guardrails/            PII detection, policy enforcement

Data Ingestion Layer/                  Node.js event ingestion service
  packages/              5 shared packages (common, auth, cache, events, logger)
  services/ingestion/    HTTP ingestion server (port 3001)

security/                              Model extraction defense
  model_extraction_defense/  6-component defense layer

scripts/                               Operational scripts
  generate_secrets.py    Production secret generation
  bump_version.py        Atomic version bumping across all files
  validate_infra.py      Infrastructure validation
  validate_docs.py       Documentation version checks
  sync_docs.py           Regenerate deterministic doc artifacts
```

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | System design, hybrid architecture, data flow |
| [Backend API](docs/BACKEND-API.md) | All API endpoints with request/response examples |
| [Intelligence Graph](docs/INTELLIGENCE-GRAPH.md) | Graph layers, edge types, scoring, V1 activation |
| [Identity Resolution](docs/IDENTITY-RESOLUTION.md) | Cross-device matching algorithms |
| [ML Training Guide](docs/ML-TRAINING-GUIDE.md) | Model training, artifacts, ingestion readiness |
| [Production Readiness](docs/PRODUCTION-READINESS.md) | Infrastructure status, deployment prerequisites |
| [Operations Runbook](docs/OPERATIONS-RUNBOOK.md) | Failure modes, recovery, operational procedures |
| [Secret Rotation](docs/SECRET-ROTATION.md) | Secret generation and rotation procedures |
| [Extraction Defense](docs/MODEL-EXTRACTION-DEFENSE.md) | ML model extraction defense architecture |
| [Provider Matrix](PROVIDER_MATRIX.md) | 24 providers with auth, env vars, health states |
| [Execution Tracker](EXECUTION_TRACKER.md) | Phase completion status across all workstreams |
| [Changelog](docs/CHANGELOG.md) | Version history |
| [Contributing](CONTRIBUTING.md) | Development setup, standards, PR process |

### Subsystem Docs

| Subsystem | Document |
|-----------|----------|
| Cache/Redis | [docs/SUBSYSTEM-CACHE.md](docs/SUBSYSTEM-CACHE.md) |
| Events/Kafka | [docs/SUBSYSTEM-EVENTS.md](docs/SUBSYSTEM-EVENTS.md) |
| PostgreSQL/Schema | [docs/SUBSYSTEM-DATABASE.md](docs/SUBSYSTEM-DATABASE.md) |

## License

Proprietary. All rights reserved.
