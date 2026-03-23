# Aether

Cross-platform Unified Intelligence Graph with Web3 wallet tracking, cross-device identity resolution, and on-chain reward automation.

## Architecture

Aether uses a **"Sense and Ship"** thin-client architecture. SDKs collect raw events, device fingerprints, and wallet interactions — the backend handles all processing, ML inference, identity resolution, traffic source classification, and analytics.

```
SDK (Web/iOS/Android/RN)          Backend (FastAPI + Neptune + TimescaleDB)
┌──────────────────────┐          ┌─────────────────────────────────┐
│ Raw events           │  POST    │ Ingestion → IP Enrichment       │
│ Device fingerprint   │  /v1/   │ Identity Resolution (10 signals)│
│ Wallet connections   │  batch   │ ML Scoring (intent, bot)        │
│ Session + identity   │ ──────> │ DeFi Tx Classification          │
│ Consent gates        │         │ Traffic Source Auto-Classification│
│ Feature flag cache   │  GET    │ Funnel Matching                 │
│                      │  /v1/   │ Heatmap Grid Generation         │
│                      │  config │ Reward Automation               │
└──────────────────────┘         └─────────────────────────────────┘
```

## SDKs

| Platform | Package | Size |
|---|---|---|
| **Web** | `@aether/web` | ~5,200 LOC |
| **iOS** | `AetherSDK` (Swift) | ~535 LOC |
| **Android** | `io.aether:sdk-android` (Kotlin) | ~493 LOC |
| **React Native** | `@aether/react-native` | ~497 LOC |

### Quick Start

**Web:**
```typescript
import aether from '@aether/web-sdk';

aether.init({ apiKey: 'your-key' });
aether.track('button_clicked', { buttonId: 'cta' });
aether.hydrateIdentity({
  userId: 'user-123',
  email: 'user@example.com',
});
```

**iOS:**
```swift
import AetherSDK
Aether.shared.initialize(config: AetherConfig(apiKey: "your-key"))
Aether.shared.track("button_tapped", properties: ["buttonId": AnyCodable("cta")])
```

**Android:**
```kotlin
import com.aether.sdk.Aether
Aether.initialize(application, AetherConfig(apiKey = "your-key"))
Aether.track("button_clicked", mapOf("buttonId" to "cta"))
```

**React Native:**
```tsx
import { AetherProvider } from '@aether/react-native-sdk';

<AetherProvider config={{ apiKey: 'your-key' }}>
  <App />
</AetherProvider>
```

## Key Features

- **Cross-device identity resolution** — Deterministic (email, phone, wallet, userId, OAuth) and probabilistic (fingerprint similarity, IP clustering, behavioral signals) matching into unified Identity Clusters
- **Device fingerprinting** — SHA-256 hash from platform-specific signals (Web: 17 browser signals via Web Crypto; iOS: CryptoKit; Android: MessageDigest)
- **Web3 wallet tracking** — 7 VM families: EVM, Solana, Bitcoin, Move/SUI, NEAR, TRON, Cosmos
- **DeFi transaction classification** — Protocol identification, swap/stake/lend/bridge categorization
- **On-chain reward automation** — Eligibility checks, pre-built claim payloads, oracle-verified proofs
- **GDPR/CCPA consent management** — Consent-gated data collection with banner UI
- **Feature flags** — Server-evaluated, locally cached
- **Automatic traffic source detection** — Server-side SourceClassifier with 40+ social, 17+ search, 14 email domain tables and 12 ad platform click IDs; priority chain: Click IDs → UTMs → Referrer → Direct
- **Web2 analytics** — Ecommerce, funnels, heatmaps, form analytics
- **ML inference** — 9 production models across edge and server tiers: intent prediction, bot detection, session scoring (edge, < 100ms); identity resolution (GNN), journey prediction (LSTM), churn prediction (XGBoost), LTV prediction (ensemble), anomaly detection (Isolation Forest + AutoEncoder), campaign attribution (Shapley values) (server, SageMaker/ECS)
- **BYOK provider gateway** — Multi-provider abstraction with Bring Your Own Key support, automatic failover (tenant BYOK → system default → fallback), per-tenant usage metering, and circuit breaker integration across 4 provider categories (blockchain RPC, block explorer, social API, analytics data)
- **Diagnostics & circuit breakers** — Centralized error registry with SHA-256 fingerprinting, per-operation circuit breakers, and real-time health monitoring
- **Model extraction defense** — 6-component security layer protecting ML inference against extraction and distillation attacks: dual-axis rate limiting, query pattern anomaly detection, output perturbation, probabilistic watermarking, canary trap inputs, and adaptive risk scoring. Gated behind `ENABLE_EXTRACTION_DEFENSE` feature flag

## Unified On-Chain Intelligence Graph

8-layer architecture for tracking behavioral and financial relationships across human-to-human, human-to-agent, agent-to-human, and agent-to-agent interactions. Built on top of the existing Neptune identity graph.

### Relationship Layers

| Layer | Description |
|---|---|
| **H2H** (Human-to-Human) | Referral chains, shared-wallet co-signers, social graph edges derived from on-chain transfers |
| **H2A** (Human-to-Agent) | User interactions with autonomous agents — delegation events, tool invocations, approval flows |
| **A2H** (Agent-to-Human) | Agent-initiated interactions back to humans — notifications, recommendations, result deliveries, escalations |
| **A2A** (Agent-to-Agent) | Inter-agent message passing, x402 payment channels, orchestration dependencies |

### By the Numbers

| Dimension | Count | Notes |
|---|---|---|
| Layers | 8 | L0 On-Chain Actions through L7 Compliance |
| ML Models | 9 | Intent, bot, session (edge); identity resolution, journey, churn, LTV, anomaly, attribution (server) |
| Streams | 5 | Wallet tx, SDK events, agent logs, x402 receipts, oracle callbacks |
| Node Types | 6 | Agent, Service, Contract, Protocol, Payment, ActionRecord (new; layered onto existing Identity Graph) |
| Edge Types | 19 | LAUNCHED_BY, DELEGATES, INTERACTS_WITH, NOTIFIES, RECOMMENDS, DELIVERS_TO, ESCALATES_TO, HIRED, PAYS, CONSUMES, EARNS_FROM, DEPLOYED, CALLED, COMPOSED_WITH, UPGRADED, GOVERNED_BY, DEPENDS_ON, PERFORMED_ACTION, USES_PROTOCOL |
| Stores | 5 | Neptune*, TimescaleDB*, Redis*, S3, Kafka* (*in-memory stubs in dev; real integrations required for production) |

### New Services (Feature-Flagged)

All intelligence graph layers are **disabled by default**. Progressive activation via environment variables (`AETHER_GRAPH_L0=true`, etc.).

- **On-Chain Actions (L0)** — Raw transaction indexing and event normalization (`AETHER_GRAPH_L0`)
- **Commerce (L3a)** — Merchant-side analytics, cart-to-chain attribution (`AETHER_GRAPH_L3A`)
- **x402 Interceptor (L3b)** — Agent-to-agent micropayment capture and settlement tracking (`AETHER_GRAPH_L3B`)

### Scoring

- **Trust Score** — Composite metric derived from existing ML models (intent, bot, fraud, anomaly) applied to graph node context
- **Bytecode Risk** — Rule-based scorer for smart contract interactions; no ML dependency

### GDPR Compliance

2 new consent purposes added: `agent_interaction` and `commerce_tracking`. DSR (Data Subject Request) cascade extended to cover all new vertex types (Agent, Contract, Merchant).

## Project Structure

```
packages/
├── web/              Web SDK (TypeScript)
├── ios/              iOS SDK (Swift)
├── android/          Android SDK (Kotlin)
└── react-native/     React Native SDK (TypeScript)

Backend Architecture/
└── aether-backend/
    ├── services/
    │   ├── ingestion/     Event ingestion + IP enrichment
    │   ├── identity/      Identity management
    │   ├── resolution/    Cross-device identity resolution
    │   ├── analytics/     Session scoring + anomaly detection
    │   ├── fraud/         Fraud detection
    │   ├── attribution/   Campaign attribution
    │   ├── ml_serving/    ML model serving
    │   ├── traffic/
    │   │   ├── routes.py      Automatic traffic source tracking
    │   │   └── classifier.py  SourceClassifier (domain tables, click IDs)
    │   └── diagnostics/   Error tracking & circuit breakers
    ├── shared/
    │   ├── graph/         Neptune graph client
    │   ├── events/        Event bus (Kafka/SNS)
    │   ├── cache/         Redis cache
    │   ├── diagnostics/   Error registry & circuit breakers
    │   └── common/        Shared utilities
    └── main.py            FastAPI application

docs/
├── ARCHITECTURE.md       System architecture overview
├── BACKEND-API.md        API endpoint specification
├── IDENTITY-RESOLUTION.md  Identity resolution deep dive
├── SDK-WEB.md            Web SDK integration guide
├── SDK-IOS.md            iOS SDK integration guide
├── SDK-ANDROID.md        Android SDK integration guide
├── SDK-REACT-NATIVE.md   React Native SDK integration guide
├── INTELLIGENCE-GRAPH.md Unified On-Chain Intelligence Graph spec
├── AGENT-CONTROLLER.md   Agent Layer orchestrator documentation
├── MODEL-EXTRACTION-DEFENSE.md  ML extraction defense architecture
├── MIGRATION-v7.md       v6 → v7 migration guide
└── CHANGELOG.md          Version history
```

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | System design, module architecture, event flow |
| [Backend API](docs/BACKEND-API.md) | All API endpoints with request/response examples |
| [Identity Resolution](docs/IDENTITY-RESOLUTION.md) | Cross-device matching algorithms and graph schema |
| [Web SDK](docs/SDK-WEB.md) | Web integration guide |
| [iOS SDK](docs/SDK-IOS.md) | iOS integration guide |
| [Android SDK](docs/SDK-ANDROID.md) | Android integration guide |
| [React Native SDK](docs/SDK-REACT-NATIVE.md) | React Native integration guide |
| [Intelligence Graph](docs/INTELLIGENCE-GRAPH.md) | On-chain intelligence graph architecture |
| [Agent Controller](docs/AGENT-CONTROLLER.md) | Agent Layer orchestrator, task queue, feedback loop |
| [Model Extraction Defense](docs/MODEL-EXTRACTION-DEFENSE.md) | ML model extraction defense layer architecture |
| [Migration Guide](docs/MIGRATION-v7.md) | Breaking changes from v6 to v7 |
| [Changelog](docs/CHANGELOG.md) | Version history |

## License

Proprietary. All rights reserved.
