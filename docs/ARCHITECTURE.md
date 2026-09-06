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
last_synced_commit: "0e967a68"
---
# Aether vNext — Architecture Guide

## Overview

Aether is a **hybrid Python/FastAPI + Node/TypeScript** platform with four operational planes:

1. **SDK Plane** — Thin-client SDKs (Web, iOS, Android, React Native) collect raw events, fingerprints, wallet interactions, and session data. SDKs ship raw data to the backend.

2. **Backend Plane** — Python/FastAPI with 60+ service routers handling ingestion, identity, analytics, ML inference, graph, rewards, lake management, profile intelligence, population omniview, expectation engine, behavioral continuity, RWA intelligence, Web3 coverage, cross-domain TradFi/Web2 intelligence, extraction defense mesh, privacy/policy control plane, **notification intelligence** (`/v1/notifications/intelligence/*` — event-driven multi-channel operator alerts + end-user Slack/Discord/Telegram/Webhook delivery; mobile push (APNs/FCM) carries only a redacted projection — amounts/PII are `[redacted]`, never raw payload), plus the customer-facing productization surface: **registration** (`POST /v1/tenants`), **auth** (`/v1/auth/*` — email+password+OTP signup, Auth0 SSO callback, API-key recovery), **caller profile** (`/v1/me/*` — paginated self-service API keys), **billing** (`/v1/billing/*` — Stripe Checkout + Billing Portal + invoices), **Stripe webhook** (`/v1/admin/billing/stripe/webhook`, signature-verified), **SDK utilities** (`/sdk/identity/resolve` — cross-device identity), and a monthly overage cron task + SLA expiry worker + Dune Analytics scheduled polling worker running in the app lifespan. Continuity and mobile surfaces complete the plane: the **continuation plane** (`/v1/continuations` — durable, CAS-guarded context-handoff tokens, never a whole graph; the operator twin `/v1/kyber/continuations` exposes the same shapes to Kyber workforce sessions via `require_kyber_access`), the **client-sync feed** (`/v1/client-sync` — gapless per-scope catch-up cursor; operators read the same feed scoped to their own identity through `/v1/kyber/client-sync`), and the **mobile gateway** (`/v1/mobile/*` — installation + push-subscription registration, per-install configuration with distribution profiles, and bounded redacted projections over owning services). Infrastructure: PostgreSQL (asyncpg), Redis (redis.asyncio), Neptune (gremlinpython), event bus with 181 topics (Kafka via aiokafka, or AWS SNS/SQS when `EVENT_BROKER=sns_sqs`), S3, Prometheus. In `AETHER_ENV=local` with no broker reachable, the event bus falls back to an in-memory list and the `main.py` lifespan runs `EventProducer.pump_local` to drain published events into the in-process consumer — so the single-process local stack delivers Bronze→Silver projections without a broker (a broker-connected producer is never double-delivered).

3. **Data Lake Plane** — Medallion architecture (Bronze/Silver/Gold) for raw data persistence, validation, feature materialization, and intelligence output generation. Lake data feeds ML training, graph mutations, and intelligence APIs.

4. **Frontend Plane** — Two React/Vite SPAs backed by the same `@aether/ui` shared component library (`packages/ui`). **Kyber** (`apps/kyber`, port 5174) is the internal operator control surface — investigation, live monitoring, entity management, and approvals. **Aether** (`apps/aether`, port 5175) is the customer-facing web app — account management and commerce. Both apps use PKCE OIDC auth and communicate exclusively with the backend REST API. Two **Expo mobile apps** extend the plane — **Aether Mobile** (`apps/aether-mobile`, customer plane) and **Kyber Mobile** (`apps/kyber-mobile`, operator plane, distinct bundle/audience from Aether Mobile) — built on the shared `@aether/mobile-core` (typed SDK: auth/continuation/sync/push over SecureStore PKCE) and `@aether/mobile-ui` (dark theme + typed navigation) packages. The mobile apps are read-only, consuming the mobile gateway's bounded redacted projections; their wire contracts (distribution profiles, install/app-version registration) live in `packages/shared/mobile-config.ts` and `packages/shared/installation.ts`.

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
| `/v1/ingest/events[/batch]` | POST | Deprecated server-to-server connector aliases — converged (WS-B2) onto the canonical `/v1/batch` spine (same validation/consent/scrub/Bronze/idempotency/publish path + `write` auth); retire with HTTP 410 when `AETHER_KILL_DEPRECATED_INGEST_ALIASES=true` |
| `/v1/kyber/ingest/replay/*` | POST/GET | Kyber-operator Bronze-ingestion replay (WS-B4) — re-deliver a tenant's durable Bronze SDK events with original-time preservation; `POST /v1/kyber/ingest/replay/events` dry-runs by default (zero publishes), a real run requires `AETHER_INGESTION_REPLAY_ENABLED` (else HTTP 403); `GET /v1/kyber/ingest/replay/status` reports gate state |
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

## Multi-Model Intelligence Harness (8.12.0)

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
single canonical registry (19 projections, nine of which — `outcome360`,
`economic360`, `infrastructure360`, `communication360`, `risk360`, `fraud360`,
the context-360 time leaf `temporal360`, the context-360 WHO/SET leaf
`population360` and the context-360 WHERE leaf `geographic360` — are now
implemented native providers) and the shared request/context/result contracts
(TS + Python) that every future 360 provider implements against.
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
`/v1/communication360` surface follows the same template. The implemented
providers are registered at boot — `main.py`'s lifespan calls
`dependencies.projection_plane.register_implemented_projection_providers` — so a
projection surface answers live instead of degrading to `provider_unavailable`
(a provider is not live until registered at this mount; the enforcement note is
in the source-of-truth). Exploration surfaces compose over the engine through
projection-backed surface adapters

(`services/exploration/adapters/projection.py`).
The design decision is [ADR-010](decisions/ADR-010-intelligence-projection-plane.md);
the source-of-truth is
[INTELLIGENCE_PROJECTION_ARCHITECTURE.md](source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md).

### Provider transport adapters

Provider SDKs live only behind the harness's provider-neutral `AsyncModelProvider`
contract (`services/model_runtime/provider.py`); orchestrators such as Noesis
never import them. Real transport for the first two providers lives in
`services/model_runtime/adapters/`:

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
`OpenAINoesisPlanProvider` in `services/noesis/provider.py`) now build a
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
under `services/model_runtime/`:

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

## Data Exchange Plane (v8.12.0, flag-gated)

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
owner/admin/viewer) via `services/data_exchange/authz.py`, resolving each
dotted `data_exchange.*` grant to the legacy read/write/admin alias the proxied
seam admits. See `BACKEND-API.md` ("Data Exchange Plane") and
`docs/plans/data-exchange-api.md` for the full contract.

## Universal Provider Runtime (8.12.0)

The Universal Provider Runtime (UPR) makes provider integrations pluggable: a
new provider is a self-contained plugin (manifest + capability adapters +
normalizer + fixtures + registration) that registers at runtime with **zero
core-system edits**. The legacy `BaseConnector` system, `/v1/integrations/
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
| Contract plane | `shared/integration_contracts/{plugin,capabilities,events,normalization,acquisition,health,reconciliation,certification}.py`; `shared/commerce_contracts/{money,order,events}.py` |
| Runtime service | `services/provider_runtime/` — registry, validation (capability honesty), legacy compat plugin, credential broker, raw store, normalization engine, event bridge, connection orchestrator, scheduler, webhook gateway, rate-limit/retry coordinators, reconciliation, health, certification, routes |
| Reference plugin | `services/providers/shopify/` — `shopify.admin.orders_read`, SSRF-safe `shop_domain` allowlist, HMAC webhook verify, order normalizer, incremental pull with page-info cursor |

Data flow is **raw-before-canonical**: `RawProviderRecord`s are persisted
idempotently to `bronze` (`provider_records`, dedup key
`tenant:provider_identity:provider_record_id:schema_version`) before
normalization; canonical `AetherEvent`s are written to `bronze_connectors`
before the event-bus publish (bronze-before-publish, mirroring the comms
pattern). Publish failure never fails ingestion.

Feature gating: all UPR routes are off by default
(`AETHER_PROVIDER_RUNTIME_ENABLED=False`); the operator plane additionally
requires `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED`; `AETHER_PROVIDER_ENTRY_POINTS_ENABLED`
controls `importlib.metadata` entry-point discovery. Legacy paths are
unaffected regardless.

Binding security invariants: credentials only via `credential_service` refs
(never plaintext); the webhook gateway is **fail-closed** — a signature scheme
without a secret denies, and `endpoint_secret` providers require a
constant-time-matching presented token; `X-Aether-Tenant-ID` is a routing hint
only, not auth; connection loads enforce tenant ownership (cross-tenant id →
404); `shop_domain` is allowlisted to `*.myshopify.com` (SSRF gate); errors
carry `safe_message` only; manifest capability claims are verified against
actual adapters at registration and certification.

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

## Universal Asset Registry & Financial Normalization Surface

The financial-normalization program surfaces a canonical financial-registry
trunk on the backend plane. Its authoritative architecture is
[FINANCIAL_NORMALIZATION.md](source-of-truth/FINANCIAL_NORMALIZATION.md); this
subsection is a pointer, not a replacement.

**Universal Asset Registry service domain** (`services/assets/`). Global
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

**Event-time valuation + persistence** (`services/valuation/`). The pure
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

**Reporting-asset-keyed safe rollup (W4a shared seam)** (`services/value/rollups.py`).
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

**Registry → graph reference projector** (`services/assets/graph_projector.py`).
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
| `services/fraud_networks` | `FEATURE_FRAUD_NETWORKS` | `/v1/fraud/networks` |
| `services/flow_trace` | `FEATURE_FLOW_TRACE` | `/v1/flow-trace` |
| `services/risk_overlay` | `FEATURE_RISK_OVERLAYS` | `/v1/risk-overlays` |

These services are fully additive — they add no startup overhead when their flags are disabled. They share the graph client, event producer, and investigation repository with existing services. The `FraudIntelligenceConfig` dataclass in `config/settings.py` owns all five flags and tuning parameters (`alert_risk_threshold`, `max_network_depth`, `max_flow_trace_hops`).

See `docs/AGENT-CONTROLLER.md` for the full specification and `Agent Layer/README.md` for implementation details.
