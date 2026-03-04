# Changelog

All notable changes to the Aether platform are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [5.1.0] — 2026-03-04

### SDK Auto-Update System with OTA Data Modules

Zero-touch SDK updates across all platforms — Web users get the latest bundle on every page load via a CDN auto-loader, and mobile/React Native users receive updated chain registries, DeFi protocol definitions, and wallet classification rules over-the-air without app store releases.

### Added

- **Web CDN Auto-Loader** (`packages/web/src/loader/aether-loader.ts`) — lightweight ~3KB script at a stable URL (`cdn.aether.network/sdk/v5/loader.js`) that dynamically loads the latest SDK bundle with localStorage caching, TTL-based refresh, SHA-256 integrity verification, and offline fallback
- **Web UpdateManager** (`packages/web/src/core/update-manager.ts`) — background manifest fetcher and data module syncer that checks CDN for updated chain registries, protocol definitions, and wallet classification rules without blocking SDK initialization
- **Rollup loader build** (`packages/web/rollup.loader.mjs`) — separate build config producing UMD + ESM loader bundles, <3KB minified+gzipped
- **iOS UpdateManager** (`Aether Mobile SDK/UpdateManager.swift`) — `AetherUpdateManager` singleton with UserDefaults-backed caching, background-thread manifest fetching via `DispatchQueue.global(qos: .utility)`, SHA-256 verification via CommonCrypto, and `NSNotification` for critical update alerts
- **Android UpdateManager** (`Aether Mobile SDK/UpdateManager.kt`) — `AetherUpdateManager` object with SharedPreferences-backed caching, Kotlin coroutines on `Dispatchers.IO`, `MessageDigest` SHA-256 verification, and broadcast intents for critical updates
- **React Native OTA Manager** (`packages/react-native/src/ota/OTAUpdateManager.ts`) — AsyncStorage-backed data module sync with `@aether_dm_` prefix, Web Crypto API for SHA-256 hashing, integrated as fire-and-forget in `AetherProvider`
- **Extracted JSON data modules** (`data-modules/`) — machine-readable JSON for chain registry (30 chains across 7 VMs), protocol registry (55 DeFi protocols), wallet labels (26 known addresses), and wallet classification rules
- **CI/CD Manifest Publisher** (`cicd/aether-cicd/stages/sdk/manifest_publisher.py`) — generates per-platform manifest JSON files (`web`, `ios`, `android`, `react-native`) with version info, data module descriptors (version/URL/SHA-256/size), feature flags, and uploads to S3 CDN with CloudFront invalidation
- **CI/CD Data Module Publisher** (`cicd/aether-cicd/stages/sdk/data_module_publisher.py`) — extracts TypeScript registry data to versioned JSON, uploads to `s3://cdn.aether.network/sdk/data/{module}/{version}.json`, and regenerates platform manifests
- **Data Module Release Workflow** (`cicd/aether-cicd/.github/workflows/data-module-release.yml`) — independent 3-job GitHub Actions workflow (extract → publish → verify) triggered by pushes to `packages/web/src/web3/chains/**`, `packages/web/src/web3/defi/protocol-registry.ts`, or `packages/web/src/web3/wallet/**`

### Changed

- **Web SDK init** (`packages/web/src/index.ts`) — `UpdateManager` auto-starts after `init()` when `autoUpdate.enabled !== false` (default: enabled), registers injectors for all 4 data modules, loads cached modules immediately, and schedules background checks
- **Chain Registry** (`packages/web/src/web3/chains/chain-registry.ts`) — added `setRemoteData()` and `getDataVersion()` exports; `getAllChains()` now returns OTA data when available, falling back to bundled defaults
- **Protocol Registry** (`packages/web/src/web3/defi/protocol-registry.ts`) — added `setRemoteData()` export; `identifyProtocol()`, `getProtocolsByCategory()`, and `getProtocolsOnChain()` now use remote data overlay
- **Wallet Labels** (`packages/web/src/web3/wallet/wallet-labels.ts`) — added `setRemoteData()` export; lookup functions use remote data when available
- **Wallet Classifier** (`packages/web/src/web3/wallet/wallet-classifier.ts`) — added `setRemoteData()` with `ClassificationRules` interface for OTA injection of hardware RDNS and smart wallet RDNS sets
- **iOS SDK** (`Aether Mobile SDK/Aether.swift`) — starts `AetherUpdateManager` after initialization; version bumped to `5.0.0`
- **Android SDK** (`Aether Mobile SDK/Aether.kt`) — starts `AetherUpdateManager` after initialization; `VERSION` bumped to `5.0.0`
- **React Native Provider** (`packages/react-native/src/index.tsx`) — `AetherProvider` now calls `OTAUpdateManager.syncDataModules()` on mount (fire-and-forget)
- **SDK Release Pipeline** (`cicd/aether-cicd/stages/sdk/sdk_release.py`) — added 5 new release steps: Build Loader, Upload Loader (UMD), Upload Loader (ESM), Extract Data Modules, Publish Manifests
- **Rollup config** (`packages/web/rollup.config.mjs`) — version corrected from `4.0.0` to `5.0.0`

### CDN Structure

```
s3://cdn.aether.network/sdk/
  v5/loader.js                    # Stable auto-loader (UMD)
  v5/loader.mjs                   # Stable auto-loader (ESM)
  manifests/{platform}/latest.json
  data/chain-registry/{version}.json + latest.json
  data/protocol-registry/{version}.json + latest.json
  data/wallet-labels/{version}.json + latest.json
  data/wallet-classification/{version}.json + latest.json
```

### Stats

- **28 files changed** — 16 added, 12 modified
- **4,287 lines added**, 15 lines removed
- Commit: [`ec04222`](../../commit/ec04222)

---

## [5.0.0] — 2026-03-04

### Multi-VM Web3 Wallet Tracking with Full DeFi Ecosystem

Major expansion from single-chain EVM support to a 7 VM family, 20+ blockchain, 150+ DeFi protocol tracking engine with cross-chain portfolio aggregation, wallet classification, and a comprehensive DeFi interaction tracking system spanning 15 categories.

### Added

- **7 VM family providers** — EVM, Solana/SVM, Bitcoin, MoveVM/SUI, NEAR, TRON/TVM, and Cosmos wallet provider adapters (`packages/web/src/web3/providers/`)
- **7 chain-specific trackers** — dedicated tracking modules for each VM family with native address validation, transaction parsing, and event emission (`packages/web/src/web3/tracking/`)
- **Unified chain registry** (`packages/web/src/web3/chains/chain-registry.ts`) — 30+ chains across 7 VMs with chain metadata, RPC endpoints, block explorer URLs, and native currency info
- **Chain utilities** (`packages/web/src/web3/chains/chain-utils.ts`) — cross-chain address validation, chain ID resolution, VM family detection
- **EVM chain database** (`packages/web/src/web3/chains/evm-chains.ts`) — detailed registry of 12 EVM networks (Ethereum, Polygon, Arbitrum, Optimism, Base, Avalanche, BSC, zkSync, Linea, Scroll, Blast, Mantle)
- **DeFi protocol registry** (`packages/web/src/web3/defi/protocol-registry.ts`) — 150+ protocols across 15 categories with contract addresses, chain mappings, and protocol metadata
- **15 DeFi category trackers** (`packages/web/src/web3/defi/`) — DEX, lending, staking, yield, perpetuals, options, bridges, governance, insurance, NFT marketplaces, launchpads, payments, restaking, CEX, and router/aggregator tracking
- **Cross-chain portfolio tracker** (`packages/web/src/web3/portfolio/portfolio-tracker.ts`) — aggregated multi-chain portfolio with token balances, DeFi positions, total value, and historical snapshots
- **Wallet classifier** (`packages/web/src/web3/wallet/wallet-classifier.ts`) — classifies wallets as hot, cold, smart contract, exchange, protocol treasury, or multisig based on behavioral heuristics and known address patterns
- **Wallet labels database** (`packages/web/src/web3/wallet/wallet-labels.ts`) — known address labels for exchanges, protocols, and notable entities across all supported chains
- **Backend Web3 service** (`Backend Architecture/services/web3/`) — FastAPI endpoints for Web3 event ingestion, wallet queries, and cross-chain analytics with Pydantic models
- **Data lake Web3 schemas** (`Data Lake Architecture/schemas/web3_events.py`) — medallion-tier table definitions for Web3 event storage
- **Agent chain monitor v2** (`Agent Layer/workers/chain_monitor_v2.py`) — multi-chain block monitoring worker with VM-aware event parsing
- **Playground v5.0 update** — multi-VM wallet simulation with connect/disconnect flows for all 7 VM families, DeFi interaction simulator, portfolio view, and Vite build config

### Changed

- **Web SDK core** (`packages/web/src/index.ts`) — added multi-VM wallet connect/disconnect methods (`connectSVM`, `connectBTC`, `connectSUI`, `connectNEAR`, `connectTRON`, `connectCosmos`), DeFi tracking methods, portfolio aggregation, and wallet classification API
- **Identity manager** (`packages/web/src/core/identity.ts`) — extended to support wallet addresses across all 7 VMs as identity keys
- **Event queue** (`packages/web/src/core/event-queue.ts`) — added Web3-specific event types for wallet, DeFi, and portfolio events
- **SDK types** (`packages/web/src/types.ts`) — expanded with multi-VM config options, DeFi tracking interfaces, portfolio types, and wallet classification types
- **Web3 module** (`packages/web/src/web3/index.ts`) — refactored from single-chain to multi-VM orchestrator managing all 7 provider + tracker pairs

### Demo Environment

- **Demo CI/CD pipeline** (`cicd/aether-cicd/.github/workflows/demo-management.yml`) — 4-action workflow (deploy, teardown, reset, status) for demo environment lifecycle
- **Demo CD stages** (`cicd/aether-cicd/stages/cd/cd_stages.py`) — simplified 3-stage deployment pipeline (deploy → smoke → seed) without canary or progressive rollout
- **Demo data seeding** (`cicd/aether-cicd/scripts/seed_demo_data.py`) — pre-populates demo environment with realistic sample data across all 9 microservices
- **Demo Terraform environment** (`AWS Deployment/aether-aws/terraform/environments/demo/main.tf`) — `aether-demo` AWS account infrastructure
- **Demo branch config** — `demo` branch added to GitFlow with dedicated Slack channel (`#aether-demo`)

### Documentation

- Updated Web SDK README with multi-VM Web3 API reference, DeFi tracking guide, and portfolio aggregation docs
- Updated Mobile SDK README with v5.0 multi-chain wallet methods and consent categories
- Updated React Native README with multi-VM wallet connect methods and Web3 module config
- Updated CI/CD README with demo pipeline stages and data module release workflow
- Updated Playground README with v5.0 Web3 simulation features
- Updated AWS Deployment README with demo environment account
- Updated root README with v5.0 platform overview

### Stats

- **65 files changed** — 51 added, 14 modified
- **8,920 lines added**, 537 lines removed
- Commits: [`daa1825`](../../commit/daa1825), [`692e4d5`](../../commit/692e4d5), [`f8784d3`](../../commit/f8784d3), [`f6ec44b`](../../commit/f6ec44b), [`9f667a3`](../../commit/9f667a3)

---

## [4.0.0] — 2026-03-03

### Production Infrastructure — CI/CD, AWS, and Compliance

Complete production readiness layer: modular CI/CD pipeline with 8 CI stages and 6 CD stages, multi-account AWS deployment with Terraform IaC, and GDPR + SOC 2 compliance framework.

### Added

#### CI/CD Pipeline (`cicd/aether-cicd/`)

- **8-stage CI pipeline** (`stages/ci/ci_stages.py`) — Lint, Type Check, Unit Test, Integration Test, Security Scan, Build, E2E Test, Performance Test with parallel execution of Lint + Security Scan
- **6-stage CD pipeline** (`stages/cd/cd_stages.py`) — Staging Deploy, Staging Smoke, Canary Deploy (5% traffic), Canary Validation, Progressive Rollout (5% → 25% → 50% → 100%), Post-Deploy Verify
- **Quality gate engine** (`quality_gates/gate.py`) — configurable pass/fail/warn evaluation per stage with JSON-exportable results
- **SDK release automation** (`stages/sdk/sdk_release.py`) — multi-platform release for npm, CocoaPods, Maven Central, and SPM with semantic versioning, dry-run mode, and automatic changelogs
- **Pipeline configuration** (`config/pipeline_config.py`) — single source of truth for environments, stages, thresholds, SDK targets, branch config, and notification channels
- **Shared utilities** — `runner.py` (subprocess wrapper), `notifier.py` (Slack/PagerDuty dispatch), `parsers.py` (tool output parsers), `change_detect.py` (monorepo-aware selective CI)
- **GitHub Actions workflows** — `ci.yml` (8-stage CI), `cd.yml` (production CD), `infrastructure.yml` (Terraform plan/apply/drift), `sdk-release.yml` (SDK release automation)
- **Composite action** (`setup-node-python/action.yml`) — reusable Node.js + Python environment setup
- **Terraform module** for ECS task definitions and service configs

#### AWS Deployment (`AWS Deployment/aether-aws/`)

- **Multi-account architecture** — 5 AWS accounts (`aether-dev`, `aether-staging`, `aether-production`, `aether-data`, `aether-security`) with environment-specific Terraform configs
- **17 Terraform modules** — VPC, ECS, RDS, ElastiCache, Neptune, S3, CloudFront, SageMaker, IAM, Monitoring, WAF, Secrets Manager, VPC Endpoints, DynamoDB, MSK, OpenSearch, API Gateway
- **Operational scripts** — capacity planning (`capacity_ops.py`), cost optimization (`cost_ops.py`), disaster recovery (`disaster_recovery.py`), monitoring (`monitoring_ops.py`), network management (`network_ops.py`), security auditing (`security_ops.py`)
- **Shared AWS utilities** — `aws_client.py` (boto3 session management), `notifier.py`, `runner.py`
- **Terraform state** — S3 backend (`aether-terraform-state`) with DynamoDB lock table (`aether-terraform-locks`), daily drift detection at 06:00 UTC

#### GDPR & SOC 2 Compliance (`GDPR & SOC2/aether-compliance/`)

- **GDPR framework** — consent management (`consent_manager.py`), data subject rights engine (`dsr_engine.py`), data protection controls (`data_protection.py`), breach notification handler (`breach_handler.py`), Records of Processing Activities (`ropa_engine.py`)
- **SOC 2 framework** — trust criteria engine covering all 5 TSC categories (`trust_criteria_engine.py`), gap analysis (`gap_analyzer.py`), continuous compliance monitoring (`compliance_monitor.py`)
- **Audit system** — audit trail engine (`audit_engine.py`), periodic access reviews (`access_review.py`)
- **Policy generator** (`policy_generator.py`) — auto-generates compliance policies from configuration
- **Compliance tests** (`tests/compliance_tests.py`) — automated compliance verification

### Stats

- **111 files changed** — all added
- **18,332 lines added**
- Commits: [`5d5583b`](../../commit/5d5583b), [`e15c003`](../../commit/e15c003), [`73044f4`](../../commit/73044f4)

---

## [3.0.0] — 2026-03-03

### Intelligence Layer — Agents, Backend, and ML Models

Full intelligence stack: 10 autonomous agent workers for data discovery and enrichment, FastAPI backend with 10 microservices, and 9 ML models spanning edge inference and server-side prediction.

### Added

#### Agent Layer (`Agent Layer/`)

- **Agent controller** (`agent_controller/controller.py`) — centralized orchestration of all autonomous workers with task scheduling, priority queuing, and health monitoring
- **10 autonomous workers** split across two categories:
  - **Discovery workers** (5) — Web Crawler, API Scanner, Chain Monitor, Competitor Tracker, Social Listener
  - **Enrichment workers** (5) — Entity Resolver, Profile Enricher, Quality Scorer, Semantic Tagger, Temporal Filler
- **Worker registry** (`workers/registry.py`) — dynamic worker registration and lifecycle management
- **Guardrails system** (`guardrails/`) — PII detection model, content safety filters, and output validation
- **Feedback learning** (`feedback/learning.py`) — reinforcement loop for improving worker accuracy over time
- **Celery task queue** (`queue/`) — distributed task execution with Redis/RabbitMQ backend

#### Backend Architecture (`Backend Architecture/aether-backend/`)

- **FastAPI application** (`main.py`) — production-grade ASGI server with middleware stack
- **10 microservices** — Ingestion, Identity, Analytics, ML Serving, Agent, Campaign, Consent, Notification, Admin, API Gateway
- **Shared infrastructure** — authentication (`auth.py`), caching (`cache.py`), event bus (`events.py`), graph database client (`graph.py`), rate limiting (`limiter.py`), structured logging (`logger.py`)
- **Repository layer** (`repositories/repos.py`) — database abstraction for all services
- **Dependency injection** (`dependencies/providers.py`) — FastAPI dependency providers
- **Middleware stack** (`middleware/middleware.py`) — CORS, request logging, error handling, authentication

#### ML Models (`ML Models/aether-ml/`)

- **9 ML models** — edge models (session scoring, engagement prediction, churn risk, content affinity) and server models (campaign attribution, journey prediction, lookalike modeling, lifetime value, anomaly detection)
- **Edge runtime** (`edge/runtime.py`) — lightweight inference engine for on-device models (<5MB, <50ms latency)
- **Model export** (`export/exporter.py`) — ONNX, CoreML, TFLite export pipeline
- **Feature pipeline** (`features/`) — feature registry, streaming feature computation, and preprocessing utilities
- **Training pipelines** (`training/`) — SageMaker integration, hyperparameter optimization, model evaluation
- **Model serving** (`serving/`) — FastAPI prediction API with batch inference, response caching, and A/B model routing
- **Monitoring** (`monitoring/`) — model drift detection, prediction quality alerts, and performance dashboards
- **Full test suite** — unit tests for models/features/serving, integration tests for API and end-to-end serving

### Stats

- **166 files changed** — all added
- **28,501 lines added**
- Commits: [`8a6d247`](../../commit/8a6d247), [`6d8aed6`](../../commit/6d8aed6), [`7394d56`](../../commit/7394d56)

---

## [2.0.0] — 2026-03-03

### Data Pipeline — Event Ingestion and Data Lake

End-to-end data pipeline: real-time event ingestion service with validation, enrichment, and routing, feeding a medallion-architecture data lake with ETL, governance, and analytics capabilities.

### Added

#### Event Ingestion (`Data Ingestion Layer/`)

- **Ingestion service** (`services/ingestion/`) — high-throughput event receiver with schema validation, event enrichment, and downstream routing
- **Event enricher** (`event-enricher.ts`) — real-time enrichment pipeline adding geo, device, and session context to incoming events
- **Event validator** (`services/ingestion/src/validator.ts`) — schema-based event validation with type checking and field constraints
- **Shared packages** — `common` (types, config, utils), `auth` (API key validation), `cache` (Redis caching), `events` (event bus), `logger` (structured logging)
- **Docker deployment** — Dockerfile and docker-compose for containerized ingestion service

#### Data Lake (`Data Lake Architecture/aether-Datalake-backend/`)

- **Medallion architecture** — Bronze (raw), Silver (cleaned), Gold (aggregated) tier processing
- **ETL pipelines** (`etl/pipelines.ts`, `etl/scheduler.ts`) — configurable data transformation pipelines with cron-based scheduling
- **Streaming bridge** (`streaming/`) — real-time data ingestion bridge with backfill manager for historical data reprocessing
- **Data governance** — GDPR governance engine (`governance/gdpr-governance.ts`), schema evolution manager (`governance/schema-evolution.ts`), data lifecycle management (`governance/lifecycle-manager.ts`)
- **Data quality** (`quality/checks.ts`) — automated quality checks with completeness, accuracy, and freshness metrics
- **Analytics engine** (`query/analytics.ts`) — pre-built analytical queries for common reporting patterns
- **Data catalog** (`catalog/catalog.ts`) — metadata catalog with schema discovery and lineage tracking
- **Storage layer** (`storage/s3-storage.ts`) — S3-backed storage with Parquet format and partitioning strategy
- **Schema management** (`schema/`) — DDL generation, table definitions, and type system
- **Monitoring** (`monitoring/monitor.ts`) — pipeline health monitoring with alerting
- **Data compaction** (`compaction/compaction.ts`) — automated small file compaction for query performance
- **Ingestion API** — REST endpoints for batch and single event ingestion with auth middleware, rate limiting, CORS, and health checks
- **Test suite** — unit tests for ingestion, integration tests for pipeline, and test fixture library

### Stats

- **98 files changed** — all added
- **23,881 lines added**
- Commits: [`8509fa5`](../../commit/8509fa5), [`a46225e`](../../commit/a46225e)

---

## [1.0.0] — 2026-03-03

### Platform Foundation — SDKs, Playground, and Monorepo

Initial release of the Aether platform with the Web SDK, React Native bridge, native iOS/Android mobile SDKs, and an interactive playground for testing SDK features.

### Added

#### Web SDK (`packages/web/`)

- **Core SDK** (`src/index.ts`) — `Aether` class with `init()`, `track()`, `screenView()`, `conversion()`, `identify()`, `reset()`, `flush()`, and `destroy()` methods
- **Event queue** (`src/core/event-queue.ts`) — batched event queue with configurable flush intervals, retry logic, and offline buffering
- **Identity manager** (`src/core/identity.ts`) — anonymous ID generation, known-user identification, and identity merging
- **Session manager** (`src/core/session.ts`) — automatic session lifecycle with configurable timeout and cross-tab coordination
- **Consent module** (`src/consent/index.ts`) — per-purpose consent management (analytics, marketing, web3) with persistence
- **Web3 module** (`src/web3/index.ts`) — EVM wallet connect/disconnect and on-chain transaction tracking
- **Edge ML** (`src/ml/edge-ml.ts`) — client-side model inference for session scoring and engagement prediction
- **Experiments** (`src/modules/experiments.ts`) — A/B testing framework with deterministic variant assignment
- **Auto-discovery** (`src/modules/auto-discovery.ts`) — automatic page element discovery for click and form tracking
- **Performance monitoring** (`src/modules/performance.ts`) — Core Web Vitals, page load timing, and resource monitoring
- **Utility library** (`src/utils/index.ts`) — cookie management, localStorage helpers, UUID generation, and event deduplication
- **TypeScript types** (`src/types.ts`) — full type definitions for SDK configuration, events, and public API
- **Rollup build** (`rollup.config.mjs`) — CJS, ESM, and UMD (minified) output with sourcemaps

#### React Native SDK (`packages/react-native/`)

- **Native bridge** (`src/index.tsx`) — unified JS API bridging to native iOS/Android modules
- **React hooks** — `useAether()`, `useIdentity()`, `useExperiment()`, `useScreenTracking()`
- **Context provider** — `AetherProvider` for dependency injection across component tree
- **iOS bridge** — Swift native module (`AetherNativeModule.swift`) with Objective-C declarations
- **Android bridge** — Kotlin native module (`AetherNativeModule.kt`) with React Native package registration (`AetherPackage.kt`)
- **CocoaPods spec** (`aether-react-native.podspec`) — iOS dependency on `AetherSDK ~> 5.0`

#### Mobile SDKs (`Aether Mobile SDK/`)

- **iOS SDK** (`Aether.swift`) — native Swift SDK with event tracking, identity management, wallet tracking, session handling, consent, experiments, and deep link attribution
- **Android SDK** (`Aether.kt`) — native Kotlin SDK with equivalent feature parity to iOS

#### Playground (`playground/`)

- **Interactive testing UI** (`index.html`) — single-page application for exercising all SDK features with real-time event visualization, identity management, wallet simulation, and experiment testing

### Stats

- **60 files changed** — all added
- **12,028 lines added**
- Commits: [`f0a3f42`](../../commit/f0a3f42), [`5ff9724`](../../commit/5ff9724), [`a265d9e`](../../commit/a265d9e)

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| [5.1.0](#510--2026-03-04) | 2026-03-04 | SDK auto-update system, CDN auto-loader, OTA data modules |
| [5.0.0](#500--2026-03-04) | 2026-03-04 | Multi-VM Web3 (7 VMs, 150+ DeFi protocols), demo environment |
| [4.0.0](#400--2026-03-03) | 2026-03-03 | CI/CD pipeline, AWS deployment, GDPR & SOC 2 compliance |
| [3.0.0](#300--2026-03-03) | 2026-03-03 | Agent layer, FastAPI backend, ML models |
| [2.0.0](#200--2026-03-03) | 2026-03-03 | Event ingestion pipeline, data lake architecture |
| [1.0.0](#100--2026-03-03) | 2026-03-03 | Web SDK, React Native SDK, mobile SDKs, playground |
