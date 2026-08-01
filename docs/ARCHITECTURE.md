---
title: Aether Architecture Guide
slug: architecture/system-map
section: architecture
visibility: P
audience: [architect, dev-senior, security]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/main.py
  - Backend Architecture/aether-backend/middleware/middleware.py
  - packages/shared/
canonical_owner: platform@aether
estimated_read_minutes: 20
toc_depth: 3
last_synced_commit: "fcc5b039"
---
# Aether vNext — Architecture Guide

## Overview

Aether is a **hybrid Python/FastAPI + Node/TypeScript** platform with four operational planes:

1. **SDK Plane** — Thin-client SDKs (Web, iOS, Android, React Native) collect raw events, fingerprints, wallet interactions, and session data. SDKs ship raw data to the backend.

2. **Backend Plane** — Python/FastAPI with 60+ service routers handling ingestion, identity, analytics, ML inference, graph, rewards, lake management, profile intelligence, population omniview, expectation engine, behavioral continuity, RWA intelligence, Web3 coverage, cross-domain TradFi/Web2 intelligence, extraction defense mesh, privacy/policy control plane, **notification intelligence** (`/v1/notifications/intelligence/*` — event-driven multi-channel operator alerts + end-user Slack/Discord/Telegram/Webhook delivery), plus the customer-facing productization surface: **registration** (`POST /v1/tenants`), **auth** (`/v1/auth/*` — email+password+OTP signup, Auth0 SSO callback, API-key recovery), **caller profile** (`/v1/me/*` — paginated self-service API keys), **billing** (`/v1/billing/*` — Stripe Checkout + Billing Portal + invoices), **Stripe webhook** (`/v1/admin/billing/stripe/webhook`, signature-verified), **SDK utilities** (`/sdk/identity/resolve` — cross-device identity), and a monthly overage cron task + SLA expiry worker + Dune Analytics scheduled polling worker running in the app lifespan. Infrastructure: PostgreSQL (asyncpg), Redis (redis.asyncio), Neptune (gremlinpython), event bus with 181 topics (Kafka via aiokafka, or AWS SNS/SQS when `EVENT_BROKER=sns_sqs`), S3, Prometheus.

3. **Data Lake Plane** — Medallion architecture (Bronze/Silver/Gold) for raw data persistence, validation, feature materialization, and intelligence output generation. Lake data feeds ML training, graph mutations, and intelligence APIs.

4. **Frontend Plane** — Two React/Vite SPAs backed by the same `@aether/ui` shared component library (`packages/ui`). **Kyber** (`apps/kyber`, port 5174) is the internal operator control surface — investigation, live monitoring, entity management, and approvals. **Aether** (`apps/aether`, port 5175) is the customer-facing web app — account management and commerce. Both apps use PKCE OIDC auth and communicate exclusively with the backend REST API.

### Data Flow

```
Providers (24)  →  /v1/lake/ingest  →  Bronze (raw, immutable)
SDKs            →  /v1/ingest/*     →       ↓
                                       Silver (validated, normalized)
                                            ↓
                                       Gold (features, metrics)
                                            ↓
                              ┌──── Redis (online features)
                              ├──── Neptune (graph edges)
                              ├──── ML Training → Model Registry
                              └──── Intelligence API (risk, analytics, clusters, alerts)
```

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
AetherSDK (index.ts) — v8.12.0
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

SDKs collect raw traffic signals and ship them to the backend, where the `SourceClassifier` (`services/traffic/classifier.py`) classifies every session into source/medium/channel automatically.

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

### Resolution Signals

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

```
SDK Event (with fingerprint + identifiers)
    │
    ▼
Ingestion Service
    ├── IP Enrichment (MaxMind GeoLite2)
    ├── Normalize & validate
    └── Publish SDK_EVENTS_VALIDATED
         │
         ▼
Resolution Consumer (real-time)
    ├── 1. Extract identifiers (anonymousId, userId, email, phone, wallets, fingerprintId, ip_hash)
    ├── 2. Upsert graph vertices (DeviceFingerprint, IPAddress, Location, Email, Phone, Wallet)
    ├── 3. Create/update edges (HAS_FINGERPRINT, SEEN_FROM_IP, HAS_EMAIL, etc.)
    ├── 4. Find candidate profiles (other Users linked to same vertices)
    └── 5. Run deterministic signals
              │
              ├── Match found → AUTO MERGE (confidence = 1.0)
              └── No match → Queue for batch
                               │
                               ▼
                  Batch Resolution Job (hourly)
                    ├── Run probabilistic signals on candidates
                    ├── Compute weighted composite score
                    └── Apply rules engine:
                          ├── >= 0.95 → auto_merge (if configured)
                          ├── >= 0.70 → flag_for_review
                          └── < 0.70  → reject
```

## Backend API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/batch` | POST | Canonical batched raw events (ALL SDKs — web, iOS, Android, RN) |
| `/v1/ingest/events[/batch]` | POST | Deprecated server-to-server connector aliases |
| `/v1/config/sdk/manifest` | GET | SDK remote config (signed manifests + rollouts) |
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
| `/v1/onchain/contracts/{address}` | GET | On-chain contract metadata |
| `/v1/resolution/cluster/{user_id}` | GET | Identity cluster for a user |
| `/v1/resolution/pending` | GET | Pending merge decisions (admin) |
| `/v1/resolution/pending/{id}/approve` | POST | Approve merge |
| `/v1/resolution/pending/{id}/reject` | POST | Reject merge |
| `/v1/resolution/audit/{id}` | GET | Audit trail for a decision |
| `/v1/resolution/config` | GET/PUT | Resolution thresholds |
| `/v1/resolution/batch` | POST | Trigger batch matching job |
| `/v1/agent/deployments` | POST/GET/PATCH | External agent deployment registry (flag-gated, observation-only) |
| `/v1/providers/keys` | POST/GET/DELETE | BYOK key management (encrypted at rest) |
| `/v1/providers/usage` | GET | Per-tenant provider usage stats |
| `/v1/providers/health` | GET | Provider health + circuit breaker states |
| `/v1/providers/test` | POST | Test a provider call |

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

## Model Extraction Defense (v8.12.0)

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
`EXTRACTION_DEFENSE_UNAVAILABLE` instead of silently passing traffic. See
[Model Extraction Defense](MODEL-EXTRACTION-DEFENSE.md) for full documentation.

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
L0, plus `IG_TRUST_SCORING`, `IG_BYTECODE_RISK`, and `IG_RPC_GATEWAY`). The
one exception is the Agentic Commerce control plane
(`COMMERCE_CONTROL_PLANE_ENABLED`), which defaults on. See
`docs/INTELLIGENCE-GRAPH.md` for the full specification, edge schemas, and
rollout guide.

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
| `services/fraud_networks` | `FEATURE_FRAUD_NETWORKS` | `/v1/fraud/networks` |
| `services/flow_trace` | `FEATURE_FLOW_TRACE` | `/v1/flow-trace` |
| `services/risk_overlay` | `FEATURE_RISK_OVERLAYS` | `/v1/risk-overlays` |

These services are fully additive — they add no startup overhead when their flags are disabled. They share the graph client, event producer, and investigation repository with existing services. The `FraudIntelligenceConfig` dataclass in `config/settings.py` owns all five flags and tuning parameters (`alert_risk_threshold`, `max_network_depth`, `max_flow_trace_hops`).

See `docs/AGENT-CONTROLLER.md` for the full specification and `Agent Layer/README.md` for implementation details.
