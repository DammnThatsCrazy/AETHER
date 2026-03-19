# Changelog

## Unreleased

### Fixed

- Restored ML compatibility interfaces so the `ML Models/aether-ml/tests` suite passes again after prior API refactors removed legacy entry points.
- Fixed timezone mismatches in identity feature aggregation that caused tz-aware vs tz-naive subtraction failures.
- Hardened the serving API test/dev path with deterministic fallback models and corrected response-contract mismatches for `/models`, batch prediction errors, and missing feature validation.
- Expanded repository health automation so CI covers both the root test suite and the ML subproject suite.
- Ignored local Gradle caches so Android build metadata does not create false-positive untracked repo changes.

### Changed

- Documented the required `main` branch protection settings so `Repo Health / validate` is enforced instead of advisory only.
- Made `.github/workflows/repo-health.yml` a generated artifact of `scripts/sync_docs.py` and documented how to regenerate the workflow/docs pair after merge conflicts.

## v8.3.1 — Model Extraction Defense Layer (2026-03-18)

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
