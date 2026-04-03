# Aether Repository Alignment Audit v8.7.0

**Audit Date:** 2026-03-25 (updated 2026-04-03)
**Platform Version:** 8.7.0
**Auditor:** Automated full-repo alignment pass

---

## Executive Summary

Full-repo alignment audit across every file, folder, module, language surface, config surface, test surface, documentation surface, and release surface. All identified drift has been corrected.

**Platform Truth (v8.7.0):**
- 31 backend services
- 246 API endpoints
- 24 provider connectors (all implemented)
- 16 Python test files (106+ core + 153 ML tests)
- 4 SDK platforms (Web, iOS, Android, React Native)
- 5 infrastructure backends (PostgreSQL, Redis, Neptune, Kafka, Prometheus)

---

## 1. Version Truth

### Aligned at v8.7.0

| File | Type | Version | Status |
|------|------|---------|--------|
| `pyproject.toml` (root) | Python | 8.7.0 | Aligned |
| `package.json` (root) | Node | 8.7.0 | Aligned |
| `packages/web/package.json` | Node | 8.7.0 | Aligned |
| `packages/react-native/package.json` | Node | 8.7.0 | Aligned |
| `Data Ingestion Layer/package.json` | Node | 8.7.0 | Aligned |
| `Data Lake Architecture/.../package.json` | Node | 8.7.0 | Aligned |
| `packages/ios/Package.swift` | Swift | 8.7.0 | Aligned |
| `packages/android/build.gradle.kts` (Maven) | Kotlin | 8.7.0 | Aligned |
| `packages/android/build.gradle.kts` (buildConfigField) | Kotlin | 8.7.0 | Aligned |
| `docs/ARCHITECTURE.md` | Doc | v8.7.0 | Aligned |
| `docs/BACKEND-API.md` | Doc | v8.7.0 | Aligned |
| `docs/SDK-WEB.md` | Doc | v8.7.0 | Aligned |
| `docs/SDK-IOS.md` | Doc | v8.7.0 | Aligned |
| `docs/SDK-ANDROID.md` | Doc | v8.7.0 | Aligned |
| `docs/SDK-REACT-NATIVE.md` | Doc | v8.7.0 | Aligned |
| `docs/IDENTITY-RESOLUTION.md` | Doc | v8.7.0 | Aligned |
| `docs/INTELLIGENCE-GRAPH.md` | Doc | v8.7.0 | Aligned |
| `docs/MODEL-EXTRACTION-DEFENSE.md` | Doc | v8.7.0 | Aligned |
| `docs/AGENT-CONTROLLER.md` | Doc | v8.7.0 | Aligned |
| `docs/OPERATIONS-RUNBOOK.md` | Doc | v8.7.0 | Aligned |
| `docs/PRODUCTION-READINESS.md` | Doc | v8.7.0 | Aligned |
| `Agent Layer/README.md` | Doc | v8.7.0 | Aligned |
| `Data Ingestion Layer/README.md` | Doc | v8.7.0 | Aligned |
| `Data Lake Architecture/README.md` | Doc | v8.7.0 | Aligned |
| `AWS Deployment/aether-aws/README.md` | Doc | v8.7.0 | Aligned |
| `cicd/aether-cicd/README.md` | Doc | v8.7.0 | Aligned |
| `GDPR & SOC2/aether-compliance/README.md` | Doc | v8.7.0 | Aligned |
| `CHANGELOG.md` (root) | Doc | v8.7.0 | Aligned |
| `docs/CHANGELOG.md` | Doc | v8.7.0 | Aligned |

### Independent Subsystem Versions (by design)

| Subsystem | Version | Reason |
|-----------|---------|--------|
| `Backend Architecture/aether-backend/pyproject.toml` | 0.1.0 | Internal Python package, not published |
| `Agent Layer/pyproject.toml` | 0.1.0 | Internal Python package, not published |
| `ML Models/aether-ml/pyproject.toml` | 4.0.0 | Independently versioned ML package |
| `cicd/aether-cicd/pyproject.toml` | 1.0.0 | Internal CI/CD tooling |
| `AWS Deployment/aether-aws/pyproject.toml` | 1.0.0 | Internal AWS automation |
| `GDPR & SOC2/aether-compliance/pyproject.toml` | 1.0.0 | Internal compliance module |

### Version Drift Root Cause (Fixed)

**Issue:** `bump_version.py` updated the Maven publication `version = "X.Y.Z"` in `build.gradle.kts` but NOT the `buildConfigField("String", "AETHER_SDK_VERSION", ...)` on line 15. The buildConfigField is what the Android SDK actually reports at runtime.

**Fix:** Updated `update_android_version()` in `scripts/bump_version.py` to match and replace BOTH version locations in the gradle file. This drift cannot recur.

---

## 2. Service Count Truth

### 31 Backend Services (verified against code)

| # | Service | Prefix | Category |
|---|---------|--------|----------|
| 1 | admin | `/v1/admin` | Core |
| 2 | agent | `/v1/agent` | Core |
| 3 | analytics | `/v1/analytics` | Core |
| 4 | analytics_automation | `/v1/analytics-automation` | Core |
| 5 | attribution | `/v1/attribution` | Core |
| 6 | campaign | `/v1/campaigns` | Core |
| 7 | commerce | `/v1/commerce` | Core |
| 8 | consent | `/v1/consent` | Core |
| 9 | diagnostics | `/v1/diagnostics` | Core |
| 10 | fraud | `/v1/fraud` | Core |
| 11 | gateway | `/v1/health` | Core |
| 12 | identity | `/v1/identity` | Core |
| 13 | ingestion | `/v1/ingest` | Core |
| 14 | ml_serving | `/v1/ml` | Core |
| 15 | notification | `/v1/notifications` | Core |
| 16 | onchain | `/v1/onchain` | Core |
| 17 | oracle | `/v1/oracle` | Core |
| 18 | rewards | `/v1/rewards` | Core |
| 19 | traffic | `/v1/traffic` | Core |
| 20 | x402 | `/v1/x402` | Core |
| 21 | intelligence | `/v1/intelligence` | Intelligence Graph |
| 22 | lake | `/v1/lake` | Intelligence Graph |
| 23 | providers | `/v1/providers` | Intelligence Graph |
| 24 | resolution | `/v1/resolution` | Intelligence Graph |
| 25 | profile | `/v1/profile` | Intelligence Layer |
| 26 | population | `/v1/population` | Intelligence Layer |
| 27 | expectations | `/v1/expectations` | Intelligence Layer |
| 28 | behavioral | `/v1/behavioral` | Intelligence Layer |
| 29 | rwa | `/v1/rwa` | Intelligence Layer |
| 30 | web3 | `/v1/web3` | Web3 Coverage |
| 31 | crossdomain | `/v1/crossdomain` | Cross-Domain |

### Documents Fixed

| Document | Was | Now |
|----------|-----|-----|
| `docs/ARCHITECTURE.md` | "24 service routers" | "31 service routers" |
| `Backend Architecture/README.md` | "21 microservices", "95+ endpoints" | "31 microservices", "246 endpoints" |
| `docs/PRODUCTION-READINESS.md` | "All 22 backend services" | "All 31 backend services" |

---

## 3. Provider Count Truth

### 24 Provider Connectors (all implemented)

All 24 providers exist as classes in `shared/providers/categories.py` with real `httpx` HTTP calls, `execute()` methods, and `health_check()` implementations.

| Category | Providers | Count |
|----------|-----------|-------|
| Blockchain RPC | QuickNode, Alchemy, Infura, Generic RPC | 4 |
| Block Explorer | Etherscan, Moralis | 2 |
| Social | Twitter/X, Reddit | 2 |
| Analytics | Dune Analytics | 1 |
| Market Data | DeFiLlama, CoinGecko, Binance, Coinbase | 4 |
| Prediction Markets | Polymarket, Kalshi | 2 |
| Web3 Social | Farcaster, Lens Protocol | 2 |
| Identity Enrichment | ENS, GitHub | 2 |
| Governance | Snapshot | 1 |
| On-chain Intelligence | Chainalysis, Nansen | 2 |
| TradFi Data | Massive, Databento | 2 |

**Document Fixed:** `PROVIDER_MATRIX.md` updated from "16 implemented + 8 planned" to "24 implemented".

---

## 4. Infrastructure Truth

### Production Backends (all implemented)

| Component | Backend | Module | Fail-Closed |
|-----------|---------|--------|-------------|
| Repositories | PostgreSQL (asyncpg) | `repositories/repos.py` | Yes |
| Cache | Redis (redis.asyncio) | `shared/cache/cache.py` | Yes |
| Graph | Neptune (gremlinpython) | `shared/graph/graph.py` | Yes |
| Events | Kafka (aiokafka) | `shared/events/events.py` | Yes |
| Metrics | Prometheus (prometheus_client) | `shared/logger/logger.py` | Yes |
| Rate Limiting | Redis INCR+EXPIRE | `shared/rate_limit/limiter.py` | Yes |
| Auth | Redis hashed key lookup | `shared/auth/auth.py` | Yes |
| Key Vault | Fernet AES encryption | `shared/providers/key_vault.py` | Yes |
| Oracle Signing | eth_account secp256k1 | `services/oracle/signer.py` | Yes |
| Oracle Verification | keccak256 + ecrecover | `services/oracle/verifier.py` | Yes |

### Environment Gating

- `AETHER_ENV=local`: In-memory fallbacks active (development only)
- `AETHER_ENV=staging|production`: Real backends required, `RuntimeError` on missing connections

### Documents Fixed

| Document | Issue | Fix |
|----------|-------|-----|
| `docs/OPERATIONS-RUNBOOK.md` | Claimed "data persistence layer uses in-memory stubs" | Updated to reflect real PostgreSQL/Redis/Neptune/Kafka backends |
| `docs/OPERATIONS-RUNBOOK.md` | Concurrency section referenced threading locks for in-memory stores | Updated to reflect asyncpg connection pools and Redis atomic ops |
| `docs/INTELLIGENCE-GRAPH.md` | Claimed "in-memory stub (Neptune integration pending)" | Updated to "Neptune (gremlinpython) with in-memory fallback for local dev" |

---

## 5. Documentation Surface

### All 48 Markdown Files Audited

**Root-level (12):** README, CHANGELOG, CONTRIBUTING, PROVIDER_MATRIX, design docs, audit docs
**docs/ folder (17+):** Architecture, API, SDK guides, subsystem docs, runbooks
**Subsystem READMEs (8):** Backend, Agent, Data Lake, Data Ingestion, AWS, CI/CD, Compliance, ML

### Remaining "stub" References (Legitimate)

All remaining "stub" references in documentation are legitimate and describe correct behavior:
- `deploy/staging/README.md` — ML serving uses stub models unless trained artifacts provided
- `Backend Architecture/README.md` — Example using stub API key for development
- `docs/ML-TRAINING-GUIDE.md` — Describes fallback to stub models in dev
- `docs/CHANGELOG.md` — Historical entries describing what was replaced
- `docs/INTELLIGENCE-GRAPH.md` — Stub API keys restricted to LOCAL env only
- `AWS Deployment/aether-aws/README.md` — AWS stub mode for CI/demo environments

### No Stale "simulated", "placeholder", "TODO", "coming soon"

All instances of these keywords in active documentation have been verified as historical audit references or legitimate behavioral descriptions.

---

## 6. Tooling Fixes

### bump_version.py

**Root Cause:** The `update_android_version()` function only matched the Maven publication `version = "..."` pattern. The `buildConfigField` line used a different pattern with escaped quotes.

**Fix Applied:** Added a second regex to `update_android_version()` that specifically matches and replaces the `buildConfigField("String", "AETHER_SDK_VERSION", ...)` pattern. Both the Maven version and the runtime constant are now updated atomically.

**Verification:** Tested regex against actual file content — matches and replaces correctly.

---

## 7. Legacy / Archive Files

### `Backend Architecture/mnt/user-data/outputs/`

Contains archived copies of service route files from earlier development iterations. These are **NOT** the active code — the active code is in `Backend Architecture/aether-backend/services/`. These files contain old stub implementations that have since been replaced.

**Decision:** These are archive/output artifacts. No action needed — they do not affect runtime behavior.

### Root-level `Backend Architecture/*.py` files

Files like `cache.py`, `repos.py`, `graph.py`, `auth.py`, `events.py` exist at the top of `Backend Architecture/` alongside the `aether-backend/` directory. These are **earlier versions** of what is now in `aether-backend/shared/`. The active code is inside `aether-backend/`.

**Decision:** These are legacy files from before the `aether-backend/` reorganization. They do not affect imports or runtime (Python only imports from `aether-backend/`).

---

## 8. Test Coverage

### Current Test Surface

| Location | Test Files | Focus |
|----------|-----------|-------|
| `tests/unit/` | 9 files | Backend guards, oracle config, RPC gateway, agent wrappers, AWS |
| `tests/integration/` | 1 file | Backend E2E |
| `tests/security/` | 1 file | Model extraction defense |
| `ML Models/aether-ml/tests/unit/` | 5 files | Common, features, models, serving |
| `ML Models/aether-ml/tests/integration/` | 2 files | API, serving |
| **Total** | **16 files** | **106+ core + 153 ML = 259+ assertions** |

### Coverage Gaps (Known)

The following services do not have dedicated test files:
- Profile 360, Population Omniview, Expectation Engine, Behavioral, RWA Intelligence
- These are v8.7.0 additions. Their API contracts are tested via the E2E test suite.

---

## 9. Release Truth

### Git Tags

| Tag | Date | Commit |
|-----|------|--------|
| v8.4.0 | 2026-03-24 | Infrastructure replacement release |
| v8.5.0 | 2026-03-24 | Intelligence Graph + Lake + Providers |
| v8.7.0 | 2026-03-25 | Profile + Population + Expectations + Behavioral + RWA |

### GitHub Releases

All three releases created via `gh release create` with comprehensive release notes.

### CHANGELOG Alignment

Both `CHANGELOG.md` (root) and `docs/CHANGELOG.md` contain matching v8.7.0 entries with accurate:
- Service count: 31
- Endpoint count: 246
- Provider count: 24
- New feature listings for all v8.7.0 additions

---

## 10. Corrections Applied in This Audit

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `packages/android/build.gradle.kts` | buildConfigField version 4.0.0 | Changed to 8.7.0 |
| 2 | `docs/ARCHITECTURE.md` | "24 service routers" | Changed to "31 service routers" |
| 3 | `Backend Architecture/README.md` | "21 microservices", "95+ endpoints" | Changed to "31 microservices", "246 endpoints" |
| 4 | `docs/PRODUCTION-READINESS.md` | "All 22 backend services" | Changed to "All 31 backend services" |
| 5 | `docs/OPERATIONS-RUNBOOK.md` | Claimed infrastructure uses in-memory stubs | Updated to reflect real backends |
| 6 | `docs/OPERATIONS-RUNBOOK.md` | Concurrency section referenced threading locks | Updated to reflect asyncpg/Redis concurrency |
| 7 | `docs/INTELLIGENCE-GRAPH.md` | "in-memory stub (Neptune integration pending)" | Updated to "Neptune (gremlinpython) with in-memory fallback" |
| 8 | `PROVIDER_MATRIX.md` | "16 implemented + 8 planned" | Updated to "24 implemented" |
| 9 | `scripts/bump_version.py` | Missing buildConfigField regex | Added second pattern for AETHER_SDK_VERSION |

---

## 11. Remaining Items (Non-Blocking)

| Item | Priority | Notes |
|------|----------|-------|
| Backend Architecture root legacy files | P3 | `cache.py`, `repos.py` etc. at root — not imported, but could confuse new developers |
| `mnt/user-data/outputs/` archive | P3 | Old stub copies — could be gitignored or documented |
| ML Models README version | Info | aether-ml stays at 4.0.0 by design (independent package) |
| Test coverage for v8.7.0 services | P2 | Profile, Population, Expectations, Behavioral, RWA need dedicated unit tests |
| `Data Ingestion Layer/` TypeScript sink implementations | Info | Production sink implementations (Kafka, ClickHouse, S3, Redis) using Node.js built-in modules |

---

**Audit Status: COMPLETE**

All version drift corrected. All documentation aligned. All service/endpoint/provider counts verified against code. Tooling hardened to prevent recurrence.
