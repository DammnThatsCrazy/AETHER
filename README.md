# Aether

**Unified observation layer for hybrid companies** — Web2, Web3, or any mix.
Cross-platform SDKs capture canonical events (analytics, identity, consent,
commerce, wallet, agent, x402) and deliver them to a Python/FastAPI backend
that owns all enrichment, identity resolution, graph mutation, and
orchestration.

> **Source of truth** for SDK behavior lives in [`docs/source-of-truth/`](docs/source-of-truth/).
> Canonical SDK contracts live in [`packages/shared/`](packages/shared/).
> Anything outside those locations that contradicts them is wrong.

## Quick links

- [`docs/source-of-truth/SDK_SCOPE.md`](docs/source-of-truth/SDK_SCOPE.md) — what the SDK is and is not
- [`docs/source-of-truth/EVENT_REGISTRY.md`](docs/source-of-truth/EVENT_REGISTRY.md) — every event the SDK emits
- [`docs/source-of-truth/CONSENT_MODEL.md`](docs/source-of-truth/CONSENT_MODEL.md) — 5 canonical consent purposes
- [`docs/source-of-truth/INGESTION_CONTRACT.md`](docs/source-of-truth/INGESTION_CONTRACT.md) — `POST /v1/batch`
- [`docs/source-of-truth/ENTITY_MODEL.md`](docs/source-of-truth/ENTITY_MODEL.md) — entities shared across Web2 + Web3
- [`docs/source-of-truth/PLATFORM_PARITY.md`](docs/source-of-truth/PLATFORM_PARITY.md) — tiers A/B/C

## Architecture

Aether is a **hybrid Python/FastAPI + Node/TypeScript** monorepo with four operational planes:

```
┌─────────────────────────────┐     ┌──────────────────────────────────────────┐
│   Client SDKs (@aether/*)   │     │   Python/FastAPI Backend                  │
│   web · ios · android · rn  │     │   35 service routers (28 core + 7 gated) │
│   shared contracts          │     │                                          │
│                             │     │   /v1/ingest/*       Event ingestion     │
│   Raw events, fingerprints  │ ──> │   /v1/lake/*         Data lake CRUD      │
│   Wallet connections        │     │   /v1/intelligence/* Live outputs        │
│   Session + identity        │     │   /v1/identity/*     Identity/graph      │
│   Consent gates             │     │   /v1/ml/*           ML inference        │
│   Commerce + x402 + agent   │     │   /v1/admin/*        Tenant/key mgmt     │
└─────────────────────────────┘     │   /v1/providers/*    BYOK gateway        │
                                    │   /v1/agent/*        Agent orchestration │
┌─────────────────────────────┐     │   /v1/rewards/*      On-chain rewards    │
│   External Data Providers   │     │   /v1/analytics/*    Dashboards/export   │
│   (24 connectors)           │ ──> │   /v1/profile/*      Profile 360         │
│                             │     │   /v1/population/*   Group intelligence  │
│                             │     │   /v1/expectations/* Negative-space      │
│                             │     │   /v1/behavioral/*   Friction signals    │
│                             │     │   /v1/rwa/*          RWA intelligence    │
│                             │     │   /v1/web3/*         Web3 coverage       │
│                             │     │   /v1/crossdomain/*  TradFi/Web2 entity  │
│   Market, social, on-chain  │     │   /v1/fraud/*        Fraud evaluation    │
│   TradFi, prediction mkts   │     │   /v1/attribution/*  Attribution models  │
│   Identity enrichment       │     │   /v1/oracle/*       Oracle proof/verify │
└─────────────────────────────┘     │   /v1/automation/*   Pipeline metrics    │
                                    │   /v1/diagnostics/*  System diagnostics  │
┌─────────────────────────────┐     │   — feature-flagged (Day-1 GA):          │
│   Kyber Operator Console    │     │   /v1/commerce/*     Commerce events     │
│   (@aether/kyber, React)    │ ──> │   /v1/onchain/*      On-chain capture    │
│   Review / Mission / Live   │     │   /v1/x402/*         x402 protocol       │
│   Noesis / Lab / Diagnostics  │     │   /v1/commerce-cp/*  Control plane       │
│   Command / Entities        │     │   /v1/approvals/*    Approval workflow   │
└─────────────────────────────┘     │   /v1/entitlements/* Entitlement service │
                                    └──────────────────────────────────────────┘
                                                      │
                                    ┌─────────────────┴────────────────────────┐
                                    │   Infrastructure                         │
                                    │   PostgreSQL (asyncpg) · Redis (asyncio) │
                                    │   Neptune (gremlinpython) · Kafka        │
                                    │   S3 (model artifacts + lake)            │
                                    │   Prometheus (metrics @ /v1/metrics)     │
                                    └──────────────────────────────────────────┘
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

Thin observation clients. All four POST to `/v1/batch`. All four share the
canonical contracts in [`packages/shared/`](packages/shared/). Parity tiers
are documented in
[`docs/source-of-truth/PLATFORM_PARITY.md`](docs/source-of-truth/PLATFORM_PARITY.md).

| Platform | Package | Entry |
|---|---|---|
| **Web** | `@aether/web` | `packages/web/src/index.ts` |
| **iOS** | `AetherSDK` (Swift SPM) | `packages/ios/Sources/AetherSDK/Aether.swift` |
| **Android** | `io.aether:sdk-android` (Kotlin) | `packages/android/src/main/java/com/aether/sdk/Aether.kt` |
| **React Native** | `@aether/react-native` | `packages/react-native/src/index.tsx` |
| **Shared contracts** | `packages/shared/` | canonical event / consent / identity / commerce / agent / wallet types |

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

## Economic Observability

Aether's graph model carries first-class agentic transaction awareness — payments, spend, revenue, and protocol-level handshakes — without adding a new graph layer. Every primitive is additive and optional, so existing events, edges, and state continue to validate unchanged. See [`docs/ECONOMIC-OBSERVABILITY.md`](docs/ECONOMIC-OBSERVABILITY.md) for the full spec.

**What you get:**

- `EconomicPayload` — embeddable `{ amount, currency, direction, counterparty_type, counterparty_id, rail }` block on any Action.
- `Handshake` — minimal `pending → paid | failed` node modelling x402-style payment handshakes (indexed by `request_id`).
- `ResourceNode` — single generic resource (campaign, ad_account, bank_account, api, model) with extensible `metadata`.
- `RelationshipExtensions` — `flow_ref`, `interaction_mode` (H2H / H2A / A2A / A2H), `economic_involved`, and causal `outcome`.
- `EconomicState` — derived `{ spend_rate, total_spend, total_revenue, unit_cost }`, computed from Actions in O(n).
- `Authorization` — embedded `{ source, scope, limit }` for human/org/policy authorization.

**Example: Action carrying spend**

```ts
import type { EconomicPayload } from '@aether/shared';

const economic: EconomicPayload = {
  amount: 0.05,
  currency: 'USD',
  direction: 'pay',
  counterparty_type: 'service',
  counterparty_id: 'svc_x402_demo',
  rail: 'internal',
};

aether.track('agent_task', { taskId: 't1', agent, status: 'completed', economic });
```

**Handshake flow (x402-style):**

```
Buyer Agent ──GET──▶ Paid API
            ◀─402 ── (Handshake { id, required_amount, status: pending })
Buyer Agent ──pay──▶ Paid API
            ◀─200── (Handshake { status: paid }, resolves_to → payment Action)
```

**A2A payment example:**

```ts
import { createHandshake, transitionHandshake } from '@aether/shared';

let hs = createHandshake({
  id: 'hs_1', request_id: 'req_1', required_amount: 0.05, timestamp: Date.now(),
});
hs = transitionHandshake(hs, 'paid'); // pending → paid
```

End-to-end examples (campaign spend → revenue, agent paying API, A2A transfer) live in [`docs/examples/economic/`](docs/examples/economic/).

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
pip install -e ".[dev,backend,agent,ml]"
npm ci                                 # install TypeScript workspaces
export AETHER_ENV=local
make test                              # Python tests (163 unit + integration + security)
npm test                               # JS tests (web + react-native + kyber, 89 tests)

# Full-stack Docker compose
docker compose up -d                   # postgres, redis, kafka, clickhouse, backend, ml-serving, kyber, prometheus
curl http://localhost:8000/v1/health   # backend
curl http://localhost:8080/health      # ml-serving
curl http://localhost:8081/health      # kyber operator console

# Staging
cd deploy/staging
./bootstrap.sh
```

### Deployment Topology

```
          ┌─────────────────┐
          │   Kyber (8081)  │  ◄──── operator console (React SPA via nginx)
          └────────┬────────┘
                   │
        ┌──────────┴──────────┐
        │   Backend (8000)    │  ◄──── FastAPI · 35 routers · JWT auth · tenants
        └──┬──────────────┬───┘
           │              │
  ┌────────┴─────┐  ┌─────┴───────────┐
  │ ml-serving   │  │ Infrastructure   │
  │ (8080)       │  │ postgres · redis │
  │ FastAPI infer│  │ kafka · clickhouse│
  └──────────────┘  │ prometheus (9090)│
                    └───────────────────┘
```

## Project Structure

```
Backend Architecture/aether-backend/   Python/FastAPI backend (35 routers, 246+ endpoints)
  main.py          FastAPI app factory, middleware, router mounting
  services/
    ingestion/         SDK event ingestion + IP enrichment
    lake/              Data lake API (Bronze/Silver/Gold + audit + rollback)
    intelligence/      Intelligence outputs (risk, analytics, clusters, alerts)
    identity/          Identity management + graph
    analytics/         Dashboard queries, GraphQL, export
    ml_serving/        ML model inference
    agent/             Agent orchestration + A2H
    rewards/           On-chain reward automation
    admin/             Tenant + API key management
    providers/         BYOK provider gateway
    profile/           Profile 360 endpoints
    population/        Group intelligence
    expectations/      Negative-space/expectation signals
    behavioral/        Friction & behavioral signals
    rwa/               RWA intelligence
    web3/              Web3 coverage + registry
    crossdomain/       TradFi/Web2 entity resolution
    fraud/             Fraud evaluation
    attribution/       Multi-touch attribution models
    oracle/            Oracle proof generation + verification
    analytics_automation/  Pipeline metrics + overview
    diagnostics/       System diagnostics
    traffic/           Traffic source detection
    campaign/          Campaign management
    consent/           Consent records + DSR workflow
    notification/      Webhooks + alerts
    gateway/           API gateway + health
    commerce/          Commerce events (feature-flagged)
    onchain/           On-chain capture (feature-flagged)
    x402/              x402 protocol + commerce control plane (feature-flagged)
  repositories/    Base repository (asyncpg PostgreSQL) + lake tiers
  shared/
    graph/           Neptune graph client + 4 relationship layers (H2H/H2A/A2H/A2A)
    events/          Kafka event bus + topic registry
    cache/           Redis cache
    providers/       24 provider adapters (11 categories)
    auth/            API key validation + JWT + tenant context
    scoring/         Trust score + bytecode risk + extraction score
    rate_limit/      Burst RPM (P1-P4), monthly quota engine, feature gate, metrics
    plans/           Plan catalog (P1-P4) + 34-service registry + endpoint resolver
    billing/         Per-service overage calculator + threshold notifications
    privacy/         PII detection + retention + redaction

packages/                              Client SDKs + shared contracts
  shared/          @aether/shared — canonical TypeScript contracts (events,
                   consent, wallet, identity, entities, commerce, agent,
                   capabilities, provenance, schema-version)
  web/             @aether/web — Web SDK (rollup → CJS/ESM/DTS)
  ios/             AetherSDK — Swift SPM package
  android/         io.aether:sdk-android — Kotlin
  react-native/    @aether/react-native — thin native bridge

apps/                                  First-party applications
  kyber/           @aether/kyber — operator control surface (React + Vite)
                   Mission · Live · Noesis · Entities · Command · Diagnostics
                   · Review · Lab; Playwright E2E + vitest unit/component/integ

ML Models/aether-ml/                   ML training + serving
  training/        9 model training pipelines
  serving/         FastAPI inference API (container port 8080)
  features/        Feature engineering pipeline
  monitoring/      Drift + model health monitoring
  edge/            Edge inference models
  docker/          Multi-stage Dockerfile (serving · features · monitoring)

Agent Layer/                           Autonomous agent workers
  agent_controller/  Multi-controller autonomy: Governance > Nous > domain
                     controllers (Intake, Discovery, Enrichment, Verification,
                     Commit, Recovery, Kinesis, Catalyst) + Cycle runtime + Atoms
  workers/           10 specialist workers (5 discovery + 5 enrichment)
  guardrails/        PII detection, policy enforcement, kill switch

Data Ingestion Layer/                  Node.js event ingestion service
  packages/        5 shared packages (common, auth, cache, events, logger)
  services/ingestion/  HTTP ingestion server (port 3001) with Kafka/ClickHouse/
                       S3/Redis production sinks (zero external deps)

Data Lake Architecture/                Data lake service (TypeScript)
  aether-Datalake-backend/  Bronze/Silver/Gold tiers + catalog + governance

security/                              Model extraction defense
  model_extraction_defense/  watermark · canary detector · output perturbation
                             · pattern detector · risk scorer · rate limiter

Smart Contracts/                       Solidity contracts + deployer
  AnalyticsRewards · RewardRegistry · multi-chain deployer

AWS Deployment/                        Cloud infrastructure
  aether-aws/      Terraform/CloudFormation + operational runbooks

GDPR & SOC2/                           Compliance package
  aether-compliance/  7-tier data classification · GDPR DSAR · SOC2 controls

cicd/aether-cicd/                      CI/CD pipeline definitions
  stages/          SDK manifest publisher · multichain deployer · seed data

scripts/                               Operational scripts
  generate_secrets.py    Production secret generation
  bump_version.py        Atomic version bumping across all files + docs
  validate_infra.py      Infrastructure connectivity validation
  validate_docs.py       Documentation version parity checks
  sync_docs.py           Regenerate deterministic doc artifacts
  migrate_extraction_mesh.py  Extraction defense mesh migrations

deploy/                                Deployment manifests
  staging/         docker-compose.staging.yml + bootstrap.sh + prometheus.yml
  observability/   Prometheus alert rules

tests/                                 Python test suite (163+ tests)
  unit/            Auth middleware, tenant isolation, API contracts,
                   cache layer, onchain RPC, privacy enforcement
  integration/     Backend end-to-end
  security/        Extraction defense + mesh tests
  load/            Locust load-test file

.github/workflows/                     CI/CD workflows
  repo-health.yml  Validate: lint, typecheck, build, test, madge, docs drift
  kyber-e2e.yml    Path-scoped Playwright E2E for apps/kyber + packages/shared
```

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | System design, hybrid architecture, data flow |
| [Backend API](docs/BACKEND-API.md) | All API endpoints with request/response examples |
| [Intelligence Graph](docs/INTELLIGENCE-GRAPH.md) | Graph layers, edge types, scoring, V1 activation |
| [Economic Observability](docs/ECONOMIC-OBSERVABILITY.md) | Economic primitives: Action.economic, Handshake, ResourceNode, derived state |
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
