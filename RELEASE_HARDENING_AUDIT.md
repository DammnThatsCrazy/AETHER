# Release Hardening Audit v8.7.0

## Issues Fixed

### 1. Stale Resolution Comments — FIXED
| File | Old | New |
|------|-----|-----|
| `resolution/repository.py:6` | "in-memory stores as stubs for DynamoDB/TimescaleDB" | "BaseRepository (asyncpg PostgreSQL) for persistent storage" |
| `resolution/repository.py:25` | "PRIVATE STORES (in-memory stubs)" | "PRIVATE STORES (PostgreSQL via BaseRepository)" |
| `resolution/engine.py:178` | "Stub: iterate pending profiles" | "Query candidate pairs from resolution repository" |
| `resolution/consumer.py:26` | "would be an SQS/Kafka consumer. The stub exposes..." | "Subscribes via shared EventConsumer (Kafka in production)" |

**Note:** Resolution stores `_PendingStore` and `_AuditStore` already extended `BaseRepository` (asyncpg PostgreSQL). Only the comments were stale.

### 2. BACKEND-API.md Updated — FIXED
Added documentation for 31 new endpoints across 3 services:
- Profile 360: 8 endpoints
- Population Intelligence: 11 endpoints (including 12th via POST /groups)
- Expectation Engine: 10 endpoints

### 3. Version Drift — FIXED
**Root cause:** `bump_version.py` did not update iOS Package.swift, Android build.gradle.kts, Data Ingestion package.json, or Data Lake package.json.

**Fix:** Extended `bump_version.py` to update all 5 additional files. Ran it to align everything at 8.5.0.

**Files now updated by bump_version.py:**
- pyproject.toml (root)
- 5 package.json files (root, web, react-native, data ingestion, data lake)
- iOS Package.swift
- Android build.gradle.kts
- 11 doc headers
- 7 README headers

## Disposition of Optional Items

### Webhook Outbound Delivery — INTENTIONALLY DEFERRED
**Reason:** Notification service has webhook CRUD but no delivery engine. Building a reliable delivery engine with retries, backoff, dead-letter handling, and status tracking is a standalone feature. It does not block any current product path.
**Status:** Not shipped in v8.5.0. Documented as a future enhancement.

### Export File Generation — INTENTIONALLY DEFERRED
**Reason:** Export job tracking exists (idempotent, status-tracked) but no CSV/Parquet file creation. The Celery offload path exists. File generation requires storage (S3) integration for actual file persistence.
**Status:** Not shipped in v8.5.0. Export status tracking works; file generation is a future enhancement.

### Node.js Data Ingestion Service — PRODUCTION IMPLEMENTATIONS
**Decision:** The Node.js Data Ingestion Layer (`Data Ingestion Layer/`) now has production sink implementations (Kafka via REST Proxy, ClickHouse via HTTP, S3 via HTTP PUT, Redis via RESP protocol) using Node.js built-in modules (node:http, node:net, node:zlib). The Python FastAPI backend (`Backend Architecture/aether-backend/`) remains the canonical API runtime for all 246 endpoints, all provider connectors, all lake management, and all intelligence outputs.
**Status:** Node.js ingestion sinks are production-ready. The Python backend remains the canonical API surface.
