# Changelog

## v7.0.0 — Thin-Client Architecture (2026-03-05)

### Architecture

- **BREAKING**: Migrated all SDKs to "Sense and Ship" thin-client architecture
- All processing, ML inference, and classification offloaded to Aether backend
- SDK now collects raw data and ships via batched HTTP — zero client-side computation
- Server config fetched at init via `GET /v1/config` (replaces OTA update system)

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

**Slimmed modules:**
- `ecommerce.ts` (290 -> ~60 LOC) — 5-method thin stub
- `heatmaps.ts` (392 -> ~80 LOC) — Raw coordinate emitter
- `funnels.ts` (357 -> ~50 LOC) — Event tagger from server config
- `form-analytics.ts` (404 -> ~80 LOC) — Field event emitter
- `feature-flags.ts` (394 -> ~80 LOC) — Cache-only layer
- `auto-discovery.ts` (347 -> ~60 LOC) — Minimal click tracker
- `traffic-source-tracker.ts` (431 -> ~60 LOC) — Raw UTM/referrer shipper
- `semantic-context.ts` (406 -> ~60 LOC) — Tier 1 only
- `reward-client.ts` (1532 -> ~80 LOC) — Thin API client
- `web3/index.ts` (470 -> ~150 LOC) — Simplified orchestrator
- All 7 VM trackers slimmed to ~40-60 LOC each

**Updated types.ts:**
- Removed: `IntentVector`, `BotScore`, `BehaviorSignature`, `SessionScore`
- Removed: `ExperimentConfig`, `ExperimentAssignment`, `ExperimentInterface`
- Removed: `PerformanceEvent` and ML/processing callback types
- Simplified: `ModuleConfig`, `AdvancedConfig`, `PrivacyConfig`

**Net result: ~12,700 LOC -> ~5,200 LOC (59% reduction)**

### iOS SDK

- Slimmed `buildContext()` — sends only `{os, osVersion, locale, timezone}`, backend derives rest from headers
- Added wallet tracking: `walletConnected()`, `walletDisconnected()`, `walletTransaction()`
- Added consent management: `grantConsent()`, `revokeConsent()`, `getConsentState()`
- Added ecommerce stubs: `trackProductView()`, `trackAddToCart()`, `trackPurchase()`
- Added feature flags: `isFeatureEnabled()`, `getFeatureValue()`
- Added `fetchConfig()` — loads server config on init
- Version bumped to 7.0.0

### Android SDK

- Slimmed `buildContext()` — sends only `{os, osVersion, locale, timezone}`, backend derives rest from headers
- Added wallet tracking: `walletConnected()`, `walletDisconnected()`, `walletTransaction()`
- Added consent management: `grantConsent()`, `revokeConsent()`, `getConsentState()`
- Added ecommerce stubs: `trackProductView()`, `trackAddToCart()`, `trackPurchase()`
- Added feature flags: `isFeatureEnabled()`, `getFeatureValue()`
- Added `fetchConfig()` — loads server config on init
- Version bumped to 7.0.0

### React Native SDK

- **Deleted**: `OTAUpdateManager.ts` (361 LOC) — replaced by `GET /v1/config`
- **Slimmed**: `SemanticContext.ts` (238 -> 69 LOC) — Tier 1 only, no sentiment/journey
- **Slimmed**: `Feedback.ts` (89 -> 52 LOC) — removed survey factory methods
- Updated `AetherProvider` to fetch server config on init
- **Net result: 1,064 LOC -> 497 LOC (53% reduction)**

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
