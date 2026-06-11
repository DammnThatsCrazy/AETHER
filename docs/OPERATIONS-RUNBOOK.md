---
title: Operations Runbook
slug: operations/runbook
section: operations
visibility: I
audience: [ops]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/main.py
  - deploy/staging/bootstrap.sh
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: 5316c08
---
# Operations Runbook v8.8.0

Operations guide for the Aether backend services.

## Extraction Defense Mesh Operations

### Enabling the Mesh

Set `ENABLE_EXTRACTION_MESH=true` in environment. The mesh requires Redis for distributed budget enforcement in staging/production. In local mode, it falls back to in-memory counters.

### Monitoring

- **Dashboard**: `GET /v1/intelligence/extraction/overview` — system-wide overview
- **Alerts**: `GET /v1/intelligence/extraction/alerts` — recent extraction alerts
- **Actor profiles**: `GET /v1/intelligence/extraction/actor/{id}` — per-actor risk
- **ML Serving**: `GET /v1/defense/metrics` — defense layer metrics

### Alert Response

| Alert | Action |
|-------|--------|
| Red band spike | Check `/v1/intelligence/extraction/alerts` for affected actors. Consider adding to blocklist. |
| High block rate (>30%) | Verify thresholds aren't too aggressive. Check for false positives. |
| Canary hit | Investigate the API key. Check lineage records for extraction patterns. |
| Cluster escalation | Review linked identities in `/v1/intelligence/extraction/clusters`. |

### Tuning

- Budget limits are in `shared/rate_limit/budget_policies.py`
- Signal weights are in `shared/scoring/extraction_score.py`
- Band thresholds are in `shared/scoring/extraction_models.py`
- Privileged callers: `EXTRACTION_PRIVILEGED_TENANTS`, `EXTRACTION_PRIVILEGED_API_KEYS`

### Redis Key Schema

All extraction mesh keys use prefix `aether:exbudget:`:
- `aether:exbudget:{axis}:{id}:{window}:{bucket}` — budget counters
- `aether:exbudget:fp:{axis}:{id}` — feature fingerprint HLL
- `aether:exbudget:models:{axis}:{id}` — model enumeration sets
- `aether:exhist:{actor_key}` — actor request history (2h TTL)

### Failure Modes

| Component | Failure | Behavior | Recovery |
|-----------|---------|----------|----------|
| Redis | Unreachable | Falls back to in-memory budgets | Auto-reconnect on next request |
| Budget engine | Timeout | Request allowed (fail-open) | Redis recovery |
| Expectation engine | Error | Signals empty, score defaults green | Automatic |
| Policy engine | Error | Default allow policy | Automatic |

---

> **Infrastructure status:** All infrastructure backends are production-implemented: PostgreSQL (asyncpg) for repositories, Redis (redis.asyncio) for cache and rate limiting, Neptune (gremlinpython) for graph, Kafka (aiokafka) for events, Prometheus for metrics. In local development (`AETHER_ENV=local`), the system falls back to in-memory backends automatically. In staging/production, real backends are required — missing connections produce a `RuntimeError` at startup (fail-closed). See `PRODUCTION-READINESS.md` for the full deployment checklist.

---

## Failure Mode Matrix

| Service | Failure | System Behavior | Recovery |
|---------|---------|----------------|----------|
| **Campaign Attribution** | No touchpoints for campaign | Returns `conversions: 0, touchpoints: []` (graceful) | Normal — no touchpoints recorded yet |
| | Invalid attribution model | Returns `400 Bad Request` with valid model list | Client corrects model parameter |
| | Campaign not found / wrong tenant | Returns `404 Not Found` (no data leak) | Client uses correct campaign ID |
| **Analytics Export** | Query fails mid-export | Job status set to `failed`, error sanitized (no internal details) | Retry via `POST /export` (idempotent) |
| | Duplicate export request | Returns existing job (idempotency) | No action needed |
| | Job not found / wrong tenant | Returns `404 Not Found` | Client uses correct export ID |
| **Analytics GraphQL** | Introspection attempt | Returns `400 Introspection is disabled` | By design — blocks schema enumeration |
| | Query too deep (>5 levels) | Returns `400 Query too deep` | Client simplifies query |
| | Invalid/unknown fields | Returns `400 Unknown fields` with specifics | Client corrects field names |
| **Agent Tasks** | Invalid worker type | Returns `400 Unknown worker type` with valid list | Client corrects worker_type |
| | Kafka publish failure | Task created in store but event not published | Monitor Kafka health; task visible via `GET /tasks/{id}` |
| | Task not found / wrong tenant | Returns `404 Not Found` | Client uses correct task ID |
| **IP Geo-Enrichment** | MaxMind DB missing | Enrichment returns empty geo fields (graceful) | Install GeoLite2 DB at `GEOIP_DB_PATH` |
| | maxminddb not installed | Enrichment disabled, warning logged once | `pip install maxminddb` |
| | Private/reserved IP | Returns immediately with empty geo (fast path) | Normal — private IPs have no geo data |
| | Invalid IP format | Returns empty geo, debug log | Normal — malformed IP from proxy headers |
| **ML Serving Proxy** | ML API unreachable | Returns `503 Service Unavailable` | Check ML serving container health |
| | ML API returns non-200 | Returns `503` with status code detail | Check ML model loading status |
| | ML API returns invalid JSON | Returns `503 Malformed response` | Check ML serving logs |
| | Cache miss + ML API down | Returns `503` (no stale cache fallback) | Restore ML serving container |

---

## Environment Variables Checklist

### Required in Production

| Variable | Service | Notes |
|----------|---------|-------|
| `JWT_SECRET` | All | Must differ from default `change-me-in-production` |
| `WATERMARK_SECRET_KEY` | ML Serving | Must differ from default when defense enabled |
| `PROVIDER_GATEWAY_ENCRYPTION_KEY` | Backend | Must be set when provider gateway enabled |
| `GEOIP_DB_PATH` | Ingestion | Path to MaxMind GeoLite2-City.mmdb |
| `GEOIP_ASN_DB_PATH` | Ingestion | Path to MaxMind GeoLite2-ASN.mmdb |

### Recommended

| Variable | Default | Service |
|----------|---------|---------|
| `ML_SERVING_URL` | `http://localhost:8080` | Backend ML proxy |
| `REDIS_HOST` | `localhost` | All caching |
| `KAFKA_BROKERS` | `localhost:9092` | Event bus |
| `ENABLE_EXTRACTION_DEFENSE` | `false` | ML Serving |
| `PRICING_OPTION` | `B` | Backend (A/B/C — Market Entry / Ideal / Premium) |
| `QUOTA_REDIS_TTL_DAYS` | `35` | Backend (retention for `rl:quota:*` and `rl:overage:*`) |
| `QUOTA_FLUSH_INTERVAL_S` | `60` | Backend (Redis → `tenant_usage` flush cadence) |

---

## Self-Serve Plans & Rate Limiting

Aether enforces three layers in the middleware chain (auth → burst RPM →
feature gate → monthly quota → handler). All four self-serve plans
(P1-P4) share one configuration; pricing is selected globally via
`PRICING_OPTION`.

### Per-Plan Limits

| Plan | Burst RPM | Monthly Quota | Members | Services |
|------|-----------|---------------|---------|----------|
| P1 Hobbyist | 100 | 25,000 | 1 | 10 |
| P2 Professional | 500 | 100,000 | 3 | 19 |
| P3 Growth Intelligence | 1,200 | 250,000 | 5 | 29 |
| P4 Protocol Master | 3,000 | 500,000 | 10 | 34 |

### Redis Key Schema (rate limiting)

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `rl:burst:{tenant_id}:{minute_ts}` | INCR | 120s | Burst RPM counter |
| `rl:quota:{tenant_id}:{YYYY-MM}` | INCR | 35 days | Monthly request counter |
| `rl:overage:{tenant_id}:{YYYY-MM}` | HASH | 35 days | Per-service overage counts |
| `rl:notified:{tenant_id}:{YYYY-MM}` | SET | 35 days | Threshold notification dedup |

### Quota Flusher

A background task in `dependencies/providers.py` calls
`QuotaFlusher.flush_once()` every `QUOTA_FLUSH_INTERVAL_S` seconds. It
upserts each Redis quota counter into the `tenant_usage` PostgreSQL
table (created idempotently on first run by `quota_flush.py`).

To trigger an immediate flush during an incident:
```python
from dependencies.providers import get_registry
await get_registry().quota_flusher.flush_once()
```

### Failure Modes

| Layer | Redis down | Behavior |
|-------|-----------|----------|
| Burst RPM | Unreachable | Fail open + `aether_redis_fallback{layer="burst"}` increments |
| Feature gate | N/A (in-memory) | Always available |
| Monthly quota | Unreachable | Fail open + `aether_redis_fallback{layer="quota"}` increments |

The `RateLimitRedisFallbackActive` alert fires within 1 minute of any
fallback event. While Redis is degraded, billing data is captured
in-memory only and is **not durable** until Redis returns.

### Switching Pricing Options

`PRICING_OPTION` is read once at startup. To switch:
1. Update env var (e.g. `PRICING_OPTION=C`).
2. Restart all backend pods. The validator in `Settings.__post_init__`
   raises if the value is not `A`, `B`, or `C`.
3. Existing in-flight overage Redis counts are unaffected; only the
   `OverageCalculator` rate sheet changes.

---

## Health Checks

| Service | Endpoint | Expected |
|---------|----------|----------|
| Backend | `GET /v1/health` | `{"status": "healthy"}` |
| ML Serving | `GET /health` | `{"status": "healthy", "models_loaded": [...]}` |
| Defense | `GET /v1/defense/status` | `{"enabled": true/false}` |

---

## Incident Playbooks

### Failed Exports

1. Check `GET /v1/analytics/export/{id}` for job status
2. If `status: "failed"`, check backend logs for `Export query failed for job`
3. Verify Redis connectivity (exports depend on query cache)
4. Re-submit export — idempotency returns existing completed jobs

### Kafka Topic Provisioning

All 114 Kafka topics are provisioned by `deploy/staging/kafka_topics.sh`, called automatically from `bootstrap.sh` after leader election. If topics are missing:

1. Run `deploy/staging/kafka_topics.sh` manually — it uses `--if-not-exists` so re-running is safe
2. Required env var: `KAFKA_BOOTSTRAP` (default: `localhost:9092`)
3. Partitions: 12 for high-throughput topics, 6 for standard, 3 for audit
4. Retention: 7 days (standard), 14 days (high-throughput), 90 days (audit)

### Kafka Backlog

1. Check `docker compose logs kafka` for consumer lag
2. Verify consumer group offsets: `kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group aether-backend`
3. If agent task events are stuck, tasks are still in `_task_store` — accessible via `GET /v1/agent/tasks/{id}`

### GeoIP Database Issues

1. Check ingestion logs for `GeoIP city database loaded` on startup
2. If missing: `maxminddb package not installed` or `Failed to load GeoIP database`
3. Download from MaxMind: `https://dev.maxmind.com/geoip/geolite2-free-geolocation-data`
4. Set `GEOIP_DB_PATH=/path/to/GeoLite2-City.mmdb`
5. Restart ingestion service — lazy loading will pick up the new DB

### ML Serving Down

1. Check `GET /health` on ML serving (port 8080)
2. Check `docker compose logs ml-serving` for model loading errors
3. Backend proxy returns `503` — clients should retry with exponential backoff
4. Cached predictions still served for previously-seen entities

---

## Security Boundaries

| Boundary | Implementation |
|----------|---------------|
| Tenant isolation | All data stores filter by `tenant_id`; cross-tenant access returns `404` |
| Permission checks | `require_permission()` called before state-mutating operations |
| Export job access | Job retrieval checks `tenant_id` match |
| Agent task access | Task retrieval checks `tenant_id` match |
| Campaign access | GET, attribution, touchpoint all verify `tenant_id` |
| GraphQL introspection | Disabled (`__schema`, `__type` blocked) |
| GraphQL depth | Limited to 5 levels, 20 fields per query |
| Error messages | Internal details never leaked to clients |
| WebSocket auth | First message must authenticate; errors are generic |
| IP data | Raw IPs never logged; only hashed values persisted |

### No-auth endpoints (registration & recovery)

These endpoints intentionally bypass API-key auth — operators should monitor them
for abuse and ensure IP rate-limiting is active:

| Endpoint | Purpose |
|---|---|
| `POST /v1/tenants` | Public tenant sign-up |
| `POST /v1/auth/register` | Email sign-up step 1 (send OTP) |
| `POST /v1/auth/verify-email` | Email sign-up step 2 (verify OTP, create tenant) |
| `POST /v1/auth/resend-verification` | Resend OTP |
| `POST /v1/auth/login` | Email + password → API key |
| `POST /v1/auth/sso/callback` | SSO via Auth0 JWT → API key |
| `GET  /v1/auth/sso/providers` | List configured SSO providers |
| `POST /v1/auth/recover` | Recover lost API key via email |

The Stripe webhook (`POST /v1/admin/billing/stripe/webhook`) is also unauthenticated
at the HTTP layer but verifies a Stripe-signed payload — failures should alert.

### Background tasks running in the app lifespan

| Task | Module | Cadence |
|---|---|---|
| Monthly overage invoice cron | `services/billing/cron.run_monthly_overage_cron` | end-of-month billing cycle |

These start during app `lifespan` startup and are cancelled on shutdown. Restart loops
during deploys are normal; persistent failures should page billing oncall.

---

## Concurrency Safety

All data access goes through `BaseRepository` (asyncpg PostgreSQL) which provides connection pooling and transactional safety. In-memory fallbacks are only used in `AETHER_ENV=local` for development:

| Layer | Backend | Concurrency Model |
|-------|---------|-------------------|
| Repositories | PostgreSQL (asyncpg pool) | Connection pool with async I/O |
| Cache | Redis (redis.asyncio) | Atomic INCR/EXPIRE for rate limiting |
| Graph | Neptune (gremlinpython) | Connection per query |
| Events | Kafka (aiokafka) | Producer/Consumer with async I/O |
| ML Serving Proxy | `httpx.AsyncClient` | Connection pooling with `_client_lock` |

All stores support horizontal scaling natively through their backend implementations.

---

## Kafka Consumer Lag Spike

### Detection

- Prometheus alert: `aether_kafka_consumer_lag > 10000` sustained for 5 minutes
- Grafana "Event Bus" dashboard → Consumer Group Lag panel
- `GET /v1/diagnostics/report` → `event_bus` field shows `"degraded"` or `"error"`

### Triage

1. Check overall lag: `GET /v1/diagnostics/health` → inspect `event_bus` status
2. Identify the lagging consumer group:
   ```
   kafka-consumer-groups.sh --bootstrap-server $KAFKA_BOOTSTRAP \
     --describe --group aether-backend
   ```
3. Check ECS task count for the backend service — unexpected scale-in causes consumer group rebalancing, which temporarily stalls progress

### Remediation

| Lag Pattern | Cause | Action |
|-------------|-------|--------|
| Steady lag growth | Consumer is slower than producer | Scale ECS tasks; check for expensive downstream calls |
| Lag spikes then recovers | Rebalancing after scale event | Wait 60s for group to stabilise |
| Lag frozen on one partition | Poison-pill message | Use console consumer to inspect the offset, skip with `--to-offset` |
| Lag spike after deploy | Schema change in event envelope | Restart consumers after confirming schema compatibility |
| Lag > 50K, not recovering after 10 min | Broker-side issue | Check CloudWatch MSK metrics for broker CPU and disk; page on-call |

### Recovery Verification

Lag should return to < 1000 within 5 minutes of remediation. Monitor via Grafana dashboard.

---

## Neptune / Graph DB Unavailable

### Detection

- `GET /v1/diagnostics/health` → `"graph": "error"` or `"graph": "degraded"`
- `GET /v1/diagnostics/circuit-breakers` → graph breaker in `"open"` state
- CloudWatch Neptune metric `ServerlessDatabaseCapacity` drops to 0

### Impact Scope

Services affected (degraded responses, not errors):
- `GET /v1/identity/profiles/{id}/graph` — profile graph traversal
- `POST /v1/identity/merge` — identity merge edge writes
- `GET /v1/agent/*` routes that query A2H relationships

Services **unaffected** (Neptune is not in the hot path):
- All ingestion, analytics, ML serving, billing, fraud, attribution, rewards, oracle endpoints continue normally

### Triage

1. Confirm graph client state: `GET /v1/diagnostics/circuit-breakers` — if breaker is `"open"`, the graph client has already tripped and is preventing cascading load
2. Check Neptune cluster status in AWS Console → Amazon Neptune → Clusters
3. Review CloudWatch metrics: `GremlinRequestsPerSec`, `CPUUtilization`, `DatabaseConnections`

### Remediation

| State | Action |
|-------|--------|
| Circuit breaker `"open"` | Self-heals after `PROVIDER_CB_TIMEOUT_S` (default 30s) recovery check — no action required |
| Neptune cluster stopped | Start cluster via AWS Console; graph client reconnects automatically on next request |
| Neptune cluster unreachable (VPC issue) | Check security group rules — port 8182 must be open from ECS task SG to Neptune SG |
| Half-open, single request fails | Breaker re-opens; wait another 30s cycle |

### Post-Recovery Verification

Circuit breaker transitions to `"closed"` automatically after the first successful Gremlin request. Confirm via `GET /v1/diagnostics/circuit-breakers`.

---

## Stripe Webhook Retry / Stuck Event

### Detection

- Stripe Dashboard → Developers → Webhooks → select endpoint → Failed deliveries tab
- Prometheus counter `stripe_webhook_sig_failures` spiking (signature failures, not handler errors)
- Application logs: `ERROR Stripe webhook handler failed` on `POST /v1/admin/billing/stripe/webhook`

### How Retries Work

The handler uses an idempotency claim: it inserts `event_id` into `stripe_webhook_events` before processing. On handler failure (5xx), the claim is released (`DELETE` from the table) so Stripe's next retry attempt is treated as new. This means **Stripe retries heal automatically** for transient failures.

### Triage

| Symptom | Likely Cause | Next Step |
|---------|-------------|-----------|
| 400 responses | Invalid `Stripe-Signature` — webhook secret mismatch | Verify `STRIPE_WEBHOOK_SECRET` matches the endpoint secret in Stripe Dashboard |
| 500 responses, then 200 on retry | Transient DB error or downstream unavailability | Monitor — retries self-heal; check DB health |
| 500 responses, not recovering | Tenant not found in `tenant_billing_accounts` | Tenant was not provisioned before subscription creation; manually upsert the billing account row |
| Event appears stuck in DB | Idempotency claim not released (process killed mid-handler) | Run: `DELETE FROM stripe_webhook_events WHERE event_id = '<id>';` |

### Manual Re-Trigger

Use Stripe Dashboard: select the failed event → "Resend" button. Alternatively, use the Stripe CLI:
```
stripe events resend <evt_xxxxxxxx> --webhook-endpoint=<we_xxxxxxxx>
```

### Escalation

If an event type is consistently failing after 3 Stripe retry cycles (Stripe retries over 72 hours with exponential backoff), investigate the specific handler (`_handle_<event_type>` in `services/admin/webhook_routes.py`) and consider adding the event to a dead-letter queue for manual reprocessing.
