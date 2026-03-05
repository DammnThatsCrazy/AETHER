# Aether Backend Architecture

**FastAPI microservices backend for the Aether platform.**

Aether Backend is a unified API gateway that mounts 11 domain-specific microservices onto a single FastAPI application. It provides real-time data ingestion, identity resolution, analytics, ML model serving, autonomous agent orchestration, campaign management, consent/DSR compliance, notifications, traffic source tracking, and multi-tenant administration -- all behind a single versioned API surface with 55+ endpoints.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Services](#services)
- [API Reference Overview](#api-reference-overview)
- [Authentication & Authorization](#authentication--authorization)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [Development Commands](#development-commands)
- [License](#license)

---

## Tech Stack

| Layer              | Technology                                      |
| ------------------ | ----------------------------------------------- |
| Language           | Python 3.11+                                    |
| Framework          | FastAPI 0.115+ / Uvicorn (ASGI)                 |
| Validation         | Pydantic v2                                     |
| Relational / TSDB  | PostgreSQL / TimescaleDB (asyncpg)              |
| Graph Database     | Amazon Neptune (Gremlin via gremlinpython)       |
| Cache              | Redis 5+ (hiredis)                              |
| Document Store     | Amazon DynamoDB (aioboto3)                       |
| Search             | Amazon OpenSearch                               |
| Object Storage     | Amazon S3                                       |
| Event Bus          | Apache Kafka (aiokafka) or AWS SNS + SQS        |
| Observability      | Prometheus metrics, structured JSON logging      |
| Linting / Types    | Ruff, mypy (strict mode)                        |
| Testing            | pytest, pytest-asyncio, httpx                   |

---

## Architecture

```
                         +---------------------------+
                         |       Load Balancer       |
                         +-------------+-------------+
                                       |
                         +-------------v-------------+
                         |     FastAPI Application    |
                         |  (main.py / create_app)    |
                         +-------------+-------------+
                                       |
              +------------------------+------------------------+
              |           Middleware Stack (global)              |
              |  CORS -> Auth -> Rate Limit -> Body Size -> Log |
              +------------------------+------------------------+
                                       |
       +-------+-------+-------+------+------+-------+-------+-------+-------+
       |       |       |       |      |      |       |       |       |       |
  +----v-+ +--v---+ +-v----+ +v---+ +v--+ +-v---+ +-v----+ +v----+ +v----+ +v----+
  |Gate- | |Inges-| |Iden- | |Ana-| |ML | |Age-| |Camp-| |Con- | |Noti-| |Admin|
  |way   | |tion  | |tity  | |lyt-| |Ser| |nt  | |aign | |sent | |fica-| |     |
  |      | |      | |      | |ics | |ve | |    | |     | |     | |tion | |     |
  +--+---+ +--+---+ +--+---+ ++--++ ++--+ ++---+ ++----+ ++----+ ++----+ ++----+
     |        |        |       |      |     |      |       |       |       |
     +--------+--------+-------+------+-----+------+-------+-------+-------+
                                       |
              +------------------------+------------------------+
              |         Dependency Injection (ResourceRegistry)  |
              |  Cache | Graph | EventProducer | RateLimiter     |
              |  JWTHandler | APIKeyValidator                    |
              +------+------+------+------+------+--------------+
                     |      |      |      |      |
               +-----v+ +--v---+ +v----+ +v---+ +v--------+
               |Redis | |Nept-| |Kafka| |Dyn-| |Timescale|
               |      | |une  | |/SNS | |amo | |DB       |
               +------+ +-----+ +-----+ +----+ +---------+
```

**Key architectural decisions:**

- **Single process, multiple routers** -- all 10 services are mounted as FastAPI `APIRouter` instances, sharing a single event loop and connection pool for reduced operational overhead.
- **Dependency injection with lifecycle management** -- a `ResourceRegistry` singleton owns all shared resources (cache, graph, event bus, auth handlers). It is initialized at startup and torn down at shutdown via FastAPI's lifespan protocol.
- **Repository pattern** -- data access is abstracted behind repository classes that separate query logic from business logic, with built-in caching, graph operations, and write-ahead logging hooks.
- **12-Factor configuration** -- all settings are sourced from environment variables with sensible defaults (`config/settings.py`).

---

## Services

| #  | Service          | Prefix                  | Description                                                  | Key Endpoints                                            |
| -- | ---------------- | ----------------------- | ------------------------------------------------------------ | -------------------------------------------------------- |
| 1  | **Gateway**      | `/`, `/v1/health`       | Health checks, root metadata, internal metrics               | `GET /v1/health`, `GET /v1/metrics`                      |
| 2  | **Ingestion**    | `/v1/ingest`            | SDK event intake (single + batch), external API feeds        | `POST /v1/ingest/events`, `POST /v1/ingest/events/batch` |
| 3  | **Identity**     | `/v1/identity`          | Profile CRUD, identity merge/resolution, graph traversal     | `GET /v1/identity/profiles/{id}`, `POST /v1/identity/merge` |
| 4  | **Analytics**    | `/v1/analytics`         | Event queries, dashboards, data export, GraphQL, WebSocket   | `POST /v1/analytics/events/query`, `WS /v1/analytics/ws/events` |
| 5  | **ML Serving**   | `/v1/ml`                | Model registry, single + batch prediction, feature serving   | `POST /v1/ml/predict`, `GET /v1/ml/features/{id}`        |
| 6  | **Agent**        | `/v1/agent`             | Autonomous task orchestration, audit trail, kill switch      | `POST /v1/agent/tasks`, `POST /v1/agent/kill-switch`     |
| 7  | **Campaign**     | `/v1/campaigns`         | Campaign lifecycle (CRUD), attribution tracking              | `POST /v1/campaigns`, `GET /v1/campaigns/{id}/attribution` |
| 8  | **Consent**      | `/v1/consent`           | GDPR/CCPA consent records, data subject request management   | `POST /v1/consent/records`, `POST /v1/consent/dsr`       |
| 9  | **Notification** | `/v1/notifications`     | Webhook management, alert creation and listing               | `POST /v1/notifications/webhooks`, `POST /v1/notifications/alerts` |
| 10 | **Admin**        | `/v1/admin`             | Tenant management, API key provisioning, billing             | `POST /v1/admin/tenants`, `POST /v1/admin/tenants/{id}/api-keys` |
| 11 | **Traffic**      | `/v1/traffic`           | Automatic traffic source tracking, channel attribution       | `POST /v1/traffic/sources`, `GET /v1/traffic/channels` |

---

## API Reference Overview

All endpoints are versioned under `/v1` and return consistent JSON envelopes:

**Success response:**

```json
{
  "data": { ... },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-03-03T12:00:00+00:00"
  }
}
```

**Paginated response:**

```json
{
  "data": [ ... ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 142,
    "has_more": true
  },
  "meta": { ... }
}
```

**Error response:**

```json
{
  "error": {
    "code": 401,
    "message": "Missing API key or Bearer token",
    "details": {},
    "request_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

**Common HTTP status codes:** `200` OK, `201` Created, `400` Bad Request, `401` Unauthorized, `403` Forbidden, `404` Not Found, `409` Conflict, `413` Payload Too Large, `422` Unprocessable Entity, `429` Rate Limited, `500` Internal Server Error, `503` Service Unavailable.

**Interactive docs** are available at `/docs` (Swagger UI) and `/redoc` (ReDoc) when the server is running.

### Full Endpoint Listing (50+)

<details>
<summary>Click to expand all endpoints</summary>

**Gateway**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/` | Root metadata |
| `GET` | `/v1/health` | Deep health check (probes all dependencies) |
| `GET` | `/v1/metrics` | Internal Prometheus metrics |

**Ingestion**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/v1/ingest/events` | Ingest a single SDK event |
| `POST` | `/v1/ingest/events/batch` | Ingest a batch of SDK events |
| `POST` | `/v1/ingest/feed` | Ingest from an external API feed |

**Identity**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/v1/identity/profiles/{id}` | Get a user profile |
| `PUT` | `/v1/identity/profiles/{id}` | Upsert a user profile |
| `POST` | `/v1/identity/merge` | Merge two identities |
| `GET` | `/v1/identity/profiles/{id}/graph` | Get profile graph neighbors |

**Analytics**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/v1/analytics/events/query` | Query events with filters |
| `GET` | `/v1/analytics/events/{id}` | Get a single event by ID |
| `GET` | `/v1/analytics/dashboard/summary` | Dashboard summary (24h) |
| `POST` | `/v1/analytics/export` | Export data |
| `POST` | `/v1/analytics/graphql` | GraphQL query endpoint |
| `WS` | `/v1/analytics/ws/events` | Real-time event stream (WebSocket) |

**ML Serving**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/v1/ml/models` | List registered ML models |
| `POST` | `/v1/ml/predict` | Single prediction |
| `POST` | `/v1/ml/predict/batch` | Batch predictions |
| `GET` | `/v1/ml/features/{id}` | Feature serving |

**Agent**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/v1/agent/status` | Agent system status |
| `POST` | `/v1/agent/tasks` | Submit a task to the agent |
| `GET` | `/v1/agent/tasks/{id}` | Get task status |
| `GET` | `/v1/agent/audit` | Audit trail |
| `POST` | `/v1/agent/kill-switch` | Emergency kill switch |

**Campaign**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/v1/campaigns` | List campaigns |
| `POST` | `/v1/campaigns` | Create a campaign |
| `GET` | `/v1/campaigns/{id}` | Get a campaign |
| `PATCH` | `/v1/campaigns/{id}` | Update a campaign |
| `DELETE` | `/v1/campaigns/{id}` | Delete a campaign |
| `GET` | `/v1/campaigns/{id}/attribution` | Get campaign attribution data |

**Consent**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/v1/consent/records` | Record user consent |
| `GET` | `/v1/consent/records/{user_id}` | Get consent records for a user |
| `POST` | `/v1/consent/dsr` | Submit a data subject request |
| `GET` | `/v1/consent/dsr` | List data subject requests |

**Notification**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/v1/notifications/webhooks` | Create a webhook |
| `GET` | `/v1/notifications/webhooks` | List webhooks |
| `DELETE` | `/v1/notifications/webhooks/{id}` | Delete a webhook |
| `POST` | `/v1/notifications/alerts` | Create an alert |
| `GET` | `/v1/notifications/alerts` | List alerts |

**Admin**
| Method | Path | Description |
| ------ | ---- | ----------- |
| `POST` | `/v1/admin/tenants` | Create a tenant |
| `GET` | `/v1/admin/tenants/{id}` | Get tenant details |
| `PATCH` | `/v1/admin/tenants/{id}` | Update a tenant |
| `POST` | `/v1/admin/tenants/{id}/api-keys` | Create an API key for a tenant |
| `GET` | `/v1/admin/tenants/{id}/api-keys` | List API keys for a tenant |
| `DELETE` | `/v1/admin/api-keys/{id}` | Revoke an API key |
| `GET` | `/v1/admin/tenants/{id}/billing` | Get tenant billing data |

</details>

---

## Authentication & Authorization

Every request to a non-public path must carry credentials. The middleware attempts API key authentication first, then falls back to JWT Bearer tokens.

### Authentication Methods

| Method | Header | Format | Use Case |
| ------ | ------ | ------ | -------- |
| **API Key** | `X-API-Key` | `ak_<key>` | Server-to-server, SDK integrations |
| **JWT Bearer** | `Authorization` | `Bearer <token>` | User sessions, dashboard access |

**Public (unauthenticated) paths:** `/`, `/health`, `/v1/health`, `/docs`, `/openapi.json`, `/redoc`

### Roles (4)

| Role | Description |
| ---- | ----------- |
| `admin` | Full access to all resources and operations. Bypasses all permission checks. |
| `editor` | Read and write access. Can manage campaigns, agents, and consent. |
| `viewer` | Read-only access to analytics, profiles, and campaigns. |
| `service` | Machine-to-machine role for internal service communication. |

### Permissions (10)

| Permission | Scope |
| ---------- | ----- |
| `read` | Read access to profiles, events, and campaigns |
| `write` | Create and update profiles, events, and campaigns |
| `delete` | Delete campaigns, webhooks, and API keys |
| `analytics` | Query events, dashboards, export data |
| `ml:inference` | Run predictions and access feature serving |
| `agent:manage` | Submit tasks, view audit trail, trigger kill switch |
| `campaign:manage` | Full campaign lifecycle management |
| `consent:manage` | Record consent, manage data subject requests |
| `admin` | Tenant management and API key provisioning |
| `billing` | Access billing and usage data |

### Rate Limiting

Rate limiting is enforced per API key using a token bucket algorithm. Limits are tiered:

| Tier | Requests per Minute |
| ---- | ------------------- |
| `free` | 60 |
| `pro` | 600 |
| `enterprise` | 6,000 |

Rate limit status is communicated via response headers:

```
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 594
X-RateLimit-Reset: 1709472000
```

### Tenant Isolation

Every authenticated request is scoped to a `TenantContext` that carries `tenant_id`, `user_id`, `role`, `api_key_tier`, and `permissions`. All data queries are filtered by `tenant_id` to enforce strict multi-tenant isolation.

---

## Installation

### Prerequisites

- Python 3.11 or later
- (Optional) Docker and Docker Compose for local data stores

### Clone and Install

```bash
git clone <repository-url>
cd "Backend Architecture/aether-backend"

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# Install core dependencies
pip install -e .

# Install with all production dependencies
pip install -e ".[all]"

# Install development dependencies
pip install -e ".[dev]"
```

### Dependency Groups

| Group | Command | Includes |
| ----- | ------- | -------- |
| Core | `pip install -e .` | FastAPI, Uvicorn, Pydantic |
| Databases | `pip install -e ".[databases]"` | asyncpg, redis, aioboto3, opensearch-py, gremlinpython |
| Kafka | `pip install -e ".[kafka]"` | aiokafka |
| All | `pip install -e ".[all]"` | Databases + Kafka + httpx + prometheus-client |
| Dev | `pip install -e ".[dev]"` | pytest, pytest-asyncio, httpx, ruff, mypy |

---

## Quick Start

```bash
# 1. Activate the virtual environment
source .venv/bin/activate

# 2. (Optional) Set environment variables -- defaults work for local development
export AETHER_ENV=local
export DEBUG=true

# 3. Start the server
uvicorn main:app --reload --port 8000

# 4. Verify the server is running
curl http://localhost:8000/
# => {"name": "Aether API", "version": "v1", "docs": "/docs", "health": "/v1/health"}

# 5. Check the health endpoint
curl http://localhost:8000/v1/health

# 6. Make an authenticated request (using the stub API key)
curl -H "X-API-Key: ak_test_123" http://localhost:8000/v1/analytics/dashboard/summary

# 7. Open interactive API docs
open http://localhost:8000/docs
```

---

## Configuration Reference

All configuration is sourced from environment variables with sensible defaults. See `config/settings.py` for the full definition.

### Application

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `AETHER_ENV` | `local` | Environment: `local`, `dev`, `staging`, `production` |
| `DEBUG` | `true` | Enable debug mode and hot-reload |
| `CORS_ORIGINS` | `http://localhost:3000,https://app.aether.io` | Comma-separated allowed CORS origins |
| `MAX_REQUEST_BODY_MB` | `10` | Maximum request body size in megabytes |

### TimescaleDB (PostgreSQL)

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `TSDB_HOST` | `localhost` | Database host |
| `TSDB_PORT` | `5432` | Database port |
| `TSDB_DATABASE` | `aether` | Database name |
| `TSDB_USER` | `aether` | Database user |
| `TSDB_PASSWORD` | *(empty)* | Database password |
| `TSDB_POOL_MIN` | `5` | Minimum connection pool size |
| `TSDB_POOL_MAX` | `20` | Maximum connection pool size |

### Amazon Neptune

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `NEPTUNE_ENDPOINT` | `localhost` | Neptune cluster endpoint |
| `NEPTUNE_PORT` | `8182` | Neptune port |
| `AWS_REGION` | `us-east-1` | AWS region (shared with other AWS services) |

### Redis

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis database number |
| `REDIS_PASSWORD` | *(empty)* | Redis password |
| `REDIS_POOL_SIZE` | `10` | Connection pool size |

### DynamoDB

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `DYNAMODB_ENDPOINT` | *(empty)* | Custom endpoint (for local DynamoDB) |
| `DYNAMODB_TABLE_PREFIX` | `aether_` | Table name prefix |

### OpenSearch

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `OPENSEARCH_ENDPOINT` | `localhost` | OpenSearch domain endpoint |
| `OPENSEARCH_PORT` | `9200` | OpenSearch port |

### Event Bus

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `EVENT_BROKER` | `kafka` | Broker type: `kafka` or `sns_sqs` |
| `KAFKA_BROKERS` | `localhost:9092` | Kafka bootstrap servers |
| `KAFKA_CONSUMER_GROUP` | `aether-backend` | Kafka consumer group ID |
| `SNS_TOPIC_ARN` | *(empty)* | SNS topic ARN (when using `sns_sqs`) |
| `SQS_QUEUE_URL` | *(empty)* | SQS queue URL (when using `sns_sqs`) |

### Authentication

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `JWT_SECRET` | `change-me-in-production` | HMAC secret for JWT signing |
| `JWT_EXPIRY_MINUTES` | `60` | JWT token expiry in minutes |

---

## Development Commands

```bash
# Run the development server with hot-reload
uvicorn main:app --reload --port 8000

# Run as a Python module (alternative)
python main.py

# Run the test suite
pytest

# Run tests with async support
pytest --asyncio-mode=auto

# Lint with Ruff
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Format code
ruff format .

# Type check with mypy (strict)
mypy .

# Run all quality checks
ruff check . && ruff format --check . && mypy . && pytest
```

### Project Structure

```
aether-backend/
|-- main.py                     # Application entrypoint and router mounting
|-- pyproject.toml              # Project metadata and dependencies
|-- config/
|   +-- settings.py             # 12-Factor environment configuration
|-- dependencies/
|   +-- providers.py            # DI registry and FastAPI dependency functions
|-- middleware/
|   +-- middleware.py            # Auth, rate limiting, logging, error handling
|-- repositories/
|   +-- repos.py                # Repository pattern for all data stores
|-- services/
|   |-- gateway/routes.py       # Health, root, metrics
|   |-- ingestion/routes.py     # Event intake
|   |-- identity/routes.py      # Profile CRUD, merge, graph
|   |-- analytics/routes.py     # Queries, dashboards, export, GraphQL, WS
|   |-- ml_serving/routes.py    # Models, predictions, features
|   |-- agent/routes.py         # Tasks, audit, kill switch
|   |-- campaign/routes.py      # Campaign lifecycle, attribution
|   |-- consent/routes.py       # Consent records, DSR
|   |-- notification/routes.py  # Webhooks, alerts
|   |-- admin/routes.py         # Tenants, API keys, billing
|   +-- traffic/routes.py       # Automatic traffic source tracking and attribution
+-- shared/
    |-- common/common.py        # Error classes, response formatters, validation
    |-- auth/auth.py            # JWT, API key validation, roles, permissions
    |-- cache/cache.py          # Redis cache client
    |-- events/events.py        # Kafka/SNS event producer and consumer
    |-- graph/graph.py          # Neptune graph client
    +-- rate_limit/limiter.py   # Token bucket rate limiter
```

---

## License

Proprietary. All rights reserved. Unauthorized copying, modification, distribution, or use of this software is strictly prohibited without prior written permission from the Aether team.
