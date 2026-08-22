# Aether

**Entity-agnostic intelligence graph infrastructure** — Web2, Web3, AI-native, or any mix.
Cross-platform SDKs capture canonical events (analytics, identity, consent,
commerce, wallet, agent, x402) and deliver them to a Python/FastAPI backend
that owns all enrichment, identity resolution, graph mutation, and
orchestration. Profile360 surfaces unified intelligence for any entity type —
humans, organizations, AI agents, and onchain protocols.

> **Source of truth** for SDK behavior lives in [`docs/source-of-truth/`](docs/source-of-truth/).
> Canonical SDK contracts live in [`packages/shared/`](packages/shared/).
> Anything outside those locations that contradicts them is wrong.

## Quick links

- [`docs/source-of-truth/SDK_SCOPE.md`](docs/source-of-truth/SDK_SCOPE.md) — what the SDK is and is not
- [`docs/source-of-truth/EVENT_REGISTRY.md`](docs/source-of-truth/EVENT_REGISTRY.md) — every event the SDK emits
- [`docs/source-of-truth/CONSENT_MODEL.md`](docs/source-of-truth/CONSENT_MODEL.md) — canonical consent purposes (registry-derived from [`packages/shared/contracts/consent-registry.json`](packages/shared/contracts/consent-registry.json))
- [`docs/source-of-truth/INGESTION_CONTRACT.md`](docs/source-of-truth/INGESTION_CONTRACT.md) — `POST /v1/batch`
- [`docs/source-of-truth/ENTITY_MODEL.md`](docs/source-of-truth/ENTITY_MODEL.md) — entities shared across Web2 + Web3
- [`docs/source-of-truth/PLATFORM_PARITY.md`](docs/source-of-truth/PLATFORM_PARITY.md) — tiers A/B/C
- [`docs/architecture/BACKEND_INTELLIGENCE_ARCHITECTURE.md`](docs/architecture/BACKEND_INTELLIGENCE_ARCHITECTURE.md) — additive backend intelligence architecture blueprint

## Apps & productization

Three frontends (all run locally in `local-mocked` mode with no backend):
**Aether** (tenant, `frontend/aether`, :5175), **Kyber** (operator, `frontend/kyber`, :5174),
and the **Demo App** (`frontend/demo`, :5177) — a closed synthetic value-loop demo.
Ingestion works **with or without the SDK** (SDK or connectors/signed webhooks).

- Local dev & deployment: [`docs/LOCAL-DEVELOPMENT.md`](docs/LOCAL-DEVELOPMENT.md), [`docs/PRODUCTION-DEPLOYMENT.md`](docs/PRODUCTION-DEPLOYMENT.md), [`docs/ENVIRONMENT-VARIABLES.md`](docs/ENVIRONMENT-VARIABLES.md)
- Connectors & ingestion: [`docs/CONNECTORS.md`](docs/CONNECTORS.md), [`docs/DATA-INGESTION-PATHS.md`](docs/DATA-INGESTION-PATHS.md)
- Demo: [`docs/DEMO-APP.md`](docs/DEMO-APP.md) · API: [`docs/API-REFERENCE.md`](docs/API-REFERENCE.md) · SDKs: [`docs/SDKS.md`](docs/SDKS.md)
- Readiness: [`docs/PRODUCTIZATION-CHECKLIST.md`](docs/PRODUCTIZATION-CHECKLIST.md), [`docs/SECURITY-READINESS.md`](docs/SECURITY-READINESS.md), [`docs/PREPRODUCTION-READINESS.md`](docs/PREPRODUCTION-READINESS.md)

```bash
npm run test:all        # alias for `make ci-check` — the canonical PR completion gate
npm run security:audit  # secret scan + dependency audit
npm run compliance:readiness   # readiness inventory (not certification)
```

> Repository consistency is owned by `scripts/repo_doctor.py` + the root `Makefile`.
> `pyproject.toml` is the canonical platform version source;
> [`docs/source-of-truth/`](docs/source-of-truth/) owns canonical behavior;
> [`packages/shared/contracts/`](packages/shared/contracts/) owns canonical
> SDK / event / consent contracts. Generated docs must be regenerated
> (`make docs-fix`) and committed; source-linked docs must be reviewed before
> stamping. No PR is merge-ready unless `make ci-check` passes. `npm run test:all`
> is only an alias for `make ci-check`. Formal certification is not claimed unless
> actual certification artifacts exist.

## Architecture

Aether is a **hybrid Python/FastAPI + Node/TypeScript** monorepo with four operational planes:

```
┌─────────────────────────────┐     ┌──────────────────────────────────────────┐
│   Client SDKs (@aether/*)   │     │   Python/FastAPI Backend                  │
│   web · ios · android · rn  │     │   55 service routers (48 core + 7 gated) │
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
│   (51 providers, 17 cats)   │ ──> │   /v1/profile/*      Profile 360         │
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
├─────────────────────────────┤     │   /v1/entitlements/* Entitlement service │
│   Aether Customer App       │     └──────────────────────────────────────────┘
│   (@aether/aether, React)   │ ──>
│   Home / Account / Commerce │
│   Auth (PKCE OIDC)          │
└─────────────────────────────┘
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
Provider connectors (51 across 17 categories) → POST /v1/lake/ingest → Bronze (raw, immutable)
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
| **Kafka** | aiokafka | Event streaming (114 topics) | `KAFKA_BOOTSTRAP_SERVERS` |
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

## Provider Connectors (51 across 17 categories)

| Category | Providers |
|---|---|
| Blockchain RPC | QuickNode, Alchemy, Infura, Generic |
| Block Explorer | Etherscan, Moralis |
| Social API | Twitter/X, Instagram, TikTok, Reddit, YouTube, LinkedIn, Discord, GitHub, Snapchat, Pinterest, Telegram, Mastodon |
| Web3 Social | Farcaster, Lens Protocol |
| Market Data | DeFiLlama, CoinGecko, Binance, Coinbase |
| Analytics | Dune Analytics |
| Prediction Markets | Polymarket, Kalshi |
| Identity Enrichment | ENS, GitHub |
| Governance | Snapshot |
| On-Chain Intel | Chainalysis, Nansen |
| TradFi | Massive, Databento |
| Open Banking | Plaid |
| Credit Bureau | Experian, Equifax, TransUnion |
| Brokerage | Alpaca, IBKR, Schwab, Fidelity |
| Consumer Fintech | Robinhood, SoFi, CashApp, Chime |
| Payment Processor | PayPal, Venmo, Square, Stripe Connect, Zelle |
| E-commerce Platform | Shopify, WooCommerce, Amazon Seller |
| Ad Platforms | Twitter Ads, Google Ads, LinkedIn Ads, Meta Ads, TikTok Ads |

All connectors use real httpx HTTP calls with BYOK key vault. Unconfigured providers report `not_configured`.

## Intelligence Graph

4 relationship layers powered by Neptune graph:

| Layer | Description |
|---|---|
| **H2H** | Human-to-Human — referral chains, shared wallets, social graph |
| **H2A** | Human-to-Agent — delegation, tool invocations, approval flows |
| **A2H** | Agent-to-Human — notifications, recommendations, escalations |
| **A2A** | Agent-to-Agent — orchestration, payments, protocol composition |

**V1 activation:** Intelligence Graph services are available and can be enabled per-environment via `IG_AGENT_LAYER=true`, `IG_COMMERCE_LAYER=true`, `IG_ONCHAIN_LAYER=true`, `IG_X402_LAYER=true`. Graph mutations are fueled by the lake Silver/Gold tiers, not ad-hoc scripts.

## Profile360

Multi-dimensional entity intelligence surface for any entity type — human, organization, AI agent, or onchain protocol.
All sub-resources support `?window=30d|60d|90d|lifetime` and include `data_freshness` (live / recent / stale) + `computed_at`.

| Sub-Resource | Entity Types | Covers |
|---|---|---|
| `social_intelligence` | All | 20+ platforms: followers, engagement, cross-platform influence tier |
| `web2` | Human | Bank accounts (Plaid), brokerage positions, credit signal, P2P payments |
| `ecommerce_profile` | Organization | GMV, AOV, conversion rate, cart abandonment, repeat purchase rate |
| `saas_profile` | Organization | MRR, ARR, churn rate, NRR, NPS |
| `customer_intelligence` | Organization | LTV distribution, retention rate, segment breakdown |
| `customer_relationships` | Human | Organizations an individual subscribes to / shops at / works for |
| `temporal_heatmap` | All | 24×7 activity heatmap, streaks, behavioral velocity score, dormancy |
| `location_history` | All | Primary / secondary / rare cities with ASN connection type |
| `economic_flow` | All | Cross-rail inflow/outflow (web2_ach, web2_card, web2_p2p, web3_onchain, web3_l2) |
| `agent_activity` | AI Agent | Execution history, spending, delegation chain, authorized capabilities |
| `graph_traversal` | All | N-hop configurable BFS + PageRank-style influence scoring (max 500 nodes) |

See [`docs/PROFILE-360-AGGREGATION.md`](docs/PROFILE-360-AGGREGATION.md) for the full aggregator spec.

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

## ML Intelligence Outputs (11)

Aether produces 11 intelligence outputs: **9 trainable ML models** and **2 deterministic/composite outputs** (no training required).

### Trainable ML Models (9)

| Model ID | Algorithm | Canonical Serving Endpoint |
|----------|-----------|---------------------------|
| `intent_prediction` | LogisticRegression | `/v1/predict/intent` |
| `bot_detection` | RandomForest | `/v1/predict/bot` |
| `session_scorer` | LogisticRegression | `/v1/predict/session-score` |
| `identity_resolution` | GradientBoosting | `/v1/predict/identity` |
| `journey_prediction` | Multi-class (LogisticRegression) | `/v1/predict/journey` |
| `churn_prediction` | GradientBoosting | `/v1/predict/churn` |
| `ltv_prediction` | GradientBoosting | `/v1/predict/ltv` |
| `anomaly_detection` | IsolationForest | `/v1/predict/anomaly` |
| `campaign_attribution` | Multi-touch (LogisticRegression) | `/v1/predict/attribution` |

All 9 models are trained via `ML Models/aether-ml/training/pipelines/train.py`. Artifacts
must be trained before serving. Stub models are available in `AETHER_ENV=local` only.

### Deterministic / Composite Outputs (2)

| Output | Type | Source |
|--------|------|--------|
| `bytecode_risk` | Rule-based (deterministic) | Smart contract bytecode analysis |
| `trust_score` | Composite (weighted ML outputs) | Aggregates above ML model scores |

These are always available regardless of artifact state. `trust_score` degrades gracefully
when ML models are unavailable.

See `docs/ML-TRAINING-GUIDE.md` for training instructions and `docs/MODEL-EXTRACTION-DEFENSE.md` for security controls.

## Quick Start

```bash
# Local development (no infrastructure required)
pip install -e ".[dev,security,backend,agent,ml]"
npm ci --ignore-scripts                # install TypeScript workspaces from package-lock.json
export AETHER_ENV=local
python -m ruff check .                 # Python static checks
make test                              # Python tests (root + ML testpaths)
npm run lint                           # TypeScript workspace static checks
npm run typecheck                      # TypeScript type checks
npm test                               # TypeScript/Vitest tests
npm run build                          # TypeScript package and frontend builds

# Full-stack Docker compose
docker compose up -d                   # postgres, redis, kafka, clickhouse, backend, ml-serving, kyber, prometheus
curl http://localhost:8000/v1/health   # backend
curl http://localhost:8080/health      # ml-serving
curl http://localhost:8081/health      # kyber operator console
# frontend/aether runs separately (dev-only): cd frontend/aether && npm run dev  # → http://localhost:5175

# Staging
cd deploy/legacy-staging
./bootstrap.sh
```

### Deployment Topology

```
  ┌─────────────────┐  ┌───────────────────────┐
  │   Kyber (8081)  │  │  Aether App (:5175)   │
  │  operator SPA   │  │  customer SPA (dev)   │
  └────────┬────────┘  └──────────┬────────────┘
           └──────────┬───────────┘
                      │
        ┌─────────────┴───────────┐
        │   Backend (8000)        │  ◄──── FastAPI · 55 routers · JWT auth · tenants
        └──┬──────────────────┬───┘
           │                  │
  ┌────────┴─────┐  ┌─────────┴────────┐
  │ ml-serving   │  │ Infrastructure    │
  │ (8080)       │  │ postgres · redis  │
  │ FastAPI infer│  │ kafka · clickhouse│
  └──────────────┘  │ prometheus (9090) │
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
    providers/       51 provider adapters (17 categories)
    auth/            API key validation + JWT + tenant context
    scoring/         Trust score + bytecode risk + extraction score
    rate_limit/      Burst RPM (P1-P4), monthly quota engine, feature gate, metrics
    plans/           Plan catalog (P1-P4) + 34-service registry + endpoint resolver
    billing/         Per-service overage calculator + threshold notifications
    privacy/         PII detection + retention + redaction

packages/                              Client SDKs + shared contracts + UI
  shared/          @aether/shared — canonical TypeScript contracts (events,
                   consent, wallet, identity, entities, commerce, agent,
                   capabilities, provenance, schema-version)
  ui/              @aether/ui — shared React component library (21 components,
                   design tokens, Tailwind preset, query layer, cn utility,
                   ThemeProvider); used by both Kyber and Aether
  web/             @aether/web — Web SDK (rollup → CJS/ESM/DTS)
  ios/             AetherSDK — Swift SPM package
  android/         io.aether:sdk-android — Kotlin
  react-native/    @aether/react-native — thin native bridge

apps/                                  First-party applications
  kyber/           @aether/kyber — operator control surface (React + Vite)
                   Mission · Live · Noesis · Entities · Command · Diagnostics
                   · Review · Lab; Playwright E2E + vitest unit/component/integ
  aether/          @aether/aether — customer-facing web app (React + Vite)
                   Auth (PKCE OIDC) · Home · port 5175 · imports @aether/ui

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
  kyber-e2e.yml    Path-scoped Playwright E2E for frontend/kyber + packages/shared
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
| [Agent Layer Production](docs/AGENT-LAYER-PRODUCTION.md) | Hosted agent control plane: envs, migration, operator workflows |
| [Connectors](docs/CONNECTORS.md) | Inbound connector framework with auth, env vars, health states |
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
