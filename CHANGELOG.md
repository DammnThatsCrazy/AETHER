# Changelog

All notable changes to the Aether platform are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [vNext] — Unreleased

### Added — Agent Layer: Multi-Controller Internal Autonomy Architecture
- **Governance Controller** — top-level policy authority with budget ceilings, kill switch, audit invariants, conflict arbitration, and autonomy boundaries
- **KIRA Controller** — top orchestration controller coordinating across all domain controllers with plan supervision, synthesis, and replan/escalation
- **Intake Controller** — objective intake with dedupe, normalization, admission control, and severity classification
- **Discovery Controller** — source-facing evidence collection orchestration with team routing and fallback
- **Enrichment Controller** — candidate fact generation, entity resolution/reconciliation orchestration
- **Verification Controller** — evidence sufficiency, provenance, schema, consistency, and quality scoring checks
- **Commit Controller** — mutation staging, review batch building, internal approval queue, and graph write through explicit interfaces
- **Recovery Controller** — retry/fallback, compensation, rollback orchestration, stale objective repair, checkpoint restoration
- **BOLT Controller** — objective continuity across sessions, checkpoint records, brief records, operator summaries, handoff state, run history, session restore, internal feed/timeline
- **TRIGGER Controller** — unified scheduling/wake engine with cron, graph-state, webhook, queue-condition, stale-entity, failed-retry, and manual wakeups; missed-fire handling; orphan cleanup
- **LOOP runtime** — aggressive shared continuation behavior across KIRA and domain controllers with policy/budget/stopping enforcement
- **UNITS identity layer** — fully functional but optional identity + mascot system for controllers, teams, and workers
- **Durable objective runtime** — Objective, Plan, PlanStep lifecycle management replacing flat task-only model
- **Evidence & verification pipeline** — EvidenceRecord, CandidateFact, VerificationResult data models
- **Staged mutation review system** — StagedMutation, ReviewBatch with 5-class mutation classification; all classes require human approval
- **Checkpointing & briefing** — CheckpointRecord, BriefRecord for continuity and operator communication
- **CLI dashboard** — ASCII dashboard with Feed/Timeline, Kanban/Objective Board, and Controller Health Console views
- **Internal Ops Service** — operator-facing service for objective submission, review management, and health monitoring
- **Review Queue Service** — review workflow surface for human approval and commit coordination
- **Graph staging interface** — explicit agent-layer interface for staging and committing approved mutations
- **Internal event bus** — synchronous event channel for agent-layer events (objective, plan, step, mutation, trigger events)
- **Policy guardrails** — controller-aware policy enforcement extending existing guardrails
- **Controller Hub** — single assembly point wiring the full Governance > KIRA > Domain Controller hierarchy
- **Worker teams** — bounded execution groups (discovery, enrichment, verification, recovery, commit) under domain controllers
- **Queue routing** — controller-to-queue mapping for the multi-controller architecture

### Changed
- Agent Layer architecture: flat single-controller → multi-controller internal autonomy hierarchy
- Task execution: task-only → objective + plan runtime with durable state
- Routing: confidence-only → verification + staging + review batches
- Scheduling: simple hooks → TRIGGER unified wake engine
- Continuity: ad-hoc → BOLT checkpoint and briefing system
- Worker pool: flat pool → controller + team-aware execution fabric
- Internal UI: none → real CLI dashboard and ops console

### Preserved
- Queue backends (in-memory heapq for dev, Celery + Redis for production)
- Worker lifecycle guardrails (kill switch, rate limiter, cost monitor, PII detector, confidence gate, audit logger)
- Specialist workers (10 workers: 5 discovery + 5 enrichment) as the execution fabric
- Feedback learning loop (EMA threshold tuner, priority booster)
- Safety-first posture

---

## [v8.7.0] — 2026-03-25

### Added
- **Web3 Coverage Service**: Registry-first intelligence with 31 chains, 40+ protocols, 24 apps, classification engine, migration tracking (29 endpoints)
- **Cross-Domain TradFi/Web2 Service**: Unified business/financial graph with accounts, instruments, trades, compliance, identity fusion (34 endpoints)
- **Privacy Control Plane**: 7-tier data classification, RBAC+ABAC+purpose access control, field-level masking, DSAR workflows, ML training eligibility, log redaction
- 18+16 new graph vertex types (52 total), 27+30 new edge types (90+ total)

### Changed
- Platform: 31 services, 246 endpoints (up from 29/184 in v8.6.0)

---

## [v8.6.0] — 2026-03-25

### Added

- Profile 360 service — 8 endpoints for holistic entity omniview
- Population Omniview — 12 endpoints for macro-to-micro group intelligence
- Expectation Engine — 11 endpoints for negative-space intelligence
- Behavioral Continuity & Friction — 5 endpoints, 10 signal families
- RWA Intelligence Graph — 14 endpoints for tokenized asset intelligence
- Grafana dashboards, Prometheus alert rules, WebSocket hardening
- Population snapshot scheduling, ML drift monitoring

### Changed

- Service count: 24 → 29
- Endpoint count: 165 → 184
- All docs, READMEs, version headers updated to v8.6.0

---

## [v8.5.0] — 2026-03-24

### Added

- Data Lake medallion architecture (Bronze/Silver/Gold) with 6 domain repositories
- 7 new lake API endpoints: ingest, rollback, audit, materialize, quality, status
- Intelligence API: wallet risk, protocol analytics, identity clusters, anomaly alerts, wallet profiles
- Feature materialization from Silver → Gold → Redis online serving
- Lake-to-graph edge builders: wallet↔protocol, wallet↔social, governance
- Model artifact registry with versioning (candidate → active → retired) and rollback
- 8 new provider connectors (total: 24 across 11 categories)
- Staging deployment package with one-command bootstrap
- Environment gating for ML serving and rewards heuristic fallback

---

## [v8.4.0] — 2026-03-23

### Added

- **A2H (Agent-to-Human) relationship layer** — fourth relationship category in the Intelligence Graph
- 4 new edge types: `NOTIFIES`, `RECOMMENDS`, `DELIVERS_TO`, `ESCALATES_TO`
- 4 new event topics for A2H interactions
- `POST /v1/agent/{id}/a2h` endpoint
- **Production infrastructure backends** for all 15+ subsystems:
  - CacheClient → Redis via redis.asyncio
  - GraphClient → Neptune via gremlinpython
  - EventProducer/Consumer → Kafka via aiokafka
  - Repositories → PostgreSQL via asyncpg
  - APIKeyValidator → async Redis lookup with SHA-256 hashed keys
  - BYOKKeyVault → Fernet AES encryption via cryptography
  - TokenBucketLimiter → Redis INCR+EXPIRE distributed limiting
  - MetricsCollector → Prometheus Counter/Histogram
  - 9 Provider Adapters → real httpx HTTP calls
  - GraphQL parser → graphql-core AST
  - Export worker → Celery offload
  - JWT Handler → PyJWT library
- **Oracle signing with real crypto**: secp256k1 ECDSA via eth_account, keccak256 hashing, ecrecover verification
- **Admin API key provisioning**: `POST /v1/admin/tenants/{id}/api-keys` with Redis auth cache registration
- **Middleware async auth**: validate_async() for Redis key lookup, check_async() for distributed rate limiting
- **Health endpoint**: probes database, cache, graph, and event bus
- **Prometheus /v1/metrics endpoint**
- `docker-compose.yml`: PostgreSQL service with health checks and all required env vars
- `docs/SECRET-ROTATION.md`: rotation runbook for all production secrets
- `CONTRIBUTING.md`: development setup and contribution guide
- Subsystem docs: Cache/Redis, Events/Kafka, PostgreSQL/schema, ML training guide

### Fixed

- Oracle verifier: replaced simulated SHA-256/HMAC with real keccak256 + ecrecover
- MultiChain signer: chain-specific hashing (keccak256 for EVM/TVM, SHA3-256 for MoveVM, SHA-256d for Bitcoin)
- Rewards scoring: ML-backed fraud scoring with heuristic fallback (was random-based)
- Middleware: sync-to-async migration for auth and rate limiting
- Tenant isolation: identity graph, analytics events, resolution clusters, x402 endpoints
- Missing CacheKey.custom() method, null guard in analytics
- CI: ML test execution, version header alignment, pytest markers

- Restored ML compatibility interfaces so the `ML Models/aether-ml/tests` suite passes again after prior API refactors removed legacy entry points.
- Fixed timezone mismatches in identity feature aggregation that caused tz-aware vs tz-naive subtraction failures.
- Hardened the serving API test/dev path with deterministic fallback models and corrected response-contract mismatches for `/models`, batch prediction errors, and missing feature validation.
- Expanded repository health automation so CI covers both the root test suite and the ML subproject suite.
- Ignored local Gradle caches so Android developer artifacts no longer show up as untracked repository changes.

### Changed

- Documented branch-protection requirements in the generated automation policy so GitHub's unprotected-`main` warning has a repeatable remediation path and the `Repo Health / validate` check can be enforced.
- Made `.github/workflows/repo-health.yml` a generated artifact of `scripts/sync_docs.py` and documented a merge-conflict recovery flow so concurrent edits to repo-health automation are resolved from one source of truth.

## [8.3.1] — 2026-03-18

### Model Extraction Defense Layer

Modular defense layer protecting ML serving endpoints against model extraction and knowledge distillation attacks. Audited the inference pipeline and found critical vulnerability — 9 models exposed with exact probability outputs, no perturbation, no watermarking, and no query anomaly detection.

### Added

- **Query Rate Limiter** (`security/model_extraction_defense/rate_limiter.py`) — dual-axis sliding window rate limiting (per-API-key + per-IP), three time windows each (minute/hour/day), batch cost accounting
- **Query Pattern Detector** (`security/model_extraction_defense/pattern_detector.py`) — detects systematic feature sweeps, input similarity clustering, uniform random probing, and bot-like timing regularity
- **Output Perturbation Layer** (`security/model_extraction_defense/output_perturbation.py`) — logit noise injection, top-k probability clipping, entropy smoothing, precision rounding; noise scales with extraction risk score
- **Model Watermarking** (`security/model_extraction_defense/watermark.py`) — HMAC-based probabilistic bias embedding in outputs; statistically detectable across many queries for forensic identification of extracted models
- **Canary Input Detector** (`security/model_extraction_defense/canary_detector.py`) — secret-seed-generated trap inputs with lazy initialization from observed feature dimensionality; triggers cooldown on detection
- **Extraction Risk Scorer** (`security/model_extraction_defense/risk_scorer.py`) — EMA-smoothed aggregate score combining velocity, pattern anomaly, similarity, and entropy signals; drives response degradation across four tiers (normal/elevated/high/critical)
- **Defense Metrics** (`security/model_extraction_defense/metrics.py`) — thread-safe metrics collector with Prometheus exposition format export; tracks requests, blocks, canary triggers, risk distribution
- **Background Cleanup** (`security/model_extraction_defense/cleanup.py`) — daemon thread, asyncio coroutine, and Celery beat task modes for periodic expiration of in-memory state
- **Admin CLI** (`security/model_extraction_defense/admin_cli.py`) — watermark verification against suspect models, canary generation, metrics inspection
- **`ModelExtractionDefenseConfig`** in `Backend Architecture/aether-backend/config/settings.py` — 16 environment variables with production validation for secret keys
- **`EXTRACTION_DEFENSE_AUDIT.md`** — comprehensive audit report with threat model covering 4 attack scenarios

### Changed

- **ML Serving API** (`ML Models/aether-ml/serving/src/api.py`) — all 8 prediction endpoints + batch endpoint now wrapped with extraction defense middleware and post-response perturbation
- **Backend Middleware** (`Backend Architecture/aether-backend/middleware/middleware.py`) — extraction defense checks integrated into request lifecycle for `/v1/ml/predict` routes

### Stats

- **13 new files**, **4 modified files** — 4,500+ lines added
- All protections gated behind `ENABLE_EXTRACTION_DEFENSE=false` (default off)
- Zero latency impact when disabled; <2ms overhead when enabled

---

## [8.3.0] — 2026-03-10

### Provider Gateway: BYOK, Failover & Usage Metering

Unified abstraction layer for all third-party provider calls. Tenants can bring their own API keys (encrypted at rest), the system automatically fails over between providers using circuit breakers, and every call is metered per-tenant for billing and monitoring.

### Added

- **Provider Gateway** (`shared/providers/`) — multi-provider abstraction with 4 categories: blockchain RPC (QuickNode, Alchemy, Infura, custom), block explorer (Etherscan, Moralis), social API (Twitter, Reddit), analytics data (Dune Analytics)
- **BYOK (Bring Your Own Key)** — tenants store encrypted API keys via `POST /v1/providers/keys`; keys are automatically used for routing at request time with Fernet encryption at rest
- **Automatic failover** — `AdaptiveRouter` implements priority chain: tenant BYOK → system default → fallback provider(s) → `ServiceUnavailableError`. Composes with existing `ErrorRegistry` circuit breakers
- **Usage metering** — `UsageMeter` tracks per-tenant, per-provider call counts, latency, success rates, and method-level breakdown
- **Admin API** — 8 endpoints under `/v1/providers/`: key CRUD, usage stats, usage summary, health monitoring, category listing, and provider testing
- **9 concrete provider adapters** — QuickNodeProvider, AlchemyProvider, InfuraProvider, GenericRPCProvider, EtherscanProvider, MoralisProvider, TwitterProvider, RedditProvider, DuneAnalyticsProvider
- **`ProviderGatewayConfig`** in `config/settings.py` — 12 environment variables with feature flag (`PROVIDER_GATEWAY_ENABLED=false` default)
- **`ProviderGateway` facade** in `dependencies/providers.py` — owns key vault, registry, meter, and router lifecycle

### Changed

- **`RPCGateway`** — delegates through Provider Gateway when enabled; falls back to direct QuickNode on failure (fully backwards compatible)
- **`main.py`** — mounts providers router (service count 17 → 18 core, 21 total with IG)
- **Backend Architecture README** — updated service count, diagrams, endpoint listing, project structure, and configuration reference

### Stats

- **10 new files**, **4 modified files** — 1,720 lines added
- Backend service count: 20 → 21 (18 core + 3 IG)

---

## [8.2.0] — 2026-03-07

### Automatic Traffic Source Detection

Server-side traffic source classification with full-stack signal capture. SDKs collect raw referrer, UTM params, and click IDs — the backend classifies every session into source/medium/channel automatically. No pre-created links required.

### Added

- **SourceClassifier** (`services/traffic/classifier.py`) — stateless, pure-function classifier with O(1) domain lookup tables covering 40+ social platforms, 17+ search engines, 14 email providers, and 12 ad platform click IDs. Uses a priority chain: Click IDs (confidence 1.0) → UTM params (0.95) → Referrer domain (0.9) → Direct (0.5). Email domains checked before search to prevent `mail.google.com` misclassification
- **Web SDK: `referrerDomain` field** — `TrafficSourceData` now includes a parsed `referrerDomain` (with `www.` stripped) for backend classification
- **Web SDK: SPA session persistence** — `sessionStorage`-based caching ensures traffic source data survives client-side SPA navigations without losing the original referrer
- **iOS SDK: 12 click ID capture** — `handleDeepLink()` expanded from 2 (gclid, fbclid) to 12 ad platform click IDs (gclid, msclkid, fbclid, ttclid, twclid, li_fat_id, rdt_cid, scid, dclid, epik, irclickid, aff_id)
- **iOS SDK: campaign context in events** — `CampaignInfo` expanded with `content`, `term`, `clickIds`, `referrerDomain` fields; now wired into `buildContext()` so every event includes campaign attribution data
- **Android SDK: 12 click ID capture** — `handleDeepLink()` expanded from 3 (gclid, fbclid, msclkid) to 12 ad platform click IDs
- **Android SDK: campaign context in events** — new `campaignContext` JSONObject wired into `buildContext()` with source, medium, campaign, content, term, clickIds, referrerDomain
- **`confidence` field on `SourceInfo`** — classifier confidence score (0.0–1.0) now stored with each classified traffic source

### Changed

- **Traffic source classification** — `traffic_type` field on traffic sources is now automatically populated by the backend classifier instead of always arriving as `"unknown"` from the SDK. Channel breakdowns in `/v1/analytics/channels` now return meaningful categories (Paid Search, Organic Social, Email, Direct, Referral, etc.)
- **`POST /v1/track/traffic-source`** — now runs raw signals through `SourceClassifier` before storage, overriding SDK-provided source/medium/traffic_type with classified values

### Stats

- **5 files changed** — 1 new, 4 modified
- **~277 lines added** — zero classification logic in any SDK

---

## [8.1.0] — 2026-03-07

### Security Hardening, Bug Fixes & Diagnostics System

Comprehensive remediation of 51 issues discovered during deep code review (5 CRITICAL, 18 HIGH, 18 MEDIUM, 10 LOW). Adds a centralized automatic error handling and diagnostics system with circuit breakers, error fingerprinting, and real-time health monitoring.

### Added

- **Diagnostics Service** (`/v1/diagnostics/`) — centralized error tracking and monitoring system with 6 admin-only endpoints: `GET /health`, `GET /errors`, `GET /report`, `POST /errors/{fingerprint}/resolve`, `POST /errors/{fingerprint}/suppress`, `GET /circuit-breakers`
- **ErrorRegistry** (`shared/diagnostics/error_registry.py`) — automatic error classification engine with SHA-256 fingerprinting for deduplication, 13 error categories, 5 severity levels, and 11 built-in classification rules mapping exceptions to remediation advice
- **CircuitBreaker** — per-operation circuit breaker pattern (5 failures → open, 30s recovery) preventing cascading failures across services
- **`@track_error` decorator** — wraps async functions for automatic error registration, circuit breaker enforcement, and success tracking without swallowing exceptions
- **RPC method allowlist** (`services/onchain/rpc_gateway.py`) — restricts executable RPC methods to a curated set of safe EVM and Solana read methods, blocking arbitrary method execution

### Fixed

#### Critical

- **C-1: Race condition in x402 economic graph** — added `asyncio.Lock` and copy-and-swap pattern for concurrent `_payments` list mutation; `snapshot_to_graph()` now acquires lock, copies payments, clears list, releases lock before iterating
- **C-2: Hardcoded JWT secret** — `Settings.__post_init__` now raises `RuntimeError` when non-local environments use the default `"change-me-in-production"` secret
- **C-3: Hardcoded API key stub** — `APIKeyValidator` now only accepts `_STUB_KEYS` in `LOCAL` environment; non-local environments reject stub keys with `UnauthorizedError`
- **C-4: Agent IG endpoints not feature-flagged** — all 6 Intelligence Graph agent endpoints now check `settings.intelligence_graph.enable_agent_layer` before execution; trust endpoint additionally checks `enable_trust_scoring`
- **C-5: Audit engine never wired** — trail name mismatch fixed with `trail_key_map` dictionary mapping config names (`"Application Audit"`) to actual trail keys (`"application"`)

#### High

- **H-SEC1: RPC method injection** — added `ALLOWED_RPC_METHODS` allowlist blocking arbitrary method execution through the RPC gateway
- **H-SEC2: x402 header parsing** — added 8KB size limit, amount validation (non-negative numeric), rejection of malformed non-JSON headers
- **H-SEC3: Fraud routes unauthenticated** — added `request: Request` parameter and permission checks (`fraud:evaluate`, `fraud:read`, `admin`) to all 5 fraud service endpoints
- **H-SEC4/5: Cross-tenant data leakage** — added `tenant_id` parameter to commerce service, x402 economic graph, and agent lifecycle stores; all query methods now filter by tenant
- **H-SEC6: sendBeacon API key leak** — moved API key from URL query parameter (`?key=...`) to JSON request body to prevent key exposure in server logs, referrer headers, and browser history
- **H-SEC7: Audit trail name mismatch** — `retention_report()` now correctly maps config names to trail keys via lookup dictionary
- **H-LB2: Trust score inflated for unknown entities** — reduced default `identity_confidence` and `session_score` from `0.5` to `0.1`; unknown entities now score ~0.15 composite instead of ~0.70
- **H-EH1: x402 capture lost on event failure** — transaction now appended to `_captures` before event publishing; publish failure logged but doesn't block capture
- **H-EH2: On-chain action recorder** — graph operations wrapped in try/except; failures logged but action still recorded locally

#### Medium

- **M-1:** Fixed double "not found" in `NotFoundError` messages for on-chain contract lookups
- **M-2:** Bytecode risk scorer now receives `bytecode_opcodes` from action metadata instead of always scoring empty input
- **M-3:** RPC cache key changed from non-deterministic `hash()` to stable `hashlib.sha256().hexdigest()[:16]`
- **M-4:** Fixed `params: list[Any] = None` type annotation to `Optional[list[Any]]`
- **M-5:** RPC rate limiter now uses `asyncio.Lock` to prevent race conditions under concurrent requests
- **M-6:** Gremlin escape regex expanded from `['\\x00-\x1f]` to include `"`, `` ` ``, and `;` to prevent injection
- **M-7:** `Content-Length` header parsing wrapped in `try/except` to handle malformed values gracefully
- **M-8:** DSR erasure cascade extended to SERVICE (CONSUMES edges), PROTOCOL (INTERACTS_WITH edges), and x402 in-memory store; portability export now includes IG data
- **M-9:** SDK 429 retry now respects `maxRetries` bound instead of recursing indefinitely
- **M-10:** Removed unused `edges` variable in `get_layer_subgraph()`
- **M-11:** `EventConsumer` recursive retry replaced with bounded `while` loop to prevent stack overflow
- **M-12:** Confidence delta changed from binary (0/1) to graduated similarity using `SequenceMatcher`

#### Low

- **L-1:** Fee elimination rounding unified to 4 decimal places across commerce and x402 services
- **L-2:** Trust score constructor type annotations and docstring added
- **L-3:** Dead `SERVICE_PURCHASED` and `FEE_ELIMINATED` topics marked with `# Reserved` comments
- **L-5:** DSR `stores_processed`/`stores_remaining` type annotations changed from `list` to `list[str]`

### Changed

- **SDK types** — added 5 new event interfaces (`AgentTaskEvent`, `AgentDecisionEvent`, `PaymentEvent`, `X402PaymentEvent`, `ContractActionEvent`); `AetherEvent` discriminated union extended from 7 to 12 members
- **SDK EventType** — added `'experiment'` and `'performance'` to the `EventType` string literal union
- **Backend service count** — updated from 15 to 17 core services (added diagnostics service)

### Stats

- **26 files changed** — 22 modified, 4 new
- **51 issues remediated** — 5 critical, 18 high, 18 medium, 10 low

---

## [8.0.0] — 2026-03-06

### Unified On-Chain Intelligence Graph

### Added

- **Intelligence Graph** with 8 layers, 3 relationship layers (H2H, H2A, A2A), 6 new vertex types (AGENT, PAYMENT, CONTRACT, ACTION_RECORD, TRUST_SCORE, BYTECODE_RISK), and 13 new edge types (LAUNCHED_BY, DEPLOYED, PAID, RECEIVED, EXECUTED, DECIDED, HIRED, ACTED_ON, SCORED, RISKED, H2H_LINK, H2A_LINK, A2A_LINK)
- **Commerce service (L3a)** — payment recording, agent hiring, fee elimination with full payment lifecycle tracking
- **On-Chain Action service (L0)** — ActionRecord schema for normalized on-chain events, chain listener for real-time block monitoring, RPC gateway for multi-chain read/write
- **x402 Interceptor service (L3b)** — HTTP 402 payment header capture, economic graph construction from micropayment flows
- **Trust Score composite** — 3-component weighted average (identity confidence, behavioral history, on-chain reputation) derived from existing ML models
- **Bytecode Risk scorer** — rule-based static analysis scoring 10 patterns (reentrancy, selfdestruct, delegatecall, tx.origin, unchecked-send, uninitialized-storage, overflow, flash-loan, proxy-abuse, hidden-mint) on a 0.0-1.0 scale
- **Anomaly Detection extension** — 6 new feature columns (agent_action_rate, payment_velocity, contract_deploy_frequency, x402_amount_zscore, cross_layer_hop_count, trust_score_delta) added to existing anomaly detection model
- **Agent service extensions** — agent registration with capability declaration, lifecycle management (active/paused/terminated), autonomous decision recording with rationale capture, ground truth feedback loop for decision quality scoring
- **2 new consent purposes** (`agent`, `commerce`) with CONSENT_MAP routing: `agent_task`/`agent_decision` -> `'agent'`, `payment`/`x402_payment` -> `'commerce'`, `contract_action` -> `'web3'`
- **DSR cascade extended** to new vertex types — data subject access/erasure/portability requests now cascade through AGENT, PAYMENT, CONTRACT, and ACTION_RECORD vertices in addition to existing User, Wallet, Email, Phone, and DeviceFingerprint vertices
- **10 new audit actions** for Intelligence Graph operations: `graph.vertex.created`, `graph.vertex.updated`, `graph.vertex.deleted`, `graph.edge.created`, `graph.edge.deleted`, `graph.trust_score.computed`, `graph.bytecode_risk.scored`, `graph.agent.registered`, `graph.agent.decision_recorded`, `graph.dsr.cascade_executed`
- **3 new ROPA processing activities** — Agent Data Processing (lawful basis: legitimate interest), Commerce Payment Processing (lawful basis: contract performance), On-Chain Action Indexing (lawful basis: legitimate interest)
- **Feature-flagged via IntelligenceGraphConfig** — 7 flags (`enableCommerceLayer`, `enableAgentLayer`, `enableOnChainActions`, `enableX402Interceptor`, `enableTrustScore`, `enableBytecodeRisk`, `enableAnomalyExtension`), all disabled by default for safe rollout
- **QuickNodeConfig** for L6 infrastructure backbone — RPC endpoint management, chain-specific node configuration, and failover routing for multi-chain block data ingestion

---

## [7.0.0] — 2026-03-05

### Thin-Client Architecture, Identity Resolution, and DRY Consolidation

Major architectural shift to "Sense and Ship" thin-client design. SDKs now collect and ship raw events; all processing (identity resolution, ML inference, DeFi classification, funnel matching, heatmap generation) happens server-side. Cross-device identity resolution with hybrid deterministic + probabilistic matching. Full codebase DRY consolidation eliminating duplication across SDK, backend, and cross-platform modules.

### Added

- **Identity Resolution Engine** (`Backend Architecture/aether-backend/services/identity/`) — deterministic matching (email, phone, wallet, OAuth) + probabilistic matching (device fingerprint similarity, behavioral clustering, temporal overlap) with configurable thresholds
- **Identity Graph** — Neptune-backed graph with User, Session, Device, Email, Phone, Wallet, Company, IdentityCluster vertex types and HAS_SESSION, VIEWED_PAGE, TRIGGERED_EVENT, OWNS_WALLET, MEMBER_OF_CLUSTER, SIMILAR_TO edge types
- **Identity Resolution ML Model** — PyTorch MLP + Graph Attention Network for probabilistic cross-device identity matching
- **SDK hydrateIdentity()** — new method across all 4 SDKs that receives resolved identity from backend and hydrates local session
- **Backend processing pipeline** — server-side IP enrichment, identity resolution, ML inference, DeFi classification, traffic attribution, funnel matching, heatmap generation, whale detection

### Changed

- **Web SDK** — stripped to thin client: removed all server-side logic, SDK now collects raw events and ships via POST /v1/events
- **iOS/Android/React Native SDKs** — aligned to thin-client architecture with identical event-shipping pattern
- **Backend** — expanded from 15 to 16 microservices with dedicated Identity Resolution service
- **Documentation** — complete rewrite of ARCHITECTURE.md, new IDENTITY-RESOLUTION.md, updated BACKEND-API.md with identity endpoints

### Refactored

- **DRY consolidation** — eliminated duplication across SDK packages, backend services, and cross-platform modules
- **Shared type definitions** — unified type system across TypeScript SDK and Python backend
- **Common utilities** — consolidated redundant helper functions into shared modules

### Stats

- **36 files changed** — 8 added, 28 modified

---

## [6.1.0] — 2026-03-04

### Web2 Analytics Modules & Multi-Chain Reward Automation

Two major expansions: a full Web2 analytics module suite (ecommerce, form analytics, feature flags, feedback surveys, heatmaps, conversion funnels) integrated across all 4 SDK platforms, and multi-chain reward automation extending the oracle-signed reward pipeline from EVM-only to 7 VM families with native smart contracts on Solana, SUI, NEAR, and Cosmos.

### Added

#### Web2 Analytics Modules — Web SDK (`packages/web/src/modules/`)

- **Ecommerce Module** (`ecommerce.ts`) — product viewed/added/removed, cart state, checkout funnel, purchase tracking with currency support and localStorage cart persistence
- **Form Analytics Module** (`form-analytics.ts`) — field-level interaction tracking, hesitation detection, abandonment tracking, error capture, and form completion funnels
- **Feature Flag Module** (`feature-flags.ts`) — remote feature flag evaluation with caching, default fallbacks, targeting rules, and flag change listeners
- **Feedback Module** (`feedback.ts`) — in-app survey rendering, NPS/CSAT/CES collection, response submission, and targeting based on user segments
- **Heatmap Module** (`heatmaps.ts`) — click, move, and scroll heatmap data collection with configurable sampling rates and viewport-relative coordinate capture
- **Funnel Module** (`funnels.ts`) — conversion funnel definition, step tracking, drop-off analysis, and time-between-steps measurement

#### Web2 Analytics Modules — iOS (`Aether Mobile SDK/`)

- **AetherEcommerce** (`AetherEcommerce.swift`) — native ecommerce event tracking with product, cart, and purchase lifecycle
- **AetherFeatureFlags** (`AetherFeatureFlags.swift`) — remote flag evaluation with `UserDefaults` caching and TTL-based refresh
- **AetherFeedback** (`AetherFeedback.swift`) — survey fetching, response submission, and display eligibility checks

#### Web2 Analytics Modules — Android (`Aether Mobile SDK/`)

- **AetherEcommerce** (`AetherEcommerce.kt`) — Kotlin ecommerce tracking with `SharedPreferences`-backed cart state
- **AetherFeatureFlags** (`AetherFeatureFlags.kt`) — flag evaluation with coroutine-based background refresh on `Dispatchers.IO`
- **AetherFeedback** (`AetherFeedback.kt`) — survey management with `Gson` serialization and cooldown tracking

#### Web2 Analytics Modules — React Native (`packages/react-native/src/modules/`)

- **RNEcommerce** (`Ecommerce.ts`) — cross-platform ecommerce tracking bridging to native modules
- **RNFeatureFlags** (`FeatureFlags.ts`) — feature flag evaluation with `AsyncStorage` caching
- **RNFeedback** (`Feedback.ts`) — survey lifecycle management for React Native

#### Multi-Chain Oracle Signer (`Backend Architecture/aether-backend/services/oracle/`)

- **MultiChainSigner** (`multichain_signer.py`) — `VMType` enum (EVM, SVM, Bitcoin, MoveVM, NEAR, TVM, Cosmos) with 7 VM-specific message hash builders using domain-separated signing:
  - EVM: `SHA-256(abi.encodePacked(...))`
  - SVM: `SHA-256(Borsh-serialized instruction data)`
  - Bitcoin: `SHA-256d(Bitcoin varint message)`
  - MoveVM: `SHA3-256(BCS-encoded struct)`
  - NEAR: `SHA-256(Borsh-serialized payload)`
  - TVM: `SHA-256(TVM cell-encoded message)`
  - Cosmos: `SHA-256(canonical JSON sign bytes)`
- **MultiChainProofConfig** — per-chain configuration (chain_id, contract_address, proof_expiry) for all 7 VM families
- **MultiChainRewardProof** — extended proof structure with `vm_type`, `program_id`, and chain-specific metadata

#### Multi-Chain Smart Contracts (`Smart Contracts/programs/`)

- **Solana/Anchor** (`solana/aether_rewards.rs`) — ProgramState, Vault PDA, NonceTracker, 6 instructions (initialize, create_campaign, claim_reward, pause, unpause, withdraw_unclaimed), Ed25519 signature verification, 7 events, 11 error codes
- **SUI/Move** (`sui/aether_rewards.move`) — RewardPool shared object, AdminCap capability, ClaimReceipt hot potato pattern, Ed25519 verification, campaign budget tracking
- **NEAR** (`near/aether_rewards.rs`) — `#[near_bindgen]` contract with Ed25519 verification, NEP-297 events, Promise-based cross-contract calls, 8 unit tests
- **Cosmos/CosmWasm** (`cosmos/aether_rewards.rs`) — `cw_storage_plus` state management, Ed25519 verification via `cosmwasm_crypto`, `BankMsg::Send` for native token distribution, 13 unit tests

#### Multi-Chain Deployer (`Smart Contracts/deploy/`)

- **MultiChainDeployer** (`multichain_deployer.py`) — `ChainDeployer` ABC with 6 concrete deployers (Solana, SUI, NEAR, Cosmos, TRON, Bitcoin/Ordinals), CLI with argparse, 10 pre-configured chain targets, deployment manifest generation

### Changed

- **Web SDK** (`packages/web/src/index.ts`) — integrated all 6 Web2 modules into `init()` lifecycle with config passthrough, added 6 public sub-interfaces (`ecommerce`, `featureFlag`, `feedback`, `heatmap`, `funnel`, `forms`), added module cleanup in `destroy()`
- **iOS SDK** (`Aether Mobile SDK/Aether.swift`) — initialized `AetherEcommerce`, `AetherFeatureFlags`, `AetherFeedback` after core SDK init with apiKey/endpoint passthrough
- **Android SDK** (`Aether Mobile SDK/Aether.kt`) — initialized `AetherEcommerce`, `AetherFeatureFlags`, `AetherFeedback` with application context, apiKey, and endpoint
- **React Native SDK** (`packages/react-native/src/index.tsx`) — added `ecommerce`, `featureFlag`, `feedback` sub-interfaces to `Aether` object, integrated module initialization in `AetherProvider` with destroy cleanup on unmount
- **Reward Eligibility** (`services/rewards/eligibility.py`) — added `vm_type` field to `RewardTier` and `Campaign`, added `program_id` to `Campaign` for Solana/SUI program addressing
- **Reward Routes** (`services/rewards/routes.py`) — multi-chain `MultiChainSigner` initialization with environment-driven config for all 7 VM families, `CampaignCreate` model extended with `vm_type`/`program_id`, `evaluate_event` generates multi-chain proofs via oracle signer
- **SDK Reward Client** (`packages/web/src/rewards/reward-client.ts`) — added `VMType` type alias, chain-specific claim methods (`_claimEVM`, `_claimSolana`, `_claimSUI`, `_claimNEAR`, `_claimCosmos`, `_claimBitcoin`), chain-specific payload builders, contract address resolution helpers

### Documentation

- Updated root README with v6.1.0 platform overview, 16 services / 85+ endpoints, Smart Contracts row, Web2 Analytics Modules and Automated Reward Pipeline subsections
- Updated Web SDK README with 7 new feature bullets, module configuration table, API reference for ecommerce/featureFlags/feedback/heatmaps/funnels/forms
- Updated Backend README with 16 services, multi-chain oracle, new endpoint listings
- Updated Mobile SDK README with Web2 module features and iOS/Android code examples
- Updated React Native README with Web2 module API tables and project structure
- Updated CI/CD README with multi-chain smart contract deployment section

### Stats

- **40+ files changed** — 30+ added, 10+ modified

---

## [6.0.0] — 2026-03-04

### Smart Contract Analytics Integration — Automated Reward Pipeline

Major release adding a complete Web2 + Web3 automated analytics and reward architecture: fraud detection, multi-touch attribution, reward eligibility, oracle-signed proofs, on-chain smart contract reward distribution, and an automated analytics pipeline that ties it all together.

### Added

#### Fraud Detection Engine (`Backend Architecture/aether-backend/services/fraud/`)

- **8 composable fraud signals** (`signals.py`) — BotDetection, SybilDetection, Velocity, WalletAge, Geographic, Behavioral, DeviceFingerprint, TransactionPattern. Each implements `FraudSignal` ABC with configurable thresholds and 0-100 scoring.
- **Weighted fraud engine** (`engine.py`) — `FraudEngine` with `FraudConfig` (block at 70, flag at 40), runs all signals concurrently via `asyncio.gather`, produces weighted composite score with full audit trail.
- **5 API endpoints** (`routes.py`) — `POST /evaluate`, `POST /evaluate/batch`, `GET /config`, `PUT /config`, `GET /stats`.

#### Attribution Service (`Backend Architecture/aether-backend/services/attribution/`)

- **6 attribution models** (`models.py`) — FirstTouch, LastTouch, Linear, TimeDecay (configurable half-life), PositionBased (U-shaped), DataDriven (Shapley value approximation). All weights normalize to 1.0.
- **Attribution resolver** (`resolver.py`) — `AttributionResolver` with in-memory `JourneyStore`, touchpoint collection, lookback window filtering, and model selection.
- **5 API endpoints** (`routes.py`) — `POST /resolve`, `POST /touchpoints`, `GET /journey/{user_id}`, `DELETE /journey/{user_id}`, `GET /models`.

#### Reward Automation (`Backend Architecture/aether-backend/services/rewards/`)

- **Eligibility engine** (`eligibility.py`) — Rule-based reward eligibility with campaigns, tiered rewards, cooldown periods, per-user claim caps, fraud score gates, attribution weight gates, budget tracking, and time window enforcement.
- **Async reward queue** (`queue.py`) — `RewardQueue` with FIFO deque, exponential backoff retries, dead-letter handling, status lifecycle (pending → processing → proved → claimed), and oracle integration.
- **8 API endpoints** (`routes.py`) — `POST /evaluate` (full pipeline: fraud → attribution → eligibility → enqueue), `POST /campaigns`, `GET /campaigns`, `GET /campaigns/{id}`, `GET /queue/stats`, `GET /user/{address}`, `POST /process`, `GET /proof/{id}`.

#### Oracle Bridge (`Backend Architecture/aether-backend/services/oracle/`)

- **EVM-compatible proof signer** (`signer.py`) — `OracleSigner` generating `RewardProof` with random nonce, expiry timestamp, `abi.encodePacked`-style message hashing, and cryptographic signing (simulated HMAC-SHA256, production comments for `eth_account`/secp256k1).
- **Off-chain verifier** (`verifier.py`) — `verify_reward_proof()`, `is_proof_expired()`, `compute_message_hash()` for independent proof validation.
- **4 API endpoints** (`routes.py`) — `POST /proof/generate` (internal), `POST /proof/verify`, `GET /signer`, `GET /config`.

#### Smart Contracts (`Smart Contracts/`)

- **`AnalyticsRewards.sol`** — Main reward distribution contract with OpenZeppelin AccessControl + Pausable + ReentrancyGuard, ORACLE_ROLE/CAMPAIGN_MANAGER_ROLE access control, EIP-191 signature recovery with EIP-2 `s` malleability protection, campaign budget management, per-user claim caps, nonce replay protection, emergency withdrawal functions. Full NatSpec documentation.
- **`RewardRegistry.sol`** — On-chain action type and campaign registry with admin functions for registering actions/campaigns, reward tier management, and comprehensive view functions.
- **`IAnalyticsRewards.sol`** — Interface defining the external API with 6 events, core claim function, campaign management, and view functions.
- **Deployment script** (`deploy/deployer.py`) — Multi-chain deployer supporting Ethereum, Polygon, Arbitrum, Base, Optimism with CLI, deployment manifests, and verification.
- **Hardhat config** (`hardhat.config.js`) — Solidity 0.8.20, optimizer, viaIR, multi-chain network configs, Etherscan verification.

#### Automated Analytics Pipeline (`Backend Architecture/aether-backend/services/analytics_automation/`)

- **`AnalyticsPipeline`** (`pipeline.py`) — Real-time event ingestion that classifies platform (Web2/Web3), classifies intent (acquisition/engagement/conversion/retention), aggregates time-windowed metrics, triggers automated reward pipeline for eligible events, and generates automated insights.
- **`EventClassifier`** — Static utility for platform/intent classification and reward eligibility pre-filtering.
- **Anomaly detection** — Event volume spikes (>3x), fraud rate spikes (>2x), conversion drops (>50%), budget depletion warnings (>80%).
- **5 API endpoints** (`routes.py`) — `POST /ingest`, `GET /metrics/{campaign_id}`, `GET /overview`, `GET /insights`, `POST /report/{campaign_id}`.

#### SDK Reward Client (`packages/web/src/rewards/reward-client.ts`)

- **`RewardClient`** class with full lifecycle: `setUserAddress()`, `checkEligibility()`, `getProof()`, `claimOnChain()`, `getRewards()`, `getCampaigns()`, `onReward()` callback subscription.
- **On-chain claiming** — Manual ABI encoding of `claimReward()` function call, optional ethers.js signer integration, localStorage proof caching.
- **Auto-polling** — Configurable interval for automatic eligibility checking.

### Changed

- **Web SDK** (`packages/web/src/index.ts`) — Added `RewardClient` initialization in `init()`, new `rewards` public interface with 7 methods (setUserAddress, checkEligibility, getProof, claimOnChain, getRewards, getCampaigns, onReward), cleanup in `destroy()`.
- **Backend** (`Backend Architecture/aether-backend/main.py`) — Expanded from 11 to 15 service routers: added fraud, attribution, rewards, oracle, analytics_automation. Updated docstring with all new route listings (75+ total endpoints).

### Architecture

```
Frontend SDK → Analytics Backend → Fraud Engine → Attribution → Eligibility → Oracle Signer → Smart Contract → On-chain Reward
     ↓                                    ↓              ↓             ↓                              ↓
  RewardClient                     8 Fraud Signals   6 Models    Rule Engine                   EIP-191 Proofs
     ↓                                    ↓              ↓             ↓                              ↓
  claimOnChain()                   Composite Score   Touchpoints   Campaigns                   AnalyticsRewards.sol
```

### Stats

- **25+ files changed** — 20+ added, 5 modified

---

## [5.2.0] — 2026-03-04

### Semantic Context, Traffic Source Tracking, and ML Optimization

Three cross-cutting platform enhancements: a tiered semantic context layer that enriches every event across all SDKs with consent-driven behavioral signals, zero-config automatic traffic source detection that identifies all inbound sources without pre-created links, and a modular ML optimization stack for production model compression and accuracy tuning.

### Added

- **Tiered Semantic Context — Web** (`packages/web/src/context/semantic-context.ts`) — `SemanticContextCollector` with 3-tier consent-driven enrichment:
  - **Tier 1 (Essential):** Timestamp, event ID, SDK version, basic device info (anonymized). Always collected.
  - **Tier 2 (Functional):** Journey stage inference (awareness → consideration → decision → retention), screen path history, session duration, scroll depth, active/idle time. Requires `analytics` consent.
  - **Tier 3 (Rich):** Inferred intent, sentiment signals (frustration via rage-clicks/errors, engagement via scroll/active-time, urgency via navigation speed, confusion via backtracking), interaction heatmaps (configurable grid bucketing), and precise error logs. Requires `analytics` + `marketing` consent.
  - Passive DOM listeners with proper cleanup, all signals 0-1 normalized.

- **Tiered Semantic Context — iOS** (`Aether Mobile SDK/SemanticContext.swift`) — `SemanticContextCollector` singleton with serial DispatchQueue thread safety, lifecycle observers (`didBecomeActive`, `didEnterBackground`, `willResignActive`), Codable types for JSON serialization.

- **Tiered Semantic Context — Android** (`Aether Mobile SDK/SemanticContext.kt`) — `SemanticContextCollector` Kotlin object with `CopyOnWriteArrayList` and `@Volatile` fields, returns `JSONObject` envelopes, requires `initialize(context)` call.

- **Tiered Semantic Context — React Native** (`packages/react-native/src/context/SemanticContext.ts`) — `RNSemanticContextCollector` with `AppState.addEventListener` for app state tracking, pre-instantiated singleton, session duration and screen path tracking.

- **Automatic Traffic Source Tracker** (`packages/web/src/tracking/traffic-source-tracker.ts`) — zero-config detection pipeline with priority resolution:
  1. UTM parameters (`utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`)
  2. Ad click IDs across 12 platforms (`gclid`, `fbclid`, `msclkid`, `ttclid`, `twclid`, `li_fat_id`, `rdt_cid`, `scid`, `dclid`, `epik`, `irclickid`, `aff_id`)
  3. Referrer classification (27 social platforms, 15 search engines, 8 email providers)
  4. localStorage-persisted attribution with configurable 30-day window
  5. 12 traffic types: direct, organic, paid, social, email, referral, affiliate, push, sms, display, video, unknown

- **Traffic Source Backend Service** (`Backend Architecture/aether-backend/services/traffic/routes.py`) — FastAPI router with 5 endpoints: `POST /v1/traffic/sources` (register/upsert source), `POST /v1/traffic/events` (record traffic event), `GET /v1/traffic/sources` (list sources with filters), `GET /v1/traffic/sources/{id}` (get source by ID), `GET /v1/traffic/channels` (channel breakdown analytics). Pydantic models for request/response validation.

- **ML Quantization** (`ML Models/aether-ml/optimization/quantization.py`) — `ModelQuantizer` with 4 strategies: Dynamic (INT8 runtime), Static (INT8 calibrated), Weight-only (INT8 weights, FP32 activations), FP16. Includes tolerance checking with FP32 fallback and inference speedup benchmarking.

- **ML Distillation** (`ML Models/aether-ml/optimization/distillation.py`) — `ModelDistiller` with 3 modes: Soft-label (temperature-scaled probability transfer), Feature-matching (intermediate representation alignment), Progressive (iterative teacher shrinking). Supports data augmentation and configurable temperature scaling.

- **ML Pruning** (`ML Models/aether-ml/optimization/pruning.py`) — `ModelPruner` with 4 strategies: Magnitude (unstructured L1-norm), Structured (feature/neuron removal), Iterative (gradual pruning with fine-tune cycles), Sensitivity-aware (permutation importance-based). Automatic warm-start fine-tuning when accuracy drops.

- **ML Optimization Pipeline** (`ML Models/aether-ml/optimization/pipeline.py`) — `OptimizationPipeline` orchestrating Prune → Quantize → Distill with 3 pre-built profiles: Edge (INT8 dynamic + 30% magnitude pruning), Server (FP16 + 20% structured pruning), Aggressive (INT8 static + 50% iterative pruning). `OptimizationResult` with `summary()` method for reporting.

### Changed

- **Web SDK** (`packages/web/src/index.ts`) — Integrated `SemanticContextCollector` and `TrafficSourceTracker` into `init()`. Semantic context attached to every event via `enqueueEvent()`. Traffic source auto-detected on init and included in event payload. EdgeML callbacks inject intent and session score into semantic context. Cleanup on `destroy()`.

- **iOS SDK** (`Aether Mobile SDK/Aether.swift`) — `SemanticContextCollector.shared.resetSession()` called on init, `.recordScreen()` called on screen views, semantic context JSON injected into every event via `enqueueEvent()`.

- **Android SDK** (`Aether Mobile SDK/Aether.kt`) — `SemanticContextCollector.initialize()` and `.resetSession()` called on init, `.recordScreen()` called on screen views, semantic context injected into every event.

- **React Native** (`packages/react-native/src/index.tsx`) — Imported `semanticContext` singleton, `.resetSession()` called in `AetherProvider` mount, `.recordScreen()` called in `screenView()`, `.destroy()` called on unmount.

- **Backend** (`Backend Architecture/aether-backend/main.py`) — Added `traffic_router` as 11th service router.

### Documentation

- Updated Web SDK README with semantic context and traffic source tracking module descriptions, project structure additions
- Updated Mobile SDK README with tiered semantic context feature description
- Updated React Native README with semantic context feature and project structure additions
- Updated Backend README with Traffic service in service listing and project structure

### Stats

- **17 files changed** — 12 added, 5 modified

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
| [8.0.0](#800--2026-03-06) | 2026-03-06 | Unified On-Chain Intelligence Graph (8 layers, H2H/H2A/A2A), commerce service, on-chain actions, x402 interceptor, trust score, bytecode risk, agent extensions, 2 new consent purposes |
| [7.0.0](#700--2026-03-05) | 2026-03-05 | Thin-client "Sense and Ship" architecture, identity resolution (deterministic + probabilistic), DRY consolidation |
| [6.1.0](#610--2026-03-04) | 2026-03-04 | Web2 analytics modules (ecommerce, forms, feature flags, feedback, heatmaps, funnels), multi-chain reward automation (7 VMs), smart contracts (Solana, SUI, NEAR, Cosmos) |
| [6.0.0](#600--2026-03-04) | 2026-03-04 | Smart contract analytics integration, fraud engine, attribution, oracle bridge, automated rewards, on-chain claiming |
| [5.2.0](#520--2026-03-04) | 2026-03-04 | Tiered semantic context, automatic traffic source tracking, ML optimization (quantization, distillation, pruning) |
| [5.1.0](#510--2026-03-04) | 2026-03-04 | SDK auto-update system, CDN auto-loader, OTA data modules |
| [5.0.0](#500--2026-03-04) | 2026-03-04 | Multi-VM Web3 (7 VMs, 150+ DeFi protocols), demo environment |
| [4.0.0](#400--2026-03-03) | 2026-03-03 | CI/CD pipeline, AWS deployment, GDPR & SOC 2 compliance |
| [3.0.0](#300--2026-03-03) | 2026-03-03 | Agent layer, FastAPI backend, ML models |
| [2.0.0](#200--2026-03-03) | 2026-03-03 | Event ingestion pipeline, data lake architecture |
| [1.0.0](#100--2026-03-03) | 2026-03-03 | Web SDK, React Native SDK, mobile SDKs, playground |
