---
title: Aether Architecture Guide
slug: architecture/system-map
section: architecture
visibility: P
audience: [architect, dev-senior, security]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/main.py
  - services/api/middleware/middleware.py
  - services/api/config/settings.py
  - services/api/ingestion/ingestion/replay.py
  - services/api/ingestion/ingestion/replay_routes.py
  - services/api/shared/events/events.py
  - packages/shared/
  - services/api/actions/delegation/engine.py
  - services/api/actions/agent/agent360_provider.py
  - services/api/actions/agent/execution360_provider.py
  - services/api/actions/agent/user_agents.py
  - services/api/identity/account360_provider.py
  - services/api/intelligence/workflow/workflow360_provider.py
  - services/api/intelligence/fraud_networks/risk360_projection.py
  - services/api/intelligence/risk360/provider.py
  - services/api/journeys/communication360/provider.py
  - services/api/journeys/communication360/participant_writer.py
  - services/api/journeys/support360/
  - services/api/repositories/repos.py
  - services/api/shared/intelligence_projections/frame_runtime.py
  - services/api/value/economic/economic360_provider.py
  - services/api/value/economic/journey_operation_evidence.py
  - services/api/value/commerce/order_payment_reconciliation.py
  - services/api/value/commerce/commerce360_provider.py
  - services/api/value/commerce/commerce_intents.py
  - services/api/value/commerce/routes.py
  - services/api/alembic/versions/20261023_commerce_intent_authority.py
  - services/api/alembic/versions/20261023_support_callback_authority.py
  - services/api/connectors/integrations/providers/payment_rails/service.py
  - services/api/connectors/integrations/providers/payment_rails/stripe_onramp.py
  - services/api/value/economic/ai_aggregation.py
  - services/api/actions/agent/deployment_routes.py
  - services/api/actions/agent_marketplace/catalog.py
  - services/api/actions/agent_marketplace/authority.py
  - services/api/alembic/versions/20261011_agent_delegated_to_namespace.py
  - services/api/ingestion/silver/projectors/agent_execution_projector.py
  - services/api/actions/agent_marketplace/identity_binding.py
  - services/api/actions/agent_marketplace/graph_state_check.py
  - services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py
  - services/api/actions/agent_marketplace/lineage.py
  - services/api/actions/agent_marketplace/projection.py
  - services/api/workers/runtime/specs.py
  - scripts/generate_feature_surface_manifest.py
canonical_owner: platform@aether
estimated_read_minutes: 20
toc_depth: 3
reviewed_source_commits:
  - commit: "5bfb9394"
    reason: "Reviewed the shared action-runtime contract hardening: approval level/scope remain enforced while tenant and decision identity stay outer-context bound, and execution-step targets must match the canonical scoped target set."
  - commit: "181af52f4"
    reason: "Reviewed the shared SDK batch wire vector and cross-platform conformance seam. It documents the existing canonical intake path and adds no client-owned tenant, identity, rights, or graph authority."
  - commit: "b9dc38da7"
    reason: "Reviewed the generated shared feature-surface manifest update: Agent 360 remains tenant-scoped and explicitly exempt from exact Kyber mirror parity until an owner defines that contract."
  - commit: "40af67902"
    reason: "Reviewed the optional server-returned consent, usage, and audit references for accepted batch observations. The contracts preserve the existing intake and authority boundaries."
  - commit: "482948261"
    reason: "Reviewed 482948261 (Codex findings on fleet hypotheses, bounded lineage reads and journey handoff): repositories/repos.py only gains the additive BaseRepository.insert_if_absent and replace_if_matches conditional-write primitives, deployment_routes.py reads lineage through a shared bounded reader that reports truncation, middleware.py lets site-bound publishable keys reach the two journey-handoff POSTs, and route_registry.yaml classifies the /sdk/journey-handoff prefix; nothing this doc describes changed behavior, so no body change was required."
  - commit: "78eb672ff"
    reason: "Reviewed 78eb672ff (Codex findings on semantic-intelligence): middleware.py now passes the request method to the route-policy classifier so method-specific Kyber declarations are enforced; nothing this doc describes changed, so no body change was required."
source_hashes:
  "packages/shared/": "sha256:77455f3adb9b25f0d97c852404f6393394863c719c502f28472a8e1b71bb248d"
  "scripts/generate_feature_surface_manifest.py": "sha256:cd1c01ef58e827b0869699346952840b25702b00f765f5c16f4c7178610fd210"
  "services/api/actions/agent/agent360_provider.py": "sha256:084b3ba0a7680dee48b146e3111c22c4854b736e86742b4484db9c0927866577"
  "services/api/actions/agent/deployment_routes.py": "sha256:46ace5ea27e1c0a95bb62b7d63cd9c53f383f0ae759e30c795914f41e5e2a8b4"
  "services/api/actions/agent/execution360_provider.py": "sha256:d166db55e656eb508e84ec58945eee5fdae4da5fe487f27f87aa7e4b131b9810"
  "services/api/actions/agent/user_agents.py": "sha256:6a8dc66f37f293699cd261592f6de4655c94b2eea2140cf3c0c85c4df05aaa2a"
  "services/api/actions/agent_marketplace/authority.py": "sha256:b136984919ab302e7140815f5984f4cfad11494c3a591853af33d4c741a88b29"
  "services/api/actions/agent_marketplace/catalog.py": "sha256:b80db998c39a966ff19a25a64487b005b049bba96f6ca51cba18c15554cdce82"
  "services/api/actions/agent_marketplace/graph_state_check.py": "sha256:595617063afe604a7a5b1c421fa73916141a37b374a008606bb6dab460cd0983"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/actions/agent_marketplace/lineage.py": "sha256:bfe247f42c3360f30b3f4fa92b1f39e95f654be0862303d6f74b9fb2363e6566"
  "services/api/actions/agent_marketplace/projection.py": "sha256:92a5f5e457beebde9d161bf26f40ccb39fc5b76bc8ae4abfccc3e572b3c29de0"
  "services/api/actions/delegation/engine.py": "sha256:5b4face159fb5bd3f9d3e8be5a793d1a8f2f363316cf092b6e5a1593ecc59798"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/alembic/versions/20261023_commerce_intent_authority.py": "sha256:81dbf80e8646034fe5f2b51e616ee71c4c758b6a4380b3ee44ff5ce114156e38"
  "services/api/alembic/versions/20261023_support_callback_authority.py": "sha256:33278fd0ba6103d8a3f37c87db66c8209d953555669d72647047674425a1bede"
  "services/api/config/settings.py": "sha256:fe581665da73af478c3da53600fb0fdd4994d801f408e56f6d2796fbd00748bf"
  "services/api/connectors/integrations/providers/payment_rails/service.py": "sha256:8e681a79980dae410a82b15215fbc26fd73f55bdeefb5ded42b57675694ffa80"
  "services/api/connectors/integrations/providers/payment_rails/stripe_onramp.py": "sha256:740b01479ca0ea5104850140eb269cfef35b9c60b4b848d0b0bd0ad7eecb3905"
  "services/api/identity/account360_provider.py": "sha256:dd2b32bc4eb3fec20094ef053dfe99de88e39ec43388dae73c41f9d4cdcab838"
  "services/api/ingestion/ingestion/replay.py": "sha256:65f898480787b71d14c8f687351844fdf5585cd67664ff5c32699328594b24ce"
  "services/api/ingestion/ingestion/replay_routes.py": "sha256:5ce3f7c1d9f09cbb51e39ae223f9d502a1854f48b12a144472dc5b78c1ebc752"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:1db7a6ff778ed3ca22ebae87717636c37f6b821b1e37ddc4d85161a5bb3bb4bf"
  "services/api/intelligence/fraud_networks/risk360_projection.py": "sha256:4ad7ac91c78b7f66f66e9abd986a723453a721e4868584fa1e349723d6cd306c"
  "services/api/intelligence/risk360/provider.py": "sha256:4b133b60ba7a18037cd026481d712db6c55505b50806d8c2343d775e3c98daea"
  "services/api/intelligence/workflow/workflow360_provider.py": "sha256:fc18afe40ebfd2cc7a009d2b0f90fadbba4b56a5568a405ef78715b7e7b06f53"
  "services/api/journeys/communication360/participant_writer.py": "sha256:3569154a47bf54feb898d7a19e043aba100dc06998411afc1983017afb480cd3"
  "services/api/journeys/communication360/provider.py": "sha256:bedc278463eae8cb3d5c40078a659324dd50b8709f76887b95ad4e131c22b44d"
  "services/api/journeys/support360/": "sha256:566b316cb9d4381caf77c627e22fad1c6ea3a910d156ef48fbd7a674c48830b2"
  "services/api/main.py": "sha256:fca84921a91cae1332efdd3da2218d211d3a960dd232470b9ea808536a3aa9e2"
  "services/api/middleware/middleware.py": "sha256:f32fb04affbf87df4bbfbb6c1294ae9405765ccd22d5cc1bcaf1b60bfaf4c98a"
  "services/api/repositories/repos.py": "sha256:fcaaad1267595bd0f2a936e0b39e402b9dacc909da5a4b74066023d99035e5c2"
  "services/api/shared/events/events.py": "sha256:92a17e02a32de87e1744f75bf5c665d0482400efe0b734602abb37eda4dbdb1b"
  "services/api/shared/intelligence_projections/frame_runtime.py": "sha256:e1d39238f595d91a69347c76418cb2e4d79e860c8e254cebb5720343be4928d4"
  "services/api/value/commerce/commerce360_provider.py": "sha256:635f93631d2946d681c9f3d98c8f6b2bb929fc9a200c42b70afeeacdd49b085c"
  "services/api/value/commerce/commerce_intents.py": "sha256:c452c03579bc73e3df33a817ee97edea530d5954450c8d3a25635904120ba1d0"
  "services/api/value/commerce/order_payment_reconciliation.py": "sha256:f2e4d9a401fe5458202ec6af80634e8d2e06d894e31bdbe31b25eba99bc83942"
  "services/api/value/commerce/routes.py": "sha256:9b68c0d975d7b81b530ff8eb91e95ee6c37e10034498dbf248f1889f026c5897"
  "services/api/value/economic/ai_aggregation.py": "sha256:1c9a65985225dc3c25bb5f628610390cde15271dc320c0af6e0a2bbedd98c82f"
  "services/api/value/economic/economic360_provider.py": "sha256:b44928e1f1bcd6ecec0cbb1be7c0613809887387fd242657bcf75ee8bc8c9342"
  "services/api/value/economic/journey_operation_evidence.py": "sha256:075dd15490f0ead55d8eaaae0c88580d7ea496b1173da190e28c3459ff74cb29"
  "services/api/workers/runtime/specs.py": "sha256:b86659249b2f805b3ba81631c57e71ca57be089de07278fedccbe25b576df64b"
---
# Aether vNext — Architecture Guide

## Overview

Aether is a **hybrid Python/FastAPI + Node/TypeScript** platform with four operational planes:

1. **SDK Plane** — Thin-client SDKs (Web, iOS, Android, React Native) collect raw events, fingerprints, wallet interactions, and session data. SDKs ship raw data to the backend.

2. **Backend Plane** — Python/FastAPI with 60+ service routers handling ingestion, identity, analytics, ML inference, graph, rewards, lake management, profile intelligence, population omniview, expectation engine, behavioral continuity, RWA intelligence, Web3 coverage, cross-domain TradFi/Web2 intelligence, extraction defense mesh, privacy/policy control plane, **notification intelligence** (`/v1/notifications/intelligence/*` — event-driven multi-channel operator alerts + end-user Slack/Discord/Telegram/Webhook delivery; mobile push (APNs/FCM) carries only a redacted projection — amounts/PII are `[redacted]`, never raw payload), plus the customer-facing productization surface: **registration** (`POST /v1/tenants`), **auth** (`/v1/auth/*` — email+password+OTP signup, Auth0 SSO callback, API-key recovery), **caller profile** (`/v1/me/*` — paginated self-service API keys), **billing** (`/v1/billing/*` — Stripe Checkout + Billing Portal + invoices), **Stripe webhook** (`/v1/admin/billing/stripe/webhook`, signature-verified), **SDK utilities** (`/sdk/identity/resolve` — cross-device identity), and a monthly overage cron task + SLA expiry worker + Dune Analytics scheduled polling worker running in the app lifespan. Continuity and mobile surfaces complete the plane: the **continuation plane** (`/v1/continuations` — durable, CAS-guarded context-handoff tokens, never a whole graph; the operator twin `/v1/kyber/continuations` exposes the same shapes to Kyber workforce sessions via `require_kyber_access`), the **client-sync feed** (`/v1/client-sync` — gapless per-scope catch-up cursor; operators read the same feed scoped to their own identity through `/v1/kyber/client-sync`), and the **mobile gateway** (`/v1/mobile/*` — installation + push-subscription registration, per-install configuration with distribution profiles, and bounded redacted projections over owning services). Infrastructure: PostgreSQL (asyncpg), Redis (redis.asyncio), Neptune (gremlinpython), a typed event bus (Kafka via aiokafka, or AWS SNS/SQS when `EVENT_BROKER=sns_sqs`), S3, Prometheus. In `AETHER_ENV=local` with no broker reachable, the event bus falls back to an in-memory list and the `main.py` lifespan runs `EventProducer.pump_local` to drain published events into the in-process consumer — so the single-process local stack delivers Bronze→Silver projections without a broker (a broker-connected producer is never double-delivered).

3. **Data Lake Plane** — Medallion architecture (Bronze/Silver/Gold) for raw data persistence, validation, feature materialization, and intelligence output generation. Lake data feeds ML training, graph mutations, and intelligence APIs.

4. **Frontend Plane** — Two React/Vite SPAs backed by the same `@aether/ui` shared component library (`packages/ui`). **Kyber** (`apps/kyber-web`, port 5174) is the internal operator control surface — investigation, live monitoring, entity management, and approvals. **Aether** (`apps/aether-web`, port 5175) is the customer-facing web app — account management and commerce. Both apps use PKCE OIDC auth and communicate exclusively with the backend REST API. Two **Expo mobile apps** extend the plane — **Aether Mobile** (`apps/aether-mobile`, customer plane) and **Kyber Mobile** (`apps/kyber-mobile`, operator plane, distinct bundle/audience from Aether Mobile) — built on the shared `@aether/mobile-core` (typed SDK: auth/continuation/sync/push over SecureStore PKCE) and `@aether/mobile-ui` (dark theme + typed navigation) packages. The mobile apps are read-only, consuming the mobile gateway's bounded redacted projections; their wire contracts (distribution profiles, install/app-version registration) live in `packages/shared/mobile-config.ts` and `packages/shared/installation.ts`.

### Repository topology and runtime ownership

The implementation tree follows the same boundaries as the runtime architecture.
`services/api/` is the deployed Python/FastAPI application and owns
ingestion, lake coordination, graph access, intelligence routes, and backend
repositories. `services/ml/` owns model training and serving; `services/agents/`
owns internal broker-coupled workers and staged graph-mutation workflows; and
`services/compliance/` owns the GDPR/SOC 2 control implementation. AWS and
Terraform delivery live under `infra/aws/`, while EVM and multi-chain contract
code lives under `packages/contracts/smart-contracts/`. Shared contracts remain in
`packages/shared/contracts/`, and product clients remain under `apps/` and
`frontend/`.

The old space-containing trees are not alternate implementations. The two
un-deployed TypeScript duplicates are retained under
`docs/archive/legacy-architecture/data-ingestion-layer/` and
`docs/archive/legacy-architecture/data-lake-architecture/` for historical
reference only. Orphaned backend and deployment material is similarly grouped
under `docs/archive/legacy-architecture/`. New code, CI paths, impact-graph
entries, and operational instructions must use the canonical active paths in
[`repo-migration.md`](../reference/source-of-truth/repo-migration.md).

### Data Flow

```
Providers (24)  →  /v1/lake/ingest  →  Bronze (raw, immutable)
SDKs            →  /v1/batch        →       ↓
                                       Silver (validated, normalized)
                                            ↓
                                       Gold (features, metrics)
                                            ↓
                              ┌──── Redis (online features)
                              ├──── Neptune (graph edges)
                              ├──── ML Training → Model Registry
                              └──── Intelligence API (risk, analytics, clusters, alerts)
```

SDK, CLI, and MCP observation requests use the canonical `POST /v1/batch`
intake path. The Access Kit CLI, MCP adapters, and Node client use the
existing tenant-scoped APIs for named, bounded reads. The CLI and MCP adapters
use the same batch endpoint for site-bound observations; none of these
surfaces creates another graph writer, identity resolver, or action authority.
The Access Kit can also create and read back a bounded continuation through
the existing principal-scoped continuation API when that feature is enabled;
this records context for later resolution, not a graph write or external action.
Batch responses can return the real consent, usage, and audit references that
their owning authorities persisted. SDK batch payloads share a minimum
cross-platform wire vector, while the optional Envelope-B field remains behind
the server's adoption flags.
When Envelope-B is built, the server stamps the source block: relationship
`first_party_application`, the platform from the authenticated API key record,
and the site or tenant namespace as the source instance. Client-supplied source
claims are ignored. The relationship is descriptive provenance only; it never
authorizes use. See `docs/architecture/target/source-authority.md`.

Authenticated Access Kit calls through the CLI, local MCP, hosted MCP, and Node
client are attributed by an allowlisted surface label and recorded by the API middleware
in the existing audit ledger plus a non-billable `access_interaction` usage
dimension. Durable audit and usage event IDs are returned as response headers
and preserved in the adapter interaction envelope. Subscribed tenant webhooks
receive minimized interaction events from the notification outbox; they do not
become another graph, identity, or access authority.

The SDK also collects raw user interactions, device fingerprints, wallet events, and session data — then ships everything to the backend for processing, enrichment, identity resolution, and analysis.

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│   Client SDK                │  HTTP  │   Aether Backend                 │
│   (Sense & Ship)            │ ────>  │   (Process, Resolve, Enrich)     │
│                             │        │                                  │
│  - DOM / UI event listeners │  POST  │  - IP enrichment (MaxMind)       │
│  - Device fingerprinting    │  /v1/  │  - Identity resolution           │
│  - Wallet detection (7 VMs) │ batch  │    (deterministic + probabilistic│
│  - Raw event batching       │        │     cross-device matching)       │
│  - Session & identity mgmt  │  GET   │  - ML inference (9 models)       │
│  - Consent gates (GDPR)     │  /v1/  │  - DeFi tx classification        │
│  - Feature flag cache       │ config │  - Traffic source auto-classify  │
│  - Fingerprint generation   │        │  - Funnel matching & analysis    │
│                             │        │  - Heatmap grid generation       │
│                             │        │  - Whale detection               │
└─────────────────────────────┘        └──────────────────────────────────┘
```

## Design Principles

1. **Collect, don't compute** — The SDK captures raw data (clicks, scrolls, wallet connections, transactions, fingerprints) and ships it unprocessed. All classification, scoring, and analysis happens server-side.

2. **Minimal context, maximum signal** — Mobile SDKs send a lean context (`os`/`device` identity, `locale`, `timezone`, temporal provenance, per-session `sequence` counter, campaign/acquisition evidence, consent booleans). The backend derives remaining device capabilities from HTTP headers. Web SDK additionally stamps the canonical envelope fields (`surface`, `schemaVersion`) and the device fingerprint hash (consent-gated).

3. **Config from server** — SDK remote config (signed manifests + rollouts) is served from `GET /v1/config/sdk/manifest` and cached locally; native health agents refresh it every 5 minutes. No client-side evaluation logic. (The web feature-flag module still targets the legacy `/v1/config` path.)

4. **Offline-first** — Events are queued in memory and batch-flushed. Network failures result in retry with exponential backoff, not data loss.

5. **Consent-gated** — All data collection respects GDPR/CCPA consent state. The SDK gates collection categories locally before any data leaves the device. Device fingerprinting is skipped when GDPR mode is active and analytics consent is not granted.

6. **Privacy by design** — All PII (email, phone, IP) is SHA-256 hashed before storage. Device fingerprints are composite hashes — raw signals never leave the client. Raw IP addresses are never persisted.

## SDK Architecture

### Module Architecture (Web SDK)

```
AetherSDK (index.ts) — v0.1.0-alpha.0
│
├── Core (always loaded)
│   ├── EventQueue .............. Batch + offline queue (POST /v1/batch)
│   ├── SessionManager ......... Session lifecycle + heartbeat
│   ├── IdentityManager ........ Multi-wallet identity + traits
│   ├── ConsentModule .......... GDPR/CCPA consent gates
│   └── DeviceFingerprintCollector  SHA-256 from 17 browser signals
│
├── Web2 Analytics (thin event emitters)
│   ├── AutoDiscovery .......... Click listener (raw {selector, x, y})
│   ├── Ecommerce .............. 5 methods: view, cart, checkout, purchase
│   ├── FeatureFlags ........... Cache-only (fetch from /v1/config)
│   ├── FormAnalytics .......... focus/blur/change events
│   ├── Funnels ................ Event tagger from server config
│   ├── Heatmaps ............... Raw coordinate emitter
│   └── Performance ............ Web Vitals / Navigation Timing / Long Tasks
│                                 raw metric emitter (default on, sampled)
│
├── Web3 (wallet detection + raw tx shipping)
│   ├── 16 VM Providers ........ EVM, SVM, Bitcoin, Move/SUI, Aptos, NEAR,
│   │                             TRON, Cosmos, TON, Starknet, Cardano,
│   │                             Algorand, Hedera, Stellar, Substrate, ICP
│   └── VM Trackers ............ Raw transaction data emitters
│
├── Context
│   ├── SemanticContext ........ Tier 1 only (device, viewport, URL)
│   └── TrafficSource .......... Raw UTM/referrer/click ID/referrerDomain shipper
│                                 + sessionStorage persistence for SPA navigation
│
└── Rewards (thin API client)
    └── RewardClient ........... eligibility + claim via backend API
```

### Device Fingerprinting

All SDKs generate a deterministic device fingerprint (SHA-256 hash) that is included in every event's `context.fingerprint.id`. Only the composite hash leaves the device — raw signals are never transmitted.

| Platform | Signals | Method |
|---|---|---|
| **Web** | Canvas rendering, WebGL renderer/vendor, audio context, font detection (24 fonts), screen resolution, color depth, timezone, language, platform, hardware concurrency, device memory, touch support, cookie support, DNT, pixel ratio | SHA-256 via Web Crypto API, cached in localStorage (7-day TTL) |
| **iOS** | `identifierForVendor`, device model, system version, screen dimensions, scale, locale, timezone, processor count, physical memory | SHA-256 via CryptoKit |
| **Android** | `ANDROID_ID`, `Build.MODEL`, `Build.MANUFACTURER`, OS version, display metrics (width, height, density), locale, timezone, available processors | SHA-256 via `MessageDigest` |
| **React Native** | Delegates to native module: `NativeModules.AetherNative.getFingerprint()` | Native implementation (iOS/Android) |

## Traffic Source Classification

SDKs collect raw traffic signals and ship them to the backend, where the `SourceClassifier` (`services/api/journeys/traffic/classifier.py`) classifies every session into source/medium/channel automatically.

```
SDK detect()                       Backend SourceClassifier
┌─────────────────────┐            ┌──────────────────────────────────────┐
│ referrer URL        │   POST     │ Priority chain:                      │
│ referrerDomain      │   /v1/     │  1. Click IDs → Paid (confidence 1.0)│
│ UTM params (5)      │   track/   │  2. UTM params → Custom (0.95)       │
│ Click IDs (12)      │   traffic- │  3. Referrer → Organic/Social (0.9)  │
│ Landing page        │   source   │  4. No signals → Direct (0.5)        │
└─────────────────────┘  ────────> └──────────────────────────────────────┘
                                            │
                                   ClassifiedSource{source, medium, channel, confidence}
```

**Domain lookup tables (O(1) dict lookups — no regex):**

| Table | Coverage | Examples |
|---|---|---|
| Social | 40+ domains | facebook.com, t.co, linkedin.com, reddit.com, tiktok.com |
| Search | 17+ domains | google.*, bing.com, duckduckgo.com, baidu.com, yandex.ru |
| Email | 14 domains | mail.google.com, outlook.live.com, protonmail.com |
| Click IDs | 12 mappings | gclid→google/cpc, fbclid→facebook/cpc, epik→pinterest/cpc |

**Channel categories:** Paid Search, Paid Social, Organic Search, Organic Social, Email, Display, Affiliate, Referral, Direct, Other

**Key design decisions:**
- Email domains checked before search to prevent `mail.google.com` → Search misclassification
- `sessionStorage` persistence on web ensures SPA navigations retain original traffic source
- iOS/Android SDKs include campaign context (source, medium, campaign, content, term, clickIds, referrerDomain) in every event via `buildContext()`

## Identity Resolution

The backend runs a cross-device identity resolution engine that merges user profiles into **Identity Clusters** using deterministic and probabilistic signals.

### Identity Graph Schema

```
                    ┌──────────────────┐
                    │  IdentityCluster │
                    │  (single source  │
                    │   of truth)      │
                    └────────┬─────────┘
                 MEMBER_OF_CLUSTER
          ┌──────────┼──────────┐
          ▼          ▼          ▼
     ┌────────┐ ┌────────┐ ┌────────┐
     │ User A │ │ User B │ │ User C │
     │(phone) │ │(laptop)│ │(tablet)│
     └───┬────┘ └───┬────┘ └───┬────┘
         │          │          │
    ┌────┴────┬─────┴────┬─────┴────┐
    ▼         ▼          ▼          ▼
┌────────┐┌────────┐┌────────┐┌────────┐
│  Email ││ Device ││   IP   ││ Wallet │
│(hashed)││ Finger-││Address ││(on-    │
│        ││ print  ││(hashed)││ chain) │
└────────┘└────────┘└────────┘└────────┘
```

### Vertex Types

| Vertex | Key Properties |
|---|---|
| `User` | `anonymous_id`, `user_id`, `traits`, `tenant_id` |
| `DeviceFingerprint` | `fingerprint_id` (SHA-256), `canvas_hash`, `webgl_renderer`, `audio_hash`, `screen_resolution`, `timezone`, `language`, `platform` |
| `IPAddress` | `ip_hash` (SHA-256), `ip_range`, `asn`, `isp`, `is_vpn`, `is_proxy`, `is_tor` |
| `Location` | `country_code`, `region`, `city`, `latitude`, `longitude`, `timezone` |
| `Email` | `email_hash` (SHA-256), `domain`, `is_disposable` |
| `Phone` | `phone_hash` (SHA-256 of E.164), `country_code` |
| `Wallet` | `address`, `vm`, `chain_ids[]`, `ens`, `classification` |
| `IdentityCluster` | `cluster_id`, `canonical_user_id`, `confidence`, `member_count`, `resolution_status` |

### Edge Types

| Edge | Direction | Purpose |
|---|---|---|
| `HAS_FINGERPRINT` | User → DeviceFingerprint | Device ownership |
| `SEEN_FROM_IP` | User → IPAddress | Network observation |
| `LOCATED_IN` | User → Location | Geographic association |
| `HAS_EMAIL` | User → Email | Email ownership (deterministic) |
| `HAS_PHONE` | User → Phone | Phone ownership (deterministic) |
| `OWNS_WALLET` | User → Wallet | Wallet ownership (deterministic) |
| `MEMBER_OF_CLUSTER` | User → IdentityCluster | Cluster membership |
| `SIMILAR_TO` | User → User | Probabilistic similarity link |
| `IP_MAPS_TO` | IPAddress → Location | Geolocation mapping |
| `RESOLVED_AS` | User → User | Identity merge (audit trail) |

### Legacy resolution signals

The signal weights below describe the unregistered legacy resolution engine,
not the active tenant-facing identity resolver. The legacy cluster, approval,
and batch routes return HTTP 503 until their graph access is tenant safe.

**Deterministic (confidence = 1.0, auto-merge):**
- `UserIdSignal` — Same `userId` across profiles
- `EmailSignal` — Same normalized email hash (Gmail dot/plus normalization)
- `PhoneSignal` — Same E.164 phone hash
- `WalletAddressSignal` — Same wallet address + VM type
- `OAuthSignal` — Same OAuth provider + subject

**Probabilistic (weighted composite scoring):**

| Signal | Weight | Scoring |
|---|---|---|
| FingerprintSimilarity | 0.35 | Component-level: canvas (30%), WebGL (25%), audio (15%), screen (5%), timezone+lang (10%), platform (5%), hardware (5%), fonts (5%) |
| NetworkGraphProximity | 0.20 | Jaccard similarity on shared graph neighbors |
| IPCluster | 0.15 | Same IP = 0.8, same /24 = 0.4, same ASN = 0.15 (VPN discounted) |
| BehavioralSimilarity | 0.15 | Cosine similarity on session timing, page frequency, event mix |
| LocationProximity | 0.15 | Same city = 0.6, same region = 0.3, same country = 0.1 |

### Resolution Flow

```text
SDK event → durable validated-event consumer → source identity registry
                                             → canonical identity resolver
Tenant identity API → IdentityResolver → identity decision/review
                                   → IdentityGraphWriter → GraphMutationGateway
```

The old `ResolutionEventConsumer` and hourly `ResolutionBatchJob` are not
registered in the production runtime. The legacy graph repository exposed
unscoped reads and direct writes; its direct mutation methods have been
removed, and the remaining mounted legacy graph routes fail closed. Canonical
identity decisions belong to the tenant-scoped resolver and
`GraphMutationGateway`. The retired graph routes stay unavailable until a
replacement compatibility path is implemented and proves tenant scope.

## Backend API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/batch` | POST | Canonical batched raw events (ALL SDKs — web, iOS, Android, RN) |
| `/v1/ingest/events[/batch]` | POST | Deprecated server-to-server connector aliases — converged (WS-B2) onto the canonical `/v1/batch` spine (same validation/consent/scrub/Bronze/idempotency/publish path + `write` auth); retire with HTTP 410 when `AETHER_KILL_DEPRECATED_INGEST_ALIASES=true` |
| `/v1/kyber/ingest/replay/*` | POST/GET | Kyber-operator Bronze-ingestion replay (WS-B4) — re-deliver a tenant's durable Bronze SDK events with original-time preservation; timezone-qualified occurrence bounds compare in UTC and exclude rows without a valid original time; `POST /v1/kyber/ingest/replay/events` dry-runs by default (zero publishes); live publishing requires `AETHER_INGESTION_REPLAY_ENABLED` and is available only with explicit `AETHER_ENV=local`, in-memory storage, and an in-memory event bus (otherwise HTTP 403 when disabled or 503 when the runtime is not local); a local publish run may end as `partial` on row errors and its process-local journal prevents the same run ID from silently replaying rows on retry; `GET /v1/kyber/ingest/replay/status` reports the feature-flag state |
| `/v1/kyber/ingest/observability*` | GET | Kyber-operator ingestion-funnel telemetry + Observation Inspector (WS-E; flag-gated `AETHER_INGESTION_OBSERVABILITY_ENABLED`, default OFF — while OFF the routes stay mounted but report `enabled: false` / empty, never an error) |
| `/v1/health/pipeline` | GET | Ingestion funnel health summary (`healthy`/`degraded`/`disabled`; `enabled: false` + zeroed counters while the observability flag is OFF) |
| `/v1/config/sdk/versions` | GET | SDK version-compatibility tier manifest (supported / deprecated / read-compatible / blocked-after-date + per-band capabilities; static non-secret policy data, always served — the `/v1/batch` ingress consultation rides `AETHER_SDK_VERSION_COMPAT_ENABLED` / `_MODE` (`off`/`shadow`/`warn`/`enforce`), default OFF) |
| `/v1/config/sdk/manifest` | GET | SDK remote config (signed manifests + rollouts) |
| `/v1/activation/*` | GET/POST | Self-serve tenant activation FSM (flag-gated `AETHER_ACTIVATION_ENABLED`, default OFF) |
| `/v1/kyber/missions[/*]` | GET/POST | Kyber Mission aggregate + monitoring read plane (operator; flag-gated `KYBER_MISSIONS_ENABLED`, default OFF) |
| `/v1/command-center` | GET | Read-only tenant Command Center aggregate — composes nine tenant-safe reads in-process (flag-gated `AETHER_COMMAND_CENTER_ENABLED`, default OFF) |
| `/v1/ml/predict` | POST | ML inference (single; 9 models: intent, bot, session, identity, journey, churn, LTV, anomaly, attribution) |
| `/v1/ml/predict/batch` | POST | Batch ML inference |
| `/v1/rewards/evaluate` | POST | Evaluate reward eligibility (A6 no-custody) |
| `/v1/rewards/evaluate/batch` | POST | Batch eligibility evaluation (max 50) |
| `/v1/rewards/campaigns` | POST/GET | Campaign management |
| `/v1/rewards/campaigns/{id}/rules` | POST/GET | Rule management |
| `/v1/rewards/decisions` | GET | Eligibility decision log |
| `/v1/rewards/actions` | GET | Action payload queue |
| `/v1/rewards/proofs` | GET | On-chain claim proofs |
| `/v1/rewards/rails` | POST/GET | Tenant delivery rail config |
| `/v1/track/traffic-source` | POST | Traffic source classification |
| `/v1/onchain/contracts/{address}` | GET | Tenant-scoped contract metadata; optional `chain_id` disambiguates same-address contracts across chains |
| `/v1/agent/deployments` | POST/GET/PATCH | External agent deployment registry (flag-gated, observation-only) |
| `/v1/providers/keys` | POST/GET/DELETE | BYOK key management (encrypted at rest) |
| `/v1/providers/usage` | GET | Per-tenant provider usage stats |
| `/v1/providers/health` | GET | Provider health + circuit breaker states |
| `/v1/providers/test` | POST | Test a provider call |
| `/v1/provider-connections/*` | GET/POST/PATCH/DELETE | Provider runtime connection lifecycle (feature-gated `AETHER_PROVIDER_RUNTIME_ENABLED`, default OFF) |
| `/v1/provider-webhooks/{identity_key}` | POST | Provider webhook delivery gateway (unauthenticated; HMAC/endpoint-secret verified; `X-Aether-Tenant-ID` is a routing hint, not auth) |
| `/v1/admin/kyber/provider-connections/*` | GET/POST | Provider runtime operator plane (additional `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED`, default OFF) |

## Event Flow

```
1. User action (click, scroll, wallet connect, purchase)
         │
2. SDK captures raw event data + device fingerprint
         │
3. Consent check (is this category allowed?)
         │
4. Event queued in memory (+ persisted to localStorage/AsyncStorage)
         │
5. Batch threshold reached OR flush timer fires
         │
6. POST /v1/batch { batch: [...events], sentAt, context }
   (staging/production reject release-critical events missing the canonical
    envelope fields sequence/schemaVersion/surface: `envelope_missing:<field>`)
         │
7. Backend pipeline:
   ├── IP enrichment (MaxMind GeoLite2)
   ├── Identity resolution (deterministic + probabilistic)
   ├── ML scoring (intent, bot detection)
   ├── DeFi transaction classification
   ├── Traffic source classification
   ├── Funnel matching
   └── Heatmap grid generation
```

## SDK Size Comparison

| SDK | v6.x (Fat Client) | v7.0 (Thin Client) | Reduction |
|---|---|---|---|
| **Web** | ~12,700 LOC | ~5,200 LOC | 59% |
| **iOS** | 474 LOC | 535 LOC | +13% (new features) |
| **Android** | 372 LOC | 493 LOC | +33% (new features) |
| **React Native** | 1,064 LOC | 497 LOC | 53% |

> iOS and Android grew because wallet tracking, consent management, ecommerce stubs, feature flags, and device fingerprinting were added. The net payload still decreased because device introspection was removed (backend derives from headers).

## What Moved to Backend

| Capability | Was (Client) | Now (Backend) |
|---|---|---|
| ML Intent Prediction | `edge-ml.ts` (401 LOC) | `POST /v1/ml/predict` |
| Bot Detection | `edge-ml.ts` | `POST /v1/ml/predict` |
| DeFi Classification | `protocol-registry.ts` + 15 trackers | Backend transaction enrichment (ingestion + on-chain services) |
| Portfolio Aggregation | `portfolio-tracker.ts` (209 LOC) | Backend aggregation service |
| Wallet Classification | `wallet-classifier.ts` (170 LOC) | Backend wallet labeling (graph + fraud services) |
| Chain Registry | `chain-registry.ts` + `evm-chains.ts` | Backend chain metadata (`/v1/onchain/*`) |
| Traffic Source Classification | Regex engine (431 LOC) | `SourceClassifier` (`POST /v1/track/traffic-source` + inline at ingest) |
| Survey Rendering | `feedback.ts` (596 LOC) | Backend-rendered iframe |
| A/B Experiments | `experiments.ts` (125 LOC) | Feature flags module |
| Web Vitals *(re-added client-side)* | `performance.ts` (188 LOC) | Web SDK performance module now emits raw Web Vitals again; analysis is backend-side |
| OTA Data Updates | `update-manager.ts` (301 LOC) | `GET /v1/config/sdk/manifest` (signed) |
| Funnel Matching | `funnels.ts` (357 LOC) | Backend event matching |
| Heatmap Aggregation | Grid building (392 LOC) | Backend grid generation |
| Identity Resolution | N/A (not available) | Backend resolution service |

## Platform Parity

All four SDKs expose the same core public API surface:

| Method | Web | iOS | Android | React Native |
|---|---|---|---|---|
| `init(config)` | Y | Y | Y | Y |
| `track(event, props)` | Y | Y | Y | Y |
| `pageView` / `screenView` | Y | Y | Y | Y |
| `conversion(event, value)` | Y | Y | Y | Y |
| `hydrateIdentity(data)` | Y | Y | Y | Y |
| `getIdentity()` / `getAnonymousId()` | Y (`getIdentity`) | Y (`getAnonymousId`) | Y (`getAnonymousId`) | Y (`getIdentity`) |
| `observe(type, props)` (canonical registry events) | Y | Y | Y | Y |
| `walletConnected(addr)` | Y | Y | Y | Y |
| `walletDisconnected(addr)` | Y | Y | Y | Y |
| `walletTransaction(tx)` | Y | Y | Y | Y |
| `grantConsent(categories)` | Y | Y | Y | Y |
| `revokeConsent(categories)` | Y | Y | Y | Y |
| `trackProductView(product)` | Y | Y | Y | Y |
| `trackAddToCart(item)` | Y | Y | Y | Y |
| `trackPurchase(order)` | Y | Y | Y | Y |
| `isFeatureEnabled(key)` | Y | Y | Y | Y |
| `getFeatureValue(key)` | Y | Y | Y | Y |
| `getFingerprint()` | Y* | Y | Y | Y |
| `flush()` | Y | Y | Y | Y |
| `reset()` | Y | Y | Y | Y |

*Web SDK auto-generates fingerprint on init; available via `context.fingerprint.id` in every event.

## Safety Mechanisms

| Mechanism | Description |
|---|---|
| **Max cluster size** | Refuse merge if resulting cluster exceeds 50 profiles (configurable). Prevents cascading merges in NAT/VPN scenarios. |
| **Cooldown** | Don't re-evaluate rejected pairs for 24 hours. |
| **Fraud gate** | If either profile has fraud score > 40, route to manual review regardless of identity confidence. |
| **Undo capability** | `RESOLVED_AS` edges store full signal snapshots. Merges can be reversed by restoring the secondary profile. |
| **Privacy** | All PII (email, phone, IP) stored as SHA-256 hashes only. Raw values never persisted in graph or audit trail. |

## Model Extraction Defense (v0.1.0-alpha.0)

The ML serving pipeline is wrapped with a modular defense layer that protects against model extraction and knowledge distillation attacks.

```
Request ──> Auth ──> Extraction Defense ──> Model.predict() ──> Output Defense ──> Response
                     ├─ Rate Limiter                            ├─ Logit noise
                     │  (per-key + per-IP)                      ├─ Top-k clipping
                     ├─ Canary Detector                         ├─ Watermark embedding
                     ├─ Pattern Detector                        └─ Entropy smoothing
                     └─ Risk Scorer
```

| Component | Purpose |
|-----------|---------|
| **Query Rate Limiter** | Dual-axis sliding window (per-API-key + per-IP), three time windows |
| **Query Pattern Detector** | Detects feature sweeps, similarity clustering, uniform probing, bot timing |
| **Output Perturbation** | Logit noise, top-k clipping, entropy smoothing — scales with risk score |
| **Model Watermark** | HMAC-based probabilistic bias for forensic identification of extracted models |
| **Canary Detector** | Secret-seed trap inputs trigger cooldown on detection |
| **Risk Scorer** | EMA-smoothed aggregate score across 4 tiers (normal/elevated/high/critical) |

All protections are gated behind `ENABLE_EXTRACTION_DEFENSE` (default off).
The middleware resolves an explicit defense mode at request time (extraction
mesh → legacy defense layer → off); with `REQUIRE_EXTRACTION_DEFENSE=true`
(production profiles) an unavailable defense fails closed with
`EXTRACTION_DEFENSE_UNAVAILABLE` instead of silently passing traffic. Platform
operator tenants (Olympus staff; see [Access Control](ACCESS-CONTROL.md#platform-operators))
skip it, together with the burst limit and quota metering. The middleware
resolves that operator status before the route policy, which admits only
admins of platform operator tenants or Kyber operators to `/v1/admin/**` and
`/v1/diagnostics/**`. See
[Model Extraction Defense](MODEL-EXTRACTION-DEFENSE.md) for full documentation.

## Multi-Model Intelligence Harness (0.1.0-alpha.0)

A provider-neutral intelligence runtime lets AI models operate as
interchangeable planning, reasoning, classification, and synthesis engines
inside Aether's controlled harness. OpenAI and Anthropic are the first two
providers; additional providers (Kimi-family, open-weight, OpenAI-compatible
endpoints, Bedrock, self-hosted) plug in as isolated adapters without touching
orchestration logic. Every answer is tenant-scoped, evidence-backed,
policy-governed, observable, auditable, and verifiable.

The harness extends Aether additively — it does not replace the intelligence
graph, graph mutation gateway, entity/identity model, consent authority, audit
ledger, or the Noesis read-only intent + repository-dispatch architecture.
The design decision record is [ADR-008](decisions/ADR-008-multi-model-intelligence-harness.md).

Canonical contract plane (single source of truth, codegen twins via
`scripts/generate_platform_contracts.py`):

| Registry | JSON source | Generated twins |
|---|---|---|
| Model catalog | `packages/shared/contracts/model-registry.json` | `packages/shared/model-registry.ts`; `shared/model_governance/generated_model_registry.py`; `docs/_generated/model-registry-table.md` |
| Task profiles | `packages/shared/contracts/task-profile-registry.json` | `packages/shared/task-profile.ts`; `shared/model_governance/generated_task_profiles.py`; `docs/_generated/task-profile-table.md` |
| Intelligence projections | `packages/shared/contracts/intelligence-projection-registry.json` | `packages/shared/intelligence-projections_generated.ts`; `shared/intelligence_projections/generated_registry.py`; `docs/_generated/intelligence-projection-registry-table.md`; `docs/_generated/intelligence-projection-dependency-graph.md` |
| Relationship predicates (Relational Intelligence Spine) | `packages/shared/contracts/relationship-predicate-registry.json` | `packages/shared/relationship-predicate-registry.ts`; `shared/relationship_spine/generated_relationship_predicate_registry.py`; `docs/_generated/relationship-predicate-registry-table.md` |
| Relationship motifs (Relational Intelligence Spine) | `packages/shared/contracts/relationship-motif-registry.json` | `packages/shared/relationship-motif-registry.ts`; `shared/relationship_spine/generated_relationship_motif_registry.py`; `docs/_generated/relationship-motif-registry-table.md` |
| Spine registry | `packages/shared/contracts/spine-registry.json` | `packages/shared/spine-registry.ts` (exported from `packages/shared/index.ts` beside the ADR-011 D3 envelope); `shared/spine/generated_spine_registry.py`; `docs/_generated/spine-registry-table.md`. Each spine row carries a 14-item conformance vocabulary that lives in-registry ([ADR-011](decisions/ADR-011-spine-composition-kernel.md)) |

### Intelligence projection plane

A **360** is an intelligence projection over canonical Aether truth — it is
never a competing system of record. The intelligence projection plane owns the
single canonical registry (24 technical projections, nine of which — `outcome360`,
`economic360`, `infrastructure360`, `communication360`, `risk360`, `fraud360`,
the context-360 time leaf `temporal360`, the context-360 WHO/SET leaf
`population360` and the context-360 WHERE leaf `geographic360` — are now
implemented native providers) and the shared request/context/result contracts
(TS + Python) that every future 360 provider implements against.
Economic360 accepts `journey` subjects so its Evidence section can expose
source-linked commerce operation records carried by Journey steps; it does not
copy operation amounts or claim settlement from those links.
`implementationState` is repo metadata describing

how far a projection has been converged onto the plane (`in_flight` = an
existing implementation that is not yet a native provider) — it is NOT a
readiness signal and is never surfaced as `production_ready`. The runtime is a
fail-isolated provider protocol
(`shared/intelligence_projections/provider.py` + `registry.py`): one broken
projection degrades its own result, never the plane. P0 shipped the plane as a
library with no projection route; projection routes land only as classified
legacy bindings per vertical slice — the read-only `/v1/infrastructure` (every
route a GET, no generic catch-all) was the first, and the read-only
`/v1/communication360` surface follows the same template (written, tested and classified, but not mounted in `main.py` today). The implemented
providers are registered at boot — `main.py`'s lifespan calls
`dependencies.projection_plane.register_implemented_projection_providers` — so a
projection surface answers live instead of degrading to `provider_unavailable`
(a provider is not live until registered at this mount; the enforcement note is
in the source-of-truth). All 24 providers register, with 9 classified as
`implemented` and 15 as `in_flight`; registration does not promote status. The
tenant-scoped `POST /v1/experience360/frames` route composes the separate
18-surface product catalog, and `GET /v1/experience360/catalog` reports catalog
and provider-registration state. Policy runs before reads, and missing or
unsupported slot paths remain unknown/degraded. The product catalog is
crosswalked to the checked-in
[`AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md`](../reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md),
which defines the exact 18 backend product surfaces; the supplemental
architectural blueprint informs shared projection and lens design but does not
change that catalog's scope. Each catalog entry records its source section,
required slots, subjects, lenses, owner, and purpose. All 18 entries are now
marked `source_aligned` for contract metadata and slot IDs. This is contract
alignment only: it does not prove a complete provider path, evidence coverage,
policy behavior, freshness, API reachability, or surface-level verification.

Recent backend slices bind Account360 profiles through exact tenant membership
and policy-scoped Profile360 reads, Campaign360 targeting-leakage findings,
Journey360 explicit role markers, and Location360 source/evidence lineage.
Account360 `members` accepts a graph membership edge only when its exact tenant
graph-mutation-ledger aggregate proves the edge is live and the member resolves
to a canonical tenant entity; the bounded scans do not establish full roster
coverage or freshness.
Profile360's required `risk_summary` slot now binds to Risk360 assessments and
evidence for exact tenant-scoped entity and Agent subjects; it remains degraded
while a Profile-specific freshness threshold is unknown.
Profile360's required `value_summary` slot now binds to Economic360's exact
tenant-scoped entity and Agent summary/evidence; Outcome360 attribution to
entity/profile subjects and Profile-specific freshness remain unresolved, so it
also remains degraded.
Profile360's required `relationships` slot now reads Relationship360 graph-ledger
evidence for an exact tenant entity subject; profile/member alias resolution,
ledger completeness, and Profile-specific freshness remain unknown, so the
slot stays degraded.
Profile360's required `location_temporal` slot now reads Geographic360's
tenant-scoped location evidence and timeline for an exact entity subject. The
provider marks recorded location observations explicitly; profile alias
resolution, continuous trajectory, cross-surface completeness, historical
point-in-time reconstruction, and Profile-specific freshness remain unknown,
so the slot stays degraded.
Account360's required `communications` slot now reads Communication360
evidence, interactions, and timeline only for an exact tenant-owned entity
subject with matching endpoint identity-binding evidence. It does not fan out
through account/workspace aliases or membership edges. Slot policy can suppress
the content, claims, and evidence references; source freshness and historical
consent coverage remain unknown, so the join is partial.
Value360's `confidence` slot now exposes Economic360 attribution evidence only
when a model confidence score and model type/version lineage are present. The
claim labels confidence as model-reported and states that calibration and
application to realized value or ROI are unvalidated; model-governance
calibration evidence remains unbound.
Value360's `financial_risk` slot now requires separate Economic360 and Risk360
claims for the same tenant and exact subject. Economic evidence must be a
direct subject-scoped fact, and Risk360 must provide an assessed economic,
payment, or transaction dimension; a generic RiskSignal does not satisfy the
join. Historical or explicitly ranged value requests remain unknown because Risk360's
latest assessment read cannot prove a coordinated snapshot, and current
freshness remains unknown, so successful current joins stay degraded.
The Value360 binding requests only Risk360's `financial_risk` section, which
contains evidence-backed scored financial dimensions and their assessment
lineage; unrelated findings, poisoning evidence, policy flags, and social
propagation are not forwarded into the slot.
Agent360 now joins agentic compatibility evidence to canonical Bronze by exact
tenant, agent, source-row, event, schema, and timestamp references; Rights
source identity, source trust, freshness, and unlinked historical rows remain
unknown. Execution360 joins current x402 approval-decision evidence to admitted
run IDs, while non-commerce authorities and historical links remain unknown.
Execution360 actor attribution now records the authenticated initiating
principal separately from the acting agent and links its `USER_ID` only through
an exact tenant-scoped active alias and active surviving canonical Human
subject, with both identity evidence references. An unresolved or ambiguous
read stays unknown; identity attribution does not establish action
authorization or delegation authority. The agentic fraud-network Risk360
handoff also requires one consistent, valid timezone-aware identity-binding
timestamp no later than the detector observation; otherwise it omits the
assessment rather than retroactively attributing it.
Execution360's required `latency_cost` slot now reads canonical AI invocation
facts only for admitted executions with an exact action ID and canonical Agent
match. It preserves invocation latency and evidence, groups selected costs by
currency, and omits cost amounts without a known valid cost basis. This is
invocation telemetry, not total execution, provider, or tool cost; reads are
bounded, historical replay is unavailable, and other cost authorities and a
freshness SLA remain unknown. Server lifecycle duration stays a separate
measurement.
Agent360's required `owner_delegator` slot now also joins the configured owner
Entity to the resolved canonical Agent only through an exact tenant-scoped
`OWNS` or `OWNS_AGENT` graph edge. The bounded edge scan reports truncation and
scope uncertainty, and claims retain graph-edge, configuration, and identity
evidence. A stored edge does not prove legal or effective ownership, historical
validity, freshness, or action authorization.
Risk360 reads versioned poisoning-detector records for exact tenant subjects
with lifecycle and evidence references; it does not independently verify
poisoning, detector coverage, source reputation, or freshness.
Risk360's `policy_flags` slot now reads exact tenant-and-Agent records from
`obs_agent_risk_signals` as reported observations with source evidence. The
slot remains partial: policy evaluation is unattested, no policy version is
present, and non-agent, historical, and complete-coverage behavior remains
unknown. `anomaly_events` now reads exact typed-subject Gold alert records and
can corroborate an explicit RiskSignal event reference against one tenant
Bronze SDK event record. It exposes metadata and evidence only; automatic
detector coverage, cause, severity, complete event coverage, and freshness
remain unknown.
Additional partial paths include Identity360 device/session identifier-type
metadata and an exact recorded `source_system_id` join to the provider runtime
registry; provider-registry freshness is unknown. Other partial paths include
Execution360's exact execution-linked RiskSignals, Social360's
propagation-eligible observed paths, and Episode360 exact episode-linked
communication facts. These paths remain partial where membership, anomaly,
stage, normalization, device/session inventory, risk-signal
production/freshness, propagation completeness, or the episode message-spine
join is unavailable. They do not change the affected technical providers'
`in_flight` status or establish complete product-surface conformance.
The first 2026-10-23 backend wave adds three more exact authority joins: Episode360
`timeline` resolves only observation IDs recorded on an episode against
tenant-scoped semantic Silver rows; Campaign360 `signal_sources` joins exact
touchpoint event IDs to tenant-scoped canonical events; and Memory360
`policy_state` exposes historical write-time allow decisions with timestamped
consent-policy evidence. Episode activity/session completeness and observation
policy/freshness remain unresolved; Campaign360 observation and source-fact
dimensions, event coverage, and freshness remain unknown; Memory360 current
consent and policy remain unevaluated. These are partial slot implementations,
not completed 360 surfaces.

A follow-up slice adds partial Signals360 `classification` evidence for exact
gateway-accepted SDK event types and registry families; source attribution,
semantic classification, policy, and freshness remain unknown. Workflow360 now
resolves exact execution initiator and approval decider identities through
unique active tenant USER_ID aliases, and joins only x402 approval decisions
referenced by admitted run-linked AgentExecutions. AgentExecution stores
workflow and invocation references only when a unique tenant AI invocation has
`action_id` equal to the stable execution ID; the provider verifies tenant, run,
agent, and action equality before exposing the step. Workflow definition-to-run
linkage, complete actor and step coverage, workflow-wide approval authority,
policy, and freshness remain unknown. Account360 adds bounded member Risk360 frames from
exact tenant-owned `MEMBER_OF` edges after account-slot and per-member policy
checks; roster completeness, temporal reads, related-account aggregation, and
freshness remain unknown. Communications360 reads exact-subject RiskSignals for
resolved agents and sources and mapped recipient entities. Source and recipient
reads require current analytics consent. The agent path now also requires an
exact canonical Agent identity and current analytics consent receipt before
RiskSignals are read. A missing, ambiguous, malformed, receipt-less, or denied
decision prevents the read; consent-authority failure marks the slot degraded.
Message-edge transfer, complete coverage, composite Risk360 output, and
freshness remain unknown. Journey360's required `communications` slot now
joins only tenant-scoped canonical communication facts whose typed journey ID
exactly matches the request. Message endpoints and free-text references do not
qualify; message-spine coverage, completeness, freshness, and historical replay
remain unknown. Episode360 `agent_handoffs` also remains unknown because
episode records and observations do not reference a canonical execution or
handoff ID. Event labels and agent metadata are not used to invent those links.
Journey360 `episodes` now joins only tenant-scoped EpisodeRecords that
explicitly persist the exact `journey_id`, with record/source evidence. Legacy
or unlinked records, association completeness, store freshness, policy, and
historical replay remain unknown; a missing link does not establish absence.
The current agentic/support slice adds three partial paths: Agent360
`owner_delegator` resolves the configured owner reference through an exact
tenant entity lookup and now requires an exact tenant graph `OWNS` or
`OWNS_AGENT` edge to the canonical Agent before emitting a relationship claim;
the stored edge does not assert legal or effective ownership. Execution360
`approval_chain` joins x402 approval requests and decisions to lifecycle approval,
action, and resource references, rejecting conflicts; Support360 `resolution`
exposes resolved/closed lifecycle state only with a matching applied event and
provider evidence. Effective agent authorization, other approval authorities,
business outcome facts, historical validity, and freshness remain unknown, so
these paths do not complete their surfaces or change their providers' `in_flight`
status.
The next provider slice adds three partial paths: Communications360
`policy_state` evaluates current consent for exact tenant, recipient-entity, and
purpose pairs while retaining historical communication-time outcomes
separately; Risk360 `propagation_paths` exposes bounded consent-gated observed
FOLLOWS paths with relationship evidence but no causal contagion claim; and
Value360 `reconciliation` returns separate economic and order-linked commerce
observations, resolving settlement references only by exact provider payment
ID and shared order reference. Non-consent policy, causal social contagion,
cross-source economic matching, reconciled totals, historical replay, complete
coverage, and freshness remain unproved. None of these paths completes its
surface or changes technical provider readiness.

The next provider slice adds Profile360 `syndicates` and Commerce360
`availability_price` partial paths. Profile360 verifies bounded exact-entity
membership candidates against tenant-owned population records explicitly
opted in to Syndicates, then checks the exact current `MEMBER_OF` graph-ledger
aggregate; a positive claim uses its live mutation ID. Historical and bounded
membership reads remain unknown, and roster completeness and freshness remain
unavailable. Commerce360 exposes lifecycle and provenance for exact product or
offer catalog revisions only; inventory availability, current offer price, and
freshness remain unknown. Location360 `timezone` remains unknown because no
exact tenant-scoped geographic timezone mapping is connected, and the provider
does not infer a zone from coordinates, place labels, or source-clock metadata.

The next 2026-10-23 provider wave adds partial Identity360 identifier,
namespace, and alias rows with record-level evidence; provider-registry joins
remain unknown. Social360's `syndicates` slot now binds opted-in Syndicates
membership to an exact tenant entity and current `MEMBER_OF` graph-ledger edge,
with a mutation evidence reference on each positive claim; roster completeness,
historical membership, and freshness remain unknown. Value360's
`attribution_credits` slot now rejoins credit conversion and touchpoint IDs to
tenant-scoped canonical records and checks campaign consistency. Historical
attribution remains unavailable, touchpoint lookups are capped, and the
underlying credit query is still unbounded.

Agent360 and Execution360 now carry typed actor kind, subject, authority-edge,
confidence, explanation, and independent driver-score fields. An Agent driver
score is populated only from an exact canonical server execution actor claim;
an authenticated initiator or source-reported actor does not establish who
drove an action. Agent360 converts one complete, continuous two-edge stored
delegation path into typed edges only when both records and all party identities
have exact evidence. This describes current observed records; it does not infer
transitive authority or effective authorization. All these additions are
partial slot paths and leave the 18-surface buildout incomplete.

The latest provider slice adds three evidence-bounded paths. Agent360's
`risk_summary` no longer reads raw `obs_agent_risk_signals`; its canonical
Risk360 path checks exact Agent scope, current analytics consent with a receipt,
and claim/evidence lineage. The product slot also has a separate Risk360
projection binding evaluated through the frame slot gate. The Agent360
provider's nested reader receives a request-scoped authorization envelope only
when `risk_summary` was requested and allowed, the slot binds to Risk360, and
the projection declares `risk360.read`. The envelope binds tenant, surface,
subject, slot, consumer, target, capability, and evaluated policy IDs. No
independent actor-granted `risk360.read` capability authority is represented
yet. Agent-specific freshness, historical replay, and causal contagion remain
unknown. Execution360's `risk_events` joins bounded, exact tenant/execution
RiskSignals and RiskAssessment snapshots for execution IDs admitted from
server lifecycle records. Producer coverage, assessment history, freshness,
and causality remain unknown; the records do not prove that an execution
caused a signal or assessment. Value360's `ltv` slot exposes evidenced
confirmed or adjusted conversion net-value observations by native currency
for exact supported subjects and occurred-at scope. It does not emit an LTV
amount while lifecycle completeness, outcome attribution, and freshness remain
unknown.
Value360's `web2_value` and `web3_value` slots now classify only exact
order-linked completed payment facts. Web2 requires an explicit supported card,
ACH, wire, SEPA, or bank-transfer rail. Web3 requires an explicit crypto flow or
on-chain rail, a complete native amount/asset/chain side, and an exact
transaction-hash evidence reference. The commerce ledger preserves source rail,
flow, asset, chain, and transaction details with as-of observations; it does
not store wallet addresses or aggregate payment amounts. Non-USD normalization,
wallet identity, source coverage, policy, freshness, and full Value360 slot
completion remain unknown.

The next 2026-10-23 provider slice adds partial `workflow_run` support to
Execution360. It admits tenant-scoped AgentExecution rows only when their
stored run ID and invocation IDs match current AI facts with the same action
and agent; run-wide step coverage, workflow completion, standalone run links,
and telemetry crosswalks remain unknown. Support360's case path now joins
communication metadata through the exact tenant, canonical provider
connection, and source case key. Message bodies and participant IDs stay
suppressed, and source-history completeness and freshness remain unknown.

Execution360 can also resolve an admitted external telemetry event to a unique
same-tenant Bronze event and its recorded observation envelope. The join checks
event ID, type, and occurrence time and exposes only ingress provenance and a
Bronze evidence reference. It does not identify the external executor, prove
an external effect, cover all source telemetry, or establish a workflow-run
telemetry crosswalk. Support360 can report an EpisodeRecord relation only when
that record names the same canonical journey and cites the exact verified
support-case journey-link event. There is no live producer for this relation;
population, historical state, source authorship, and freshness remain unknown.

The 2026-10-23 projection slice adds partial Social360 `influence_paths`: the
provider exposes bounded consent-authorized directed FOLLOWS paths and accepts
per-hop RelationshipFidelity components only when every vector evidence ID
matches the exact graph edge's relationship-fact evidence. Completeness,
freshness, actual influence, trust, and causal contagion remain unknown; the
`social_contagion`, `trust_edges`, and `risk_edges` slots remain unbound.
Workflow360 `triggers` now resolves only exact tenant events referenced by
run-linked AgentExecution `triggered_by_event_id` values when the event
authority reports an available read. Rows returned alongside an unavailable
or unread source are suppressed. The stored reference does not prove that an
event caused the workflow run or establish complete trigger coverage. Both are
partial projection paths; the 18-surface contract remains incomplete.

The latest provider wave binds Identity360 `namespace_map` to an exact
`source_system_id` lookup in the already loaded provider runtime registry,
with allowlisted metadata and unknown registry freshness. Signals360
`campaign_links` follows exact tenant/source-event touchpoints and resolves
each campaign through its same-tenant canonical repository. Episode360
`conversion_events` resolves only exact outcome IDs recorded by episode rows
and emits registered conversion definitions with canonical evidence.
Workflow360 `outcomes` follows outcome IDs explicitly referenced by exact
tenant/run AI invocation facts; the link records association only. Missing
policy, complete coverage, causal attribution, or source watermarks remain
unknown, and all four product slots remain partial.

Three required slots remain incomplete because of missing source contracts.
Episode360 `touchpoints` now resolves only `journey_touchpoint_ids` explicitly
recorded by tenant-scoped EpisodeRecords against canonical tenant-scoped
touchpoint rows with evidence. Legacy records, complete link inventory,
policy, freshness, and attribution links remain unknown; Journey touchpoints,
timing, labels, and attribution records do not create episode links. Risk360
`anomaly_events` remains partial: typed-subject Gold alerts and optional exact
Bronze event records provide evidence, while detector coverage and cause are
unattested. RiskSignals and assessment dimensions alone are not events.
Memory360 `cards` and
`embeddings_meta` stay unknown because semantic context pointers and optional
vector references do not establish canonical card or embedding-metadata
records. Each needs its own tenant-scoped authority, evidence, and applicable
policy and freshness semantics before the slot can be connected.

The current risk and authority join wave adds partial Support360 `risk` and
Execution360 `authority_check` paths. Support360 first proves an exact
tenant-owned canonical support case, then reads only case-keyed RiskAssessment
and RiskSignal records with risk and case evidence; missing or expired case
authority suppresses those reads. Case risk-history completeness, signal
coverage, freshness, business outcome, and contagion authority remain unknown.
Execution360 exposes only the action/resource-scoped delegation-engine result
stored in the same tenant-owned AgentExecution row as its lifecycle evidence.
The delegation engine now records a timezone-aware evaluation timestamp, and
Agent360/Execution360 consume only that exact decision-log timestamp after
checking it against the execution record time. Missing legacy timestamps stay
unknown; malformed or later-than-execution values degrade. This records when
the action/resource-scoped evaluation was observed and does not establish
current or standing authority.

Commerce360 `intent` now reads explicit human declarations against exact
tenant-owned product or offer records, preserving actor, effective/observed
time, revision, idempotency, and evidence. It does not infer intent from views,
carts, checkout, or payments; agent declarations and freshness remain
unsupported. Support360 `callbacks` now reads typed schedule and lifecycle
events tied to an exact case and verified provider connection, with idempotent
source events and stale-event protection. Provider origin, writer identity,
history completeness, and freshness remain unknown. Communication360 accepts
typed participant-role rosters through the signed tenant webhook, resolves
provider identities only through exact tenant/provider/account mappings, and
preserves source evidence and explicit coverage. A provider conversation ID is
still not canonical Conversation membership, and a provider delegation
reference is not canonical authority. These paths remain partial and do not
complete the 18 surfaces.

The Communication360 Agent authorship slot now requires an exact canonical
Agent entity in an author participant binding, the same tenant, explicit
provider account and conversation IDs, a valid role window at the recorded
event time, and both fact and trusted source-role evidence. A loose `agent_id`,
principal reference, or event actor cannot establish the author. Noncurrent
frames leave authorship unknown because participant-role history cannot be
replayed yet. The signed roster remains a source assertion; canonical
Conversation membership and complete author coverage are still missing.

The next backend authority slice adds append-only, tenant-owned Workflow360
definition revisions at `/v1/workflows/definitions`. Registration stamps the
authenticated actor and tenant; the HTTP read returns the latest exact
revision. The frame provider can select the highest revision both created
and effective by an exact `asOf` instant after validating a bounded,
complete 200-revision history. Truncated or malformed history remains unknown.
For a current definition summary, the authenticated registrar reference can
also resolve through one active tenant `USER_ID` alias and canonical Human
identity evidence. The summary reports the registrar identity state and
evidence separately from the recorded actor reference; historical `asOf`
identity remains unknown because alias history cannot be replayed. Registrar
identity does not identify a run initiator, approver, or authorized executor.
An AgentExecution can additionally retain a caller-reported definition ID,
revision, and digest after the authenticated execution route verifies one
tenant AI invocation run link and the exact active definition revision. A
Workflow360 run summary rechecks the stored link against its run, invocation,
execution, and definition evidence and reports a partial association. This
does not prove that the definition initiated the run or that its steps fired.
Definitions describe configured triggers and steps and do not establish that
a run fired, completed, or caused an outcome. Social360 now accepts explicit
trust-edge and social-contagion evidence assertions at
`/v1/social360/evidence/*`. Writes verify canonical entity, event, graph-path,
and linked risk-signal references before preserving the source assertion;
they do not write graph edges or prove causal transmission. Risk360's Gold
anomaly-alert admission requires an exact persisted RiskSignal and event
EvidenceRef; an explicit `bronze_sdk_events` reference can additionally resolve
one tenant event record without disclosing its payload. Automatic anomaly
detection, event coverage, cause, and freshness remain open. Agent360 can show
bounded observed delegation scopes after exact
identity and party joins, with `effectiveAuthorization=unknown`. Agent360
also requires one resolved tenant-owned canonical Agent before reading
source-asserted inbox/message observations into its communications slot.
Claims cite the exact identity, inbox, and message evidence; the read does
not establish canonical provider conversation membership. All of these
remain partial projection paths.

EpisodeEngine can persist a typed episode-to-semantic observation reference
when its caller supplies both an exact observation ID and the semantic Silver
authority marker. The link writer verifies tenant, namespace, status, time,
and event evidence. The live semantic pipeline does not yet supply the
episode association, so this producer seam does not establish complete
Episode360 timelines or source coverage.

Exploration surfaces compose over the engine through projection-backed surface adapters

(`services/api/journeys/exploration/adapters/projection.py`).
The design decision is [ADR-010](decisions/ADR-010-intelligence-projection-plane.md);
the source-of-truth is
[INTELLIGENCE_PROJECTION_ARCHITECTURE.md](../reference/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md).

### Graph operating contracts

The graph-first intelligence infrastructure adds shared contracts without creating a
second truth system. `packages/shared/graph-context-contract.ts` defines the
authoritative `GraphScope` tuple (tenant, workspace, and environment), scoped
object references, one selection vocabulary, immutable snapshots and diffs,
scope-safe persistence, and deterministic scope switching. Its canonical query
adapter accepts the existing `UniversalGraphQueryRequest` and reports any
lossy translation explicitly. Contract validation fails closed when references,
workspace scope, temporal modes, depth, or result bounds are inconsistent.

`packages/shared/action-runtime-contract.ts` defines the decision, execution,
approval, impact, and rollback/reversibility envelopes used to govern graph
actions. Its transition guards require approval validity and bound execution
evidence before terminal states can be recorded; requested approval level and
scope are preserved while tenant and decision identity remain bound to the
outer transition context. Execution validation checks every plan-step target
against the execution tenant/environment and the canonical top-level target
set. These modules are exported
from the shared package as types and deterministic validation/transition
helpers; they do not introduce a parallel executor, a new source of record, or
proof that every application host has mounted the runtime. Aether now obtains
its graph scope from the authenticated `/v1/me` profile and refuses to render
graph-native children while that server-owned scope is loading, incomplete, or
inconsistent with the authenticated tenant. The current
`single_workspace_tenant_v1` authority maps one workspace to each tenant and
uses the logical graph environment `production`; neither coordinate comes from
the URL or deployment configuration. Kyber has not yet migrated to this
runtime. The Aether `/explore` surface is nevertheless classified as
parity-required in the generated Kyber feature-surface manifest, so authorized
internal tenant-mirror inspection uses the existing generic mirror capability
and disclosure policy rather than exposing Kyber in the customer product.
The Aether `/agents/:agentId` Agent 360 route is explicitly parity-exempt:
it combines a tenant profile, deployment-run evidence, and a public marketplace
snapshot, while Kyber's agentic-observability surface is a separate operator
contract and does not reproduce that customer view. It is not a byte-parity
Tenant Mirror surface until an equivalent resolver and parity proof exist.

Lens identity remains registry-governed: `packages/shared/contracts/lens-registry.json`
generates `packages/shared/lenses_generated.ts`, and projection availability
continues to come from the intelligence-projection registry. Frontend lens
composition joins those generated authorities instead of hardcoding duplicate
readiness or truth claims.

Graph rights resolve through the canonical Rights Authority rather than a
graph-local ledger. `packages/shared/contracts/rights-vocabulary.json` and its
TypeScript/Python bindings define the shared vocabulary, while the mounted,
rollout-gated `/v1/rights` surface records effective decisions and revocation
impact within the authenticated tenant boundary. The graph context carries
rights policy and references only; enforcement, retention, training use, and
generalization decisions remain owned by the Rights Authority.

The graph-first runtime keeps transport and authority separate: `/v1/explore`
requests serialize only the tenant/surface coordinates currently supported by
that endpoint, while client cache keys retain the full host-authoritative
tenant/workspace/environment scope. Backend traversal validates anchors and
filters explicitly foreign graph edges before limits. Immutable snapshot/diff
controls and Noesis proposal review remain default-OFF and route any governed
approval back through the existing permission-checked Decision Intelligence
surface.

### Provider transport adapters

Provider SDKs live only behind the harness's provider-neutral `AsyncModelProvider`
contract (`services/api/intelligence/model_runtime/provider.py`); orchestrators such as Noesis
never import them. Real transport for the first two providers lives in
`services/api/intelligence/model_runtime/adapters/`:

| Adapter | Transport | Env surface |
|---|---|---|
| `AnthropicModelProvider` (`adapters/anthropic.py`) | Anthropic SDK (lazy-imported in `complete()`) | `ANTHROPIC_API_KEY`, `NOESIS_LLM_MODEL` |
| `OpenAIModelProvider` (`adapters/openai.py`) | `httpx` POST to `{base_url}/chat/completions` (no OpenAI SDK) | `OPENAI_API_KEY`, `NOESIS_LLM_MODEL`, `OPENAI_API_BASE` |
| `OpenAICompatibleModelProvider` (`adapters/compatible.py`) | inherits the `httpx` POST `{base_url}/chat/completions` transport unchanged | `MODEL_RUNTIME_COMPAT_API_KEY`, `MODEL_RUNTIME_COMPAT_MODEL`, `MODEL_RUNTIME_COMPAT_BASE_URL`, `MODEL_RUNTIME_COMPAT_PROVIDER_NAME` |

All three adapters read credentials/config from the process environment at
construction (constructor kwargs take precedence), expose `is_configured()`,
and complete a `ModelRequest` → `ModelResponse` asynchronously via `complete()`.
Failures surface as `ModelNotConfigured`, `ModelTimeoutError`, or
`ModelProviderError`; request content and credentials are never logged.

`OpenAICompatibleModelProvider` (`adapters/compatible.py`) is a thin subclass
of `OpenAIModelProvider` that reuses the inherited httpx chat-completions
transport unchanged, so it inherits the same error taxonomy
(`ModelNotConfigured` / `ModelTimeoutError` / `ModelProviderError`) and the
same "request content and credentials are never logged" guarantee. Its config
is read from a dedicated `MODEL_RUNTIME_COMPAT_*` env surface, and its
`provider_name` is an instance attribute (default `"openai_compatible"`,
overridable per instance via constructor kwarg or
`MODEL_RUNTIME_COMPAT_PROVIDER_NAME`). Because the runtime registry keys
providers by `provider_name` (`ModelRuntimeService._providers`), a deployment
can register several compatible endpoints at once — Kimi-family, self-hosted
vLLM/TGI, other OpenAI-compatible vendors — alongside the built-in `openai`
and `anthropic` adapters without collision.

| Compatible-adapter env var | Maps to | Fallback when unset |
|---|---|---|
| `MODEL_RUNTIME_COMPAT_API_KEY` | `api_key` | `OPENAI_API_KEY` |
| `MODEL_RUNTIME_COMPAT_MODEL` | `model` | `NOESIS_LLM_MODEL` |
| `MODEL_RUNTIME_COMPAT_BASE_URL` | `base_url` | `OPENAI_API_BASE` |
| `MODEL_RUNTIME_COMPAT_PROVIDER_NAME` | `provider_name` | `"openai_compatible"` |

Config precedence (highest first): explicit constructor kwargs, then the
`MODEL_RUNTIME_COMPAT_*` vars, then the `OpenAIModelProvider` defaults
(`OPENAI_API_KEY` / `NOESIS_LLM_MODEL` / `OPENAI_API_BASE`). A deployment that
sets only the `MODEL_RUNTIME_COMPAT_*` vars can drive a compatible endpoint
without touching the OpenAI env surface at all.

The Anthropic adapter is capability-driven: it never sends sampling parameters
(`temperature`/`top_p`/`top_k`) because newer Anthropic models reject them with
HTTP 400 — it sends only `model`, `max_tokens`, `system`, and `messages`. The
OpenAI adapter emits `response_format={"type":"json_object"}` when the request
asks for it.

The Noesis LLM plan providers (`AnthropicNoesisPlanProvider` and
`OpenAINoesisPlanProvider` in `services/api/intelligence/noesis/provider.py`) now build a
`ModelRequest` and delegate the actual API call to the matching adapter via
`.complete()`, converting the `ModelResponse` back to the legacy `_call_api`
dict shape (`text`, `tokens_used`, `input_tokens`, `output_tokens`). Plan
validation (`_validate_provider_plan` / `_parse_plan_json`), the `plan()`
retry/budget/metrics loops, the `EnvironmentNoesisPlanProvider` test stub, and
the `ProductionNoesisPlanProvider` factory / `NOESIS_LLM_PROVIDER` routing are
unchanged. No direct Anthropic SDK or `httpx` imports remain in `provider.py`;
the fail-closed behavior on missing credentials or config is preserved.

### Intelligence planes

The model-runtime control plane builds on the provider adapters as a package
under `services/api/intelligence/model_runtime/`:

| Plane | Package | Responsibility | ADR-008 |
|---|---|---|---|
| Routing / policy | `routing/` | Four routing modes (`auto` / `tenant_default` / `explicit` / `policy_required`), server-authoritative entitlement resolution, fallback chains, route audit entries | D4 |
| Credentials | `credentials/` | Per-tenant LLM credential resolution through the `shared.credentials.CredentialBackend` platform: BYOK/static + AWS Secrets Manager backends, secret-token rotation, cache TTL; only secret-free masked metadata leaves the backend | D5 |
| Task profiles | `task_profiles/` | Versioned, validated task-profile registry (output schemas + prompt loaders) that routing plans consume | D3/D4/D7 |
| Context | `context/` | Retrieval-before-synthesis: an allowlisted `EvidenceSet` is built, scoped, and assembled into a grounded prompt; injection/size guards fail closed | D6 |
| Synthesis | `synthesis/` | Grounded answering path: allowlisted plan kinds, a grounding gate (insufficient/stale evidence fails), cited `EvidenceCitation` rendering, secret screening | D6 |
| Verification | `verification/` | Post-synthesis faithfulness + claim checks and cross-tenant secret-leak detection; any failure blocks the result | D7 |
| Evaluation | `evaluation/` | Scenario runner, faithfulness scorers, and a `RegressionGate` that fails when measured quality drops | D7/D8 |
| Observability | `observability/` | Provider health/readiness probes, fail-closed circuit breakers, metrics recorder, incident classification, runbooks | D8 |
| Config | `config.py` | Single `MODEL_RUNTIME_*` settings source; feature gate OFF by default; staging/production fail closed (never `in_memory`, never `deterministic`) | D5/D8/D9 |
| Pipeline | `pipeline.py` | `HarnessPipeline.run()` wires context → synthesis → verification into one facade with content-free stage errors | D6/D7 |
| HTTP | `routes.py` | `/v1/model-runtime/*` — feature-gated OFF (503 when disabled), server-authoritative tenant scope from the authenticated request state | D8/D9 |

The pipeline error contract is intentionally short: `HarnessPipelineError`
messages name the failing stage and exception class only — never evidence,
synthesis content, or credential material. Expected failures map to their
stage (`context` / `grounding` / `plans` / `synthesis` / `verification`);
anything unexpected still fails closed under a stage name. Rendering is
downstream of the pipeline: it returns the structured `SynthesisResult` plus an
optional `VerificationResult`, and evaluation/routing decide how to surface it.

Binding security invariants: credentials never in source/frontend bundles/logs/
prompts/persisted content; the model never receives direct database authority;
the model may propose only allowlisted structured plans; Aether executes all
retrieval; tenant scope is server-authoritative; staging/production fail closed
on missing credentials/config; no cross-tenant evidence leakage; the model never
selects or overrides tenant scope.

## Data Exchange Plane (v0.1.0-alpha.0, flag-gated)

A governed tenant-facing import/export layer mounted under `/v1/data-exchange/*`
(seven router groups: settings/capabilities/usage, import envelopes, saved
import mappings, export envelopes, artifact history, signed transfers, and the
PDF reports plane). Doctrine: *many ways in — one canonical graph — many ways
out — one governed portability layer*. The plane is a control layer that
composes onto the existing canonical seams (import FSM/commit/rollback,
exporter registry, identity resolution, durable jobs, shared ObjectStore) — it
is never a second ingestion path and never a third import state machine.
Payload bytes live in the shared ObjectStore; Postgres holds only envelope
metadata (`data_artifacts`, `data_exchange_saved_mappings`, `report_renders`,
created by the `20260905_data_exchange` Alembic migration). `main.py` mounts
each surface only behind the `settings.data_exchange.*` flags —
`DATA_EXCHANGE_ENABLED` (envelope routers + the `data_exchange.migrate_legacy_artifact`
job handler), `DATA_EXCHANGE_SIGNED_TRANSFERS_ENABLED`,
`DATA_EXCHANGE_REPORTS_ENABLED` (reports plane + the `report.generate` handler),
plus `DATA_EXCHANGE_OBJECT_STORE_ENABLED` / `DATA_EXCHANGE_PARQUET_ENABLED` for
transport/storage features — all OFF by default. Routes enforce the `data_exchange`
RBAC domain (added to `ALL_DOMAINS` / `TENANT_DOMAINS`, auto-granted to tenant
owner/admin/viewer) via `services/api/ingestion/data_exchange/authz.py`, resolving each
dotted `data_exchange.*` grant to the legacy read/write/admin alias the proxied
seam admits. See `BACKEND-API.md` ("Data Exchange Plane") and
`docs/architecture/plans/data-exchange-api.md` for the full contract.

## Universal Provider Runtime (0.1.0-alpha.0)

The Universal Provider Runtime (UPR) makes provider integrations pluggable: a
new provider is a self-contained plugin (manifest + capability adapters +
normalizer + fixtures + registration) that registers through shared runtime
interfaces. The legacy `BaseConnector` system, `/v1/integrations/
connectors/*` routes, credential service, Bronze ingestion, sync-run ledger,
and webhook inbox are untouched and remain authoritative; legacy connectors
are re-exposed through the runtime by a compatibility plugin. The design
decision record is [ADR-009](decisions/ADR-009-universal-provider-runtime.md).

Provider identity is `family.product.capability` (e.g. `shopify.admin.orders_read`);
legacy connectors map onto the identity `(connector_type, "ingestion", "connector")`
with manifests byte-identical to the catalog, so plugin and catalog can never drift.

Contract plane — `shared/integration_contracts/` (provider plugin protocol,
capability adapters, `RawProviderRecord`/`AetherEvent` envelopes, normalizer,
acquisition, health, reconciliation, certification) and `shared/commerce_contracts/`
(canonical `Money`/`CommerceOrder`/`OrderSnapshot` + `commerce.*` event families):

| Layer | Modules |
|---|---|
| Contract plane | `shared/integration_contracts/` — plugin, stream, source-object, raw/event, normalization, acquisition, health, reconciliation, and certification contracts; `shared/commerce_contracts/{money,order,events}.py` |
| Runtime service | `services/api/connectors/provider_runtime/` — registry, validation, legacy compatibility, credential broker, raw store, event bridge, pull/webhook ingress, source-object mapping, tenant route ledger and opt-in graph writer fence, health, and certification |
| Reference plugin | `services/api/connectors/providers/shopify/` — `shopify.admin.orders_read`, SSRF-safe shop domain, HMAC webhook verify, order normalizer, REST compatibility pull and opt-in pinned GraphQL order snapshots |

Data flow is **raw-before-canonical**: `RawProviderRecord`s are persisted
idempotently in protected provider Bronze before normalization. V1 retains
native provider-record deduplication; v2 keys raw revisions by tenant,
provider, verified source account and realm, object, and source revision.
Consent-admitted canonical `AetherEvent`s enter typed Bronze and the
transactional event outbox together, then the supervised relay publishes them
at least once. Raw or canonical persistence failure leaves a pull cursor or
webhook inbox unadvanced. The outbox is transport evidence, not source
authority or graph projection.

Feature gating: all UPR routes are off by default
(`AETHER_PROVIDER_RUNTIME_ENABLED=False`); the operator plane additionally
requires `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED`; `importlib.metadata` entry-point
discovery is off unless code constructs the registry with `entry_points_enabled=True`
(no environment variable sets it). Legacy paths are
unaffected regardless. Staging and production startup rejects enabled UPR
ingress when `OUTBOX_RELAY_ENABLED` is false. Tenant route records and the
guarded graph writer are not yet called by all legacy and native writers, so
tenant cutover remains disabled.

Binding security invariants: provider credential writes use opaque refs scoped
to tenant, provider identity, and connection; persisted legacy tenant/provider
refs remain resolvable for existing connections. Secrets pass only through
`credential_service` refs (never plaintext). The webhook gateway is
**fail-closed**: a signature scheme without a secret denies, and
`endpoint_secret` providers require a
constant-time-matching presented token; `X-Aether-Tenant-ID` is a routing hint
only, not auth; connection loads enforce tenant ownership (cross-tenant id →
404); `shop_domain` is allowlisted to `*.myshopify.com` (SSRF gate); errors
carry `safe_message` only; manifest capability claims are verified against
actual adapters at registration and certification.

## Reconciled Control Plane (§0–40 lane, flag-gated)

The **Reconciled Control Plane** is Aether's operational authority that
converges every managed integration (SDKs, connectors, provider connections,
webhooks, imports, curated feeds) toward an authorized, healthy, supportable
desired state — *install once, continuously reconcile*. Doctrine: *the SDK
observes; the control plane manages; the backend reasons*. The §0–40 lane
ships the loop end to end: reconcile **classification** (desired state vs
evidence-backed observed state; never `actionable` from missing evidence),
typed ChangeSet **planning** with §39 risk + automation authority, §34
state-machine **execution** with verify-or-rollback and
last-known-good-after-verify, §16 admission + discovery/schema-mapping/
source-authority + §37 simulation/shadow, a flag-gated §32/§35 scheduler, and
**§40 progressive rings** driven by the §12.9 health-gated rollout engine + §29
fleet controller. The plane is **operator-only**: a read-only GET surface
under `/v1/admin/kyber/managed-integrations` (`/change-sets`, `/approvals`,
`/action-required`) gated by `require_kyber_operator`, surfaced in the Kyber
console vocabulary via the `kyber.reconciled_control.read` capability (D4
evidence) + `kyber_routes` declarations. Everything is **flag-gated OFF**
(`AETHER_RECONCILED_CONTROL_*`): engines are exercised by tests only, the
scheduler is idle until its master switch + kill-switch flip, and day-1
production activation sits behind the §41+ blueprint review. No tenant grant,
no self-service delivery, no hidden rewriting of customer-controlled binaries.
See `docs/architecture/RECONCILED_CONTROL_PLANE.md` for the architecture and
boundaries.

## Unified On-Chain Intelligence Graph

The Identity Graph above captures **who** a user is across devices and wallets. The Intelligence Graph extends it with four relationship layers that track **what** humans, agents, and protocols do — and how they interact with each other.

### Layer 1 — H2H (Human-to-Human)

The existing behavioral analytics layer, unchanged. Vertices: `User`, `Session`, `Device`, `Email`, `Wallet`, `IdentityCluster`. Nine ML models — edge (intent prediction, bot detection, session scoring) and server (identity resolution, journey prediction, churn prediction, LTV prediction, anomaly detection, campaign attribution) — continue to operate on this layer.

### Layer 2 — H2A (Human-to-Agent)

Tracks delegation and attribution between human users and autonomous agents. New edge types:

| Edge | Direction | Purpose |
|---|---|---|
| `LAUNCHED_BY` | Agent → User | Which human deployed the agent |
| `DELEGATES` | User → Agent | Explicit task delegation |
| `INTERACTS_WITH` | User → Agent | Conversational or transactional touchpoint |

Campaign Attribution is extended to attribute downstream conversions back through agent intermediaries to the originating human actor.

### Layer 2b — A2H (Agent-to-Human)

Tracks agent-initiated interactions back to human users — the reverse direction of H2A. Edge types:

| Edge | Direction | Purpose |
|---|---|---|
| `NOTIFIES` | Agent → User | Agent sends alert or status update |
| `RECOMMENDS` | Agent → User | Agent-initiated suggestion or recommendation |
| `DELIVERS_TO` | Agent → User | Task result delivery back to user |
| `ESCALATES_TO` | Agent → User | Human-in-the-loop escalation for decisions |
| `HAS_RECOMMENDATION` | Agent → User | Durable recommendation record |
| `SUPPORTED_BY` | Agent → User | Agent provides supporting evidence to human |
| `SELECTED_BY` | Agent → User | Human selected agent output |
| `ACTED_FOR` | Agent → User | Agent acted on behalf of human |
| `HAS_RETARGET_RECOMMENDATION` | Agent → User | Retargeting recommendation delivery |
| `APPROVED_BY` | Agent → User | Human approval of agent action |
| `REJECTED_BY` | Agent → User | Human rejection of agent action |
| `REQUESTS_APPROVAL_FROM` | Agent → User | Agent requests human approval |
| `ESCALATES_PAYMENT_TO` | Agent → User | Payment escalated to human for review |
| `ESCALATED_TO_HUMAN` | Agent → User | Generic agent-to-human escalation |

### Layer 3 — A2A (Agent-to-Agent)

Captures orchestration, hiring, payments, and protocol composition between autonomous agents. New edge types:

| Edge | Direction | Purpose |
|---|---|---|
| `HIRED` | Agent → Agent | One agent hiring another for a subtask |
| `PAYS` | Agent → Agent | X402 or on-chain payment between agents |
| `CONSUMES` | Agent → Agent | API or data consumption |
| `DEPLOYED` | Agent → Agent | Parent agent deploying a child agent |
| `CALLED` | Agent → Agent | Synchronous protocol-level invocation |

Anomaly Detection is extended to flag cyclic payment loops, abnormal hiring depth, and agent collusion patterns.

### Data Flow

All events — human and agent — flow through the existing Unified Pipeline via `classifyEvent()`. Four new event categories are introduced: `AgentBehavioral`, `Commerce`, `X402Payment`, and `OnChainAction`. The pipeline routes each category to the appropriate graph layer for vertex/edge upsert and model inference.

### Feature Flags

All Intelligence Graph layers are **disabled by default** behind
`IntelligenceGraphConfig` feature flags (`IG_AGENT_LAYER` for L2,
`IG_COMMERCE_LAYER` for L3a, `IG_X402_LAYER` for L3b, `IG_ONCHAIN_LAYER` for
L0, plus `IG_TRUST_SCORING`). The
one exception is the Agentic Commerce control plane
(`COMMERCE_CONTROL_PLANE_ENABLED`), which defaults on. See
`docs/architecture/INTELLIGENCE-GRAPH.md` for the full specification, edge schemas, and
rollout guide.

---

## Universal Asset Registry & Financial Normalization Surface

The financial-normalization program surfaces a canonical financial-registry
trunk on the backend plane. Its authoritative architecture is
[FINANCIAL_NORMALIZATION.md](../reference/source-of-truth/FINANCIAL_NORMALIZATION.md); this
subsection is a pointer, not a replacement.

**Universal Asset Registry service domain** (`services/api/graph/assets/`). Global
reference identity for fiat currencies, crypto natives, stablecoins, and tokens
(namespaced ids `fiat:USD`, `crypto:ETH`, `stablecoin:USDC`,
`token:<chain>:<contract>`), their chain deployments, and alias rows that
bridge legacy ids (`usdc`, `usdc:eip155:8453`) — never rewriting them. The
registry is reference + observational data only: it records UNRESOLVED
references and never originates, signs, or settles transfers.
`registry_version` is a deterministic sha256 over the sorted canonical seed
content — never a wall-clock timestamp — so valuations and graph projections
can cite it as registry provenance.

**Flag-gated `/v1/assets` API.** Mounted only when `settings.assets.api_enabled`
(`AETHER_ASSETS_API_ENABLED`, default OFF); registration/seed/canonicalize
additionally require `settings.assets.ingestion_enabled`
(`AETHER_ASSETS_INGESTION_ENABLED`, default OFF). Reads require the base `READ`
permission; writes require `ADMIN`. Runtime seeding is not enabled by default —
the seed ships as an ADMIN action, it is not run at startup.

**Event-time valuation + persistence** (`services/api/value/valuation/`). The pure
`value_at` engine and the `observe_price` ingest path price a native value into
a tenant-scoped `ValuationSnapshot` in a reporting asset at `effective_at`,
persisted as an immutable append-only row — a correction appends a NEW
superseding snapshot and flips the prior row to `superseded`, never mutating the
economic fact in place. Stablecoin amounts are peg-aware via the real
`classify_peg` (never assumed $1); unknown/unpriced is `missing_rate` with a
null reporting amount — never coerced to 0. Persistence (migration B:
`valuation_price_observations` / `valuation_snapshots` / `tenant_value_policies`)
and the flag-gated `/v1/valuation` API are landed: the router mounts only when
`settings.valuation.api_enabled` (`AETHER_VALUATION_API_ENABLED`, default OFF),
and the observational writes (`observe` / `value` / policy) additionally require
`AETHER_VALUATION_INGESTION_ENABLED` + ADMIN. `execution_by_aether` is always
False — the domain observes and reports, never executes.

**Reporting-asset-keyed safe rollup (W4a shared seam)** (`services/api/value/value/rollups.py`).
`safe_rollup` accepts a reporting context — a canonical `reporting_asset_id`
(`fiat:USD` default) and an optional `amount_in_reporting_asset` resolver — and
returns an additive `reporting_totals` envelope keyed by that asset (priced /
unpriced / excluded / stale counts, `coverage_percentage`, `rollup_status`) with
opt-in `value_lineage`. With no reporting context the output is byte-identical
to the USD-first contract, so existing consumers are unchanged. Conversion to a
non-USD reporting asset is never guessed: a record without a trustworthy amount
in that asset counts as unpriced-for-reporting and contributes nothing
(reporting total `None`, never `"0"`), and ownership rules
(testnet/spam/liability/counterparty) gate the reporting view exactly as they
gate the USD view. `ValuationService.reporting_asset_id_for` resolves a
tenant's reporting asset from `tenant_value_policies` (default `fiat:USD`) for
rollup/display entry points. The TS mirror (`packages/shared/value.ts`) adds
optional `reporting_totals` / `value_lineage` to `RollupResult`. This is the
Phase-4 shared seam; per-domain ingestion adapters and viewer-display
convergence follow.

**Registry → graph reference projector** (`services/api/graph/assets/graph_projector.py`).
Projects the canonical seed's asset / chain / fiat / deployment rows into GLOBAL
reference vertices plus DEPLOYED_ON_CHAIN edges (platform tenant, EXCLUDED
layer). Opt-in and never run at startup: the seeder projects only when invoked
with graph projection enabled (`AETHER_ASSETS_GRAPH_ENABLED`, default OFF).
Idempotency is storage-spelling neutral — an unchanged vertex is skipped and a
changed vertex is rewritten in place (`node_versioned`), never a duplicate
insert on its id.

**Graph reference surface.** New reference `VertexType`/`EdgeType` members
(`AssetDeployment`, `FiatCurrency`, `Issuer`, `PriceProvider`, `Venue`,
`Bridge`; `DENOMINATED_IN`, `PAID_WITH`, `SETTLED_IN`, `CHARGED_IN`,
`ASSESSED_IN`, `WRAPS`, `BRIDGED_FROM`, `VALUED_IN`, `DERIVED_FROM`,
`REVERSES`, `DISPUTES`) register canonical assets/deployments/chains/fiat as
**global** (`tenant_scoped=False`) reference vertices/edges on the non-actor
reference layer — the `EXCLUDED` bucket, never H2H/H2A/A2H/A2A. Tenant
isolation and the four actor layers are unchanged; the shared
`Asset`/`Chain` vertex types and pre-existing edge literals are reused, with
one literal per edge type.

---

## Agent Layer — Multi-Controller Internal Autonomy Architecture

The Agent Layer is the internal warehouse operating system for the intelligence graph. It handles intake, routing, discovery, enrichment, verification, staging, approval, commit, recovery, and operator briefing. This is for **internal team operations first** — not a user-facing assistant layer.

### Controller Hierarchy

```
Governance Controller .............. policy, budget, kill switch, audit, arbitration
  └── Nous Controller .............. top orchestration, coordination, synthesis
       ├── Intake Controller ....... objective intake, dedupe, classification
       ├── Discovery Controller .... evidence collection, source polling
       ├── Enrichment Controller ... fact generation, entity resolution
       ├── Verification Controller . provenance, schema, quality scoring
       ├── Commit Controller ....... mutation staging, review batches, approval
       ├── Recovery Controller ..... retry, rollback, checkpoint restore
       ├── Kinesis Controller ......... continuity, briefing, handoff, run history
       └── Catalyst Controller ...... scheduling, wake engine, missed-fire handling
```

### Shared Runtime Behaviors

- **Cycle** — Aggressive continuation behavior shared across Nous and domain controllers. Continues objectives, revisits stale areas, creates maintenance work within policy bounds. Not a controller.
- **Atoms** — Optional identity + mascot layer for controllers, teams, and workers. Fully functional but never required.

### Commit / Approval Workflow

All graph mutations require human approval in vNext. Mutations are classified (Class 1-5), staged, batched for review, and committed only after operator approval. High-risk mutations (Class 3-5) are surfaced with distinct visibility.

### Internal UI

CLI-first operational surface with three views:
1. Feed / Timeline
2. Kanban / Objective Board
3. Controller Health Console

### Repo Integration Boundaries

The agent layer owns: ingest orchestration, discovery, enrichment, verification, mutation staging, commit approval, recovery, operator briefing, objective/plan state, checkpointing, review batching, trigger routing, continuity.

The agent layer does NOT own: raw storage backends (PostgreSQL/Redis/S3/Neptune/Kafka), end-user graph surfaces, tenant-facing UX, provider adapters, lake CRUD, auth/tenancy.

---

## Fraud Intelligence Services

Three additive service modules mount conditionally via `main.py` behind feature flags:

| Service | Feature Flag | Router Prefix |
|---------|-------------|---------------|
| `services/api/intelligence/fraud_networks` | `FEATURE_FRAUD_NETWORKS` | `/v1/fraud/networks` |
| `services/api/value/flow_trace` | `FEATURE_FLOW_TRACE` | `/v1/flow-trace` |
| `services/api/graph/risk_overlay` | `FEATURE_RISK_OVERLAYS` | `/v1/risk-overlays` |

These services are fully additive — they add no startup overhead when their flags are disabled. They share the graph client, event producer, and investigation repository with existing services. The `FraudIntelligenceConfig` dataclass in `config/settings.py` owns the fraud-intelligence flags and tuning parameters (`max_network_depth`, `max_flow_trace_hops`).

See `docs/architecture/AGENT-CONTROLLER.md` for the full specification and `services/agents/README.md` for implementation details.

## External agent observation and recovery

The tenant-facing `/v1/agent/deployments` registry stores an external agent's
tenant-declared marketplace origin and validated source telemetry. The
run-explanation route returns a chronological evidence timeline for task,
action, trigger, policy, delegation, tool, and outcome events. It separates
canonical party binding, grant-scope evaluation, economic matches, and
execution occurrence. Party binding is an explicit tenant-admin mapping from
the deployment's `(source_namespace, agent_id)` reference to a canonical Agent
in the same tenant; missing or ambiguous mappings fail closed and do not feed
automatic identity merging. When canonical parties resolve, grant status,
endpoints, supported scope, and effective/revocation timestamps are evaluated
at the reported event time using backend-owned delegation data. Target binding
uses the source-declared `delegated_to_namespace`; missing or invalid target
namespace remains unresolved instead of inheriting the actor namespace. Since
action, resource, and time are source claims and there is no server-owned external
action receipt, a scope match does not verify that the action occurred.

When `AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED` is enabled, marketplace and run
projection mutations are queued in the supervised `graph-writer` outbox and
applied through `GraphMutationGateway`. Kyber's
`/v1/admin/kyber/agent-telemetry/graph-projection/{drain,reconcile,repair}`
routes support bounded draining and source-to-outbox recovery. A distinct,
read-only `GET /v1/admin/kyber/agent-telemetry/graph-projection/state-check`
compares bounded tenant source references against supported graph entities and
links. It may report consistent, inconsistent, or partial results and
findings such as missing, extra, mismatched, unresolved, or unauthorized links.
It is best-effort and non-snapshot, has coverage limits, and neither changes nor
certifies the whole graph. Recovery and inspection remain separate operations.

The separate, default-off `AETHER_AGENT_MARKETPLACE_CATALOG_ENABLED` observer
reads minimal public listing metadata from xAI's JSON-LD catalog index. It does
not collect template configuration or connect a public slug to a canonical
Agent. Catalog graph snapshots use the `platform` tenant scope and can be
reconciled with the same Kyber routes using `tenant_id=platform`.
