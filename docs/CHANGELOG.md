# Changelog

## v8.6.0 — Intelligence Platform Completion (2026-03-25)

### Profile 360
- **NEW**: Holistic user/entity omniview composing all Aether subsystems
- 8 endpoints: full profile, timeline, graph, intelligence, identifiers, provenance, resolver, lake data

### Population Omniview Intelligence
- **NEW**: Macro-to-micro group intelligence (segments, cohorts, clusters, communities)
- 12 endpoints: summary, groups, trends, members, intelligence, compare, entity memberships, explain

### Expectation Engine (Negative-Space Intelligence)
- **NEW**: Detects what SHOULD have happened but did NOT
- 11 endpoints: summary, contradictions, silence, group gaps, entity scan, explain, signals
- 12 signal types including identity contradiction, broken sequence, source silence

### Behavioral Continuity & Friction Layer
- **NEW**: 10 derived signal families from existing data
- Engines: intent residue, wallet friction, identity delta, pre/post continuity, sequence scars, source shadow, reward near-miss, social-chain lag, CEX-DEX transition, behavioral twins
- 5 endpoints: entity scan, signals, trigger, summary, registry

### RWA Intelligence Graph
- **NEW**: Tokenized real-world asset observation, analysis, and scoring
- 14 asset classes, 8 chain environments, 7 policy types, 13 cashflow types, 6 exposure types
- Engines: exposure graph, policy simulation, reserve credibility, redemption pressure
- 14 endpoints: assets CRUD, policies, simulate-transfer, cashflows, exposure, scoring, holders

### Non-Blocking Productization
- Grafana dashboard JSON (10 panels)
- Prometheus alert rules (10 rules across 3 groups)
- WebSocket chain listener with reconnect/backoff/health
- Population snapshot scheduling
- ML drift monitoring automation

### Release Hardening
- Fixed all stale comments/docstrings
- Added 31 endpoints to BACKEND-API.md
- Fixed version drift root cause in bump_version.py
- Reconciled iOS/Android/DataIngestion/DataLake version numbers
- Webhook delivery, export generation, Node.js ingestion explicitly dispositioned

### Totals
- **29 services**, **184 endpoints**, **24 provider connectors**
- **106 tests passing**, CI green

---

## v8.5.0 — Data Lake, Intelligence API, Provider Expansion (2026-03-24)

### Data Lake (Phase 2)
- **NEW**: Bronze/Silver/Gold medallion repositories (`repositories/lake.py`)
- **NEW**: `POST /v1/lake/ingest` — batch ingest with source_tag and idempotency
- **NEW**: `POST /v1/lake/rollback` — rollback by source_tag across tiers
- **NEW**: `GET /v1/lake/audit/{domain}/{tag}` — audit trail per source_tag
- **NEW**: `POST /v1/lake/materialize` — write Gold metrics/features
- **NEW**: `GET /v1/lake/quality/{domain}` — data quality checks
- **NEW**: `GET /v1/lake/status` — record counts per domain per tier
- **NEW**: 6 domain-specific lake instances: market, onchain, social, identity, governance, tradfi

### Feature Materialization (Phase 3)
- **NEW**: `materialize_wallet_features()` — wallet features from Silver → Gold → Redis
- **NEW**: `materialize_protocol_features()` — protocol features with same pipeline

### Graph Mutations (Phase 4)
- **NEW**: Lake-to-graph edge builders: wallet↔protocol, wallet↔social, governance
- **NEW**: `run_full_graph_build()` — orchestrates all edge builders per entity

### ML Model Registry (Phase 5)
- **NEW**: `register_model()` — store metadata with artifact path and metrics
- **NEW**: `promote_model()` — candidate → active (retires previous)
- **NEW**: `rollback_model()` — reactivate most recent retired version
- **NEW**: Model versioning lifecycle: candidate → active → retired

### Intelligence API (Phase 6)
- **NEW**: `GET /v1/intelligence/wallet/{address}/risk` — composite trust score
- **NEW**: `GET /v1/intelligence/protocol/{id}/analytics` — Gold-tier protocol data
- **NEW**: `GET /v1/intelligence/entity/{id}/cluster` — graph identity cluster
- **NEW**: `GET /v1/intelligence/alerts` — anomaly alerts from Gold
- **NEW**: `GET /v1/intelligence/wallet/{address}/profile` — full wallet profile

### Provider Expansion (Phase 1 continued)
- **NEW**: 8 additional provider connectors (total: 24 across 11 categories)
  - DeFiLlama, CoinGecko, Binance, Coinbase (market data)
  - Polymarket, Kalshi (prediction markets)
  - Farcaster, Lens Protocol (Web3 social)
  - ENS, GitHub (identity enrichment)
  - Snapshot (governance)
  - Chainalysis, Nansen (on-chain intelligence, contract-gated)
  - Massive, Databento (TradFi, contract-gated)
- **NEW**: 7 new `ProviderCategory` enum values

### Deployment
- **NEW**: `deploy/staging/bootstrap.sh` — one-command staging deployment
- **NEW**: `deploy/staging/docker-compose.staging.yml` — full staging stack
- **NEW**: `scripts/generate_secrets.py` — production secret generation
- **NEW**: `scripts/validate_infra.py` — infrastructure validation
- **NEW**: Environment gating: ML serving refuses stub models in staging/prod
- **NEW**: Rewards scoring logs DEGRADED warning in non-local heuristic fallback

### Documentation
- **NEW**: `REPO_AUDIT.md`, `IMPLEMENTATION_PLAN.md`, `PROVIDER_MATRIX.md`, `EXECUTION_TRACKER.md`
- **UPDATED**: Root README.md — reflects lake/intelligence/provider architecture
- **UPDATED**: docs/CHANGELOG.md — Phases 2–7 documented
- **UPDATED**: docs/PRODUCTION-READINESS.md — truthful infrastructure status

---

## v8.4.0 — Production Infrastructure + A2H Layer (2026-03-23)

- **NEW**: A2H relationship layer with 4 edge types and event topics
- **NEW**: All infrastructure backends replaced: Redis, PostgreSQL, Neptune, Kafka, Prometheus, eth_account, PyJWT, graphql-core, asyncpg, aiokafka
- **NEW**: Oracle signing/verification with real secp256k1 ECDSA and keccak256
- **NEW**: Admin API key provisioning with Redis auth cache
- **NEW**: Middleware async auth and distributed rate limiting
- **NEW**: PostgreSQL service in docker-compose with health checks
- **NEW**: /v1/metrics Prometheus endpoint, aggregate /v1/health with DB probe
- **NEW**: Subsystem docs (Cache, Events, Database, ML Training)
- **NEW**: SECRET-ROTATION.md runbook, CONTRIBUTING.md
- **MODIFIED**: Edge type count 13 → 19
- **FIXED**: Oracle verifier simulated crypto → real keccak256 + ecrecover
- **FIXED**: Rewards fraud scoring → ML-backed with heuristic fallback
- **FIXED**: All sync/async mismatches in middleware

---

## v8.3.1 — Model Extraction Defense Layer (2026-03-18)

- **FIXED**: Web SDK production hardening — corrected `ConsentState` fallback defaults, fixed isolated-module loader exports, and added regression coverage for offline cached-loader recovery plus concurrent-load deduplication
- **FIXED**: Test harness resilience — backend async integration tests now auto-run under AnyIO when `pytest-asyncio` is not installed

- **NEW**: `security/model_extraction_defense/` — modular defense layer against model extraction and knowledge distillation attacks
- **NEW**: Query rate limiter with dual-axis sliding window (per-API-key + per-IP), three time windows each
- **NEW**: Query pattern detector — detects systematic feature sweeps, input similarity clustering, uniform random probing, bot-like timing
- **NEW**: Output perturbation layer — logit noise, top-k clipping, entropy smoothing, precision rounding; scales with risk score
- **NEW**: Model watermarking — HMAC-based probabilistic bias embedding, verifiable across many queries for forensic identification
- **NEW**: Canary input detector — secret-seed trap inputs with lazy auto-init from observed feature dimensionality
- **NEW**: Extraction risk scorer — EMA-smoothed aggregate score driving response degradation across 4 tiers
- **NEW**: Defense metrics — thread-safe counters with Prometheus exposition format export
- **NEW**: Background cleanup task — daemon thread, asyncio coroutine, and Celery beat modes
- **NEW**: Admin CLI — watermark verification, canary generation, metrics inspection
- **NEW**: `ModelExtractionDefenseConfig` in backend settings with 16 env vars and production validation
- **MODIFIED**: ML serving API — all 8 prediction endpoints + batch endpoint wrapped with defense middleware
- **MODIFIED**: Backend middleware — extraction defense checks on `/v1/ml/predict` routes
- **13 new files**, **4 modified files** — gated behind `ENABLE_EXTRACTION_DEFENSE=false` (default off)

---

## v8.3.0 — Provider Gateway: BYOK, Failover & Usage Metering (2026-03-09)

- **NEW**: `shared/providers/` module — unified abstraction layer for all third-party provider calls (blockchain RPC, block explorers, social APIs, analytics data)
- **NEW**: BYOK (Bring Your Own Key) — tenants store encrypted API keys via `POST /v1/providers/keys`, routed automatically at request time
- **NEW**: Automatic failover with circuit breaker integration — tenant BYOK → system default → fallback providers → `ServiceUnavailableError`
- **NEW**: Per-tenant, per-provider usage metering — request counts, latency, success rates, method-level breakdown
- **NEW**: 8 admin API endpoints under `/v1/providers/` — key CRUD, usage stats, health monitoring, provider testing
- **NEW**: 9 concrete provider adapters — QuickNode, Alchemy, Infura, GenericRPC, Etherscan, Moralis, Twitter, Reddit, Dune Analytics
- **NEW**: `AdaptiveRouter` composes with existing `ErrorRegistry` circuit breakers — provider failures auto-appear in `/v1/diagnostics/circuit-breakers`
- **NEW**: `ProviderGatewayConfig` with feature flag (`PROVIDER_GATEWAY_ENABLED=false` default) — zero impact until activated
- **MODIFIED**: `RPCGateway` delegates through Provider Gateway when enabled, falls back to direct QuickNode on failure
- **10 new files**, **4 modified files** — fully backwards compatible
- Backend service count: 20 → 21 (18 core + 3 IG)

---

## v8.2.0 — Automatic Traffic Source Detection (2026-03-07)

- **NEW**: Server-side `SourceClassifier` (`services/traffic/classifier.py`) with O(1) domain lookup tables — 40+ social platforms, 17+ search engines, 14 email providers, 12 ad platform click IDs
- **NEW**: Priority classification chain: Click IDs (confidence 1.0) → UTM params (0.95) → Referrer domain (0.9) → Direct (0.5)
- **Web SDK**: Added `referrerDomain` extraction and `sessionStorage` persistence for SPA navigation
- **iOS SDK**: Expanded click ID capture from 2 → 12, expanded `CampaignInfo` with content/term/clickIds/referrerDomain, wired into `buildContext()`
- **Android SDK**: Expanded click ID capture from 3 → 12, added `campaignContext` JSONObject wired into `buildContext()`
- **Backend**: `POST /v1/track/traffic-source` now auto-classifies raw signals before storage — `traffic_type` no longer arrives as `"unknown"`
- **9 files changed**, ~277 lines added, zero classification logic in any SDK

---

## v8.1.0 — Security Hardening & Diagnostics (2026-03-07)

- **51 issues remediated** — 5 critical, 18 high, 18 medium, 10 low
- **NEW**: Diagnostics service (`/v1/diagnostics/`) — centralized error tracking with 6 admin endpoints
- **NEW**: `ErrorRegistry` — SHA-256 error fingerprinting, 13 categories, 5 severity levels, auto-classification
- **NEW**: `CircuitBreaker` — per-operation failure tracking (5 failures → open, 30s recovery)
- **FIXED**: Race condition in x402 economic graph, hardcoded JWT secret, API key stubs, unprotected IG endpoints, unlinked audit engine
- **FIXED**: RPC method injection, x402 header parsing, unauthenticated fraud routes, cross-tenant data leakage, sendBeacon API key leak
- **26 files changed** — 22 modified, 4 new

---

## v8.0.0 — Unified On-Chain Intelligence Graph (2026-03-06)

- **NEW**: 8-layer architecture (L0 On-Chain Actions through L7 Compliance) for human-to-human, human-to-agent, and agent-to-agent interactions
- **NEW**: 3 feature-flagged services — Commerce (L3a), On-Chain (L0), x402 Interceptor (L3b)
- **NEW**: 6 new graph node types, 13 new edge types layered onto existing Identity Graph
- **NEW**: Trust Score composite (weighted blend of existing ML models), Bytecode Risk scorer (rule-based)
- **NEW**: 2 new consent purposes (`agent`, `commerce`), DSR cascade extended to new vertex types
- **NEW**: Agent lifecycle tracking with decision records, ground truth feedback, confidence delta
- All layers disabled by default — progressive activation via `IntelligenceGraphConfig` feature flags

---

## v7.0.0 — Thin-Client Architecture + Identity Resolution (2026-03-05)

### Architecture

- **BREAKING**: Migrated all SDKs to "Sense and Ship" thin-client architecture
- All processing, ML inference, and classification offloaded to Aether backend
- SDK now collects raw data and ships via batched HTTP — zero client-side computation
- Server config fetched at init via `GET /v1/config` (replaces OTA update system)

### Identity Resolution

- **NEW**: Cross-device identity resolution — deterministic + probabilistic matching
- **NEW**: Device fingerprinting across all platforms (Web, iOS, Android, React Native)
- **NEW**: Identity graph with 7 new vertex types (DeviceFingerprint, IPAddress, Location, Email, Phone, Wallet, IdentityCluster)
- **NEW**: 5 deterministic signals (userId, email, phone, wallet, OAuth) — auto-merge at confidence 1.0
- **NEW**: 5 probabilistic signals (fingerprint similarity, graph proximity, IP clustering, behavioral similarity, location proximity) — weighted composite scoring
- **NEW**: Resolution rules engine with configurable thresholds (auto-merge >= 0.95, review >= 0.70, reject < 0.70)
- **NEW**: Admin review workflow for flagged merges (`/v1/resolution/pending`)
- **NEW**: Full audit trail for every resolution decision
- **NEW**: Safety mechanisms — max cluster size (50), 24-hour cooldown, fraud gate, undo capability
- **NEW**: IP enrichment via MaxMind GeoLite2 (geolocation, ASN, VPN/proxy detection)
- **NEW**: 7 event topics for resolution lifecycle (evaluated, auto_merged, flagged, approved, rejected, fingerprint.observed, ip.observed)

### Web SDK

**Removed modules:**
- `edge-ml.ts` — ML inference (intent prediction, bot detection, session scoring)
- `experiments.ts` — A/B testing (use feature flags instead)
- `performance.ts` — Web Vitals (use Sentry/DataDog)
- `feedback.ts` — Survey rendering (backend-rendered iframe)
- `update-manager.ts` — OTA data module system (backend serves config)

**Removed Web3 sub-modules:**
- `protocol-registry.ts` — Backend resolves protocols
- `dex-tracker.ts` — Backend classifies swaps
- `generic-defi-tracker.ts` — Backend handles DeFi categorization
- `wallet-classifier.ts` — Backend labels wallets
- `wallet-labels.ts` — Backend provides labels
- `portfolio-tracker.ts` — Backend aggregates portfolios
- `chain-registry.ts`, `evm-chains.ts`, `chain-utils.ts` — Backend resolves chains

**New modules:**
- `fingerprint.ts` — Device fingerprint collector (17 browser signals → SHA-256)

**Slimmed modules:**
- `ecommerce.ts` (290 → ~60 LOC) — 5-method thin stub
- `heatmaps.ts` (392 → ~80 LOC) — Raw coordinate emitter
- `funnels.ts` (357 → ~50 LOC) — Event tagger from server config
- `form-analytics.ts` (404 → ~80 LOC) — Field event emitter
- `feature-flags.ts` (394 → ~80 LOC) — Cache-only layer
- `auto-discovery.ts` (347 → ~60 LOC) — Minimal click tracker
- `traffic-source-tracker.ts` (431 → ~60 LOC) — Raw UTM/referrer shipper
- `semantic-context.ts` (406 → ~60 LOC) — Tier 1 only
- `reward-client.ts` (1532 → ~80 LOC) — Thin API client
- `web3/index.ts` (470 → ~150 LOC) — Simplified orchestrator
- All 7 VM trackers slimmed to ~40-60 LOC each

**Updated types.ts:**
- Removed: `IntentVector`, `BotScore`, `BehaviorSignature`, `SessionScore`
- Removed: `ExperimentConfig`, `ExperimentAssignment`, `ExperimentInterface`
- Removed: `PerformanceEvent` and ML/processing callback types
- Added: `FingerprintComponents` interface
- Added: `fingerprint` field in `EventContext`
- Added: `email`, `phone`, `oauthProvider`, `oauthSubject` in `IdentityData`

**Net result: ~12,700 LOC → ~5,200 LOC (59% reduction)**

### iOS SDK

- Slimmed `buildContext()` — sends only `{os, osVersion, locale, timezone}`, backend derives rest from headers
- Added device fingerprinting via CryptoKit SHA-256
- Added wallet tracking: `walletConnected()`, `walletDisconnected()`, `walletTransaction()`
- Added consent management: `grantConsent()`, `revokeConsent()`, `getConsentState()`
- Added ecommerce stubs: `trackProductView()`, `trackAddToCart()`, `trackPurchase()`
- Added feature flags: `isFeatureEnabled()`, `getFeatureValue()`
- Added `fetchConfig()` — loads server config on init
- Version bumped to 7.0.0

### Android SDK

- Slimmed `buildContext()` — sends only `{os, osVersion, locale, timezone}`, backend derives rest from headers
- Added device fingerprinting via MessageDigest SHA-256
- Added wallet tracking: `walletConnected()`, `walletDisconnected()`, `walletTransaction()`
- Added consent management: `grantConsent()`, `revokeConsent()`, `getConsentState()`
- Added ecommerce stubs: `trackProductView()`, `trackAddToCart()`, `trackPurchase()`
- Added feature flags: `isFeatureEnabled()`, `getFeatureValue()`
- Added `fetchConfig()` — loads server config on init
- Version bumped to 7.0.0

### React Native SDK

- **Deleted**: `OTAUpdateManager.ts` (361 LOC) — replaced by `GET /v1/config`
- **Slimmed**: `SemanticContext.ts` (238 → 69 LOC) — Tier 1 only, no sentiment/journey
- **Slimmed**: `Feedback.ts` (89 → 52 LOC) — removed survey factory methods
- Updated `AetherProvider` to fetch server config on init
- Added `getFingerprint()` — native bridge to device fingerprint
- **Net result: 1,064 LOC → 497 LOC (53% reduction)**

### Backend

- Added identity resolution service with 9 new files (engine, signals, rules, repository, routes, consumer, tasks, models)
- Added 8 new API endpoints under `/v1/resolution/*`
- Added IP enrichment to ingestion pipeline (MaxMind GeoLite2)
- Added 7 new graph vertex types and 9 new edge types
- Added 7 new event topics for resolution lifecycle

---

## v6.1.0 — Web2 Analytics & Multi-Chain Rewards (2025)

- Added Web2 analytics modules (ecommerce, feature flags, feedback, heatmaps, funnels, form analytics)
- Added multi-chain reward automation with oracle proofs
- Added architecture diagrams and documentation

## v6.0.0 — SDK Auto-Update & OTA Data Modules (2025)

- Added OTA update system with data module sync
- Added SHA-256 verification for downloaded modules
- Added CDN loader with intelligent caching

## v5.0.0 — Web3 Multi-VM Expansion (2025)

- Added 7 VM family support: EVM, SVM, Bitcoin, Move, NEAR, TRON, Cosmos
- Added DeFi protocol tracking across 15 categories
- Added portfolio aggregation and wallet classification

## v4.0.0 — GDPR & SOC2 Compliance (2025)

- Added consent management framework
- Added privacy-first data collection with consent gates
- Added semantic context with tiered data collection

## v3.0.0 — Agent Layer & Backend Services (2024)

- Added backend architecture with FastAPI services
- Added oracle signer for multi-chain proof generation
- Added fraud detection and attribution services

## v2.0.0 — Data Infrastructure (2024)

- Added data ingestion pipeline
- Added data lake with ETL processing
- Added ML model training infrastructure

## v1.0.0 — Initial Release (2024)

- Core analytics SDK for Web, iOS, Android
- Event tracking, identity management, session tracking
- Basic ecommerce and conversion tracking
