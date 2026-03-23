# Operations Runbook v8.3.1

Operations guide for the Aether backend services.

> **Infrastructure status:** The application logic, API contracts, and error handling described in this runbook are fully implemented. However, the data persistence layer (graph, events, cache, repositories) currently uses **in-memory stubs**. The failure behaviors described below are accurate for the application layer, but data will not survive process restarts until real infrastructure (Neptune, Kafka, Redis, PostgreSQL) is connected. See `PRODUCTION-READINESS.md` for the full infrastructure integration checklist.

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

---

## Concurrency Safety

All in-memory stores use `threading.Lock` for thread-safe access:

| Store | Lock | Service |
|-------|------|---------|
| `_touchpoint_store` | `_touchpoint_lock` | Campaign |
| `_export_jobs` | `_export_lock` | Analytics |
| `_task_store` + `_audit_store` | `_task_lock` | Agent |
| `_http_client` | `_client_lock` | ML Serving |

Production note: Replace in-memory stores with Redis/TimescaleDB for horizontal scaling.
