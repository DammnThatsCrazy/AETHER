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
  - Backend Architecture/aether-backend/config/settings.py
  - Backend Architecture/aether-backend/services/provider_runtime/
  - deploy/legacy-staging/bootstrap.sh
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: "4839590b"
---
# Operations Runbook v8.12.0

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
| `ledger_chain_integrity` (P1) | A tenant's Bronze/outbox hash chain failed `verify_chain` — a chained row was deleted, edited, or reordered. Inspect `GET /v1/security/ledger/chain-verification?tenant_id=<id>` for `break_location`/`broken_record_ids`, then investigate that tenant's ingestion path. |

### Ledger chain verifier

The `ledger_chain_verifier` supervised worker re-walks each tenant's append-only
Bronze/outbox hash chain and pages a P1 `ledger_chain_integrity` alert on any
break. It is **off by default**; enable with `LEDGER_CHAIN_VERIFIER_ENABLED=1`
(cadence `LEDGER_CHAIN_VERIFIER_INTERVAL_SECONDS`, default 6h). The read
surface `GET /v1/security/ledger/chain-verification` (operator-gated) exposes
per-tenant status and the verified / verification-failure dashboard aggregate.

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

## Model Runtime Operations (v8.12.0)

The multi-model intelligence harness (`services/model_runtime/`) is
feature-gated OFF by default (`MODEL_RUNTIME_ENABLED=false`, ADR-008 D9).
While OFF the `/v1/model-runtime/*` routes are inert — every request returns
HTTP 503 `model_runtime_disabled` and no data is served.

**Enabling in staging/production.** Set `MODEL_RUNTIME_ENABLED=true` and —
because the runtime fails closed in non-local environments — a
production-safe credential backend (`MODEL_RUNTIME_CREDENTIAL_BACKEND=env` or
`aws_secrets`, never `in_memory`/`disabled`) and a real default provider
(never `deterministic`, which is test-only). A violation raises `ConfigError`
at startup and the process refuses to serve rather than falling back to an
insecure default. With `credential_backend=aws_secrets`,
`MODEL_RUNTIME_CREDENTIAL_AWS_REGION` is also required. All `MODEL_RUNTIME_*`
variables are declared in `.env.example` and
`deploy/model-runtime/.env.example`; `services/model_runtime/config.py` is the
single source for defaults and the fail-closed rules.

**Tenant scoping.** Tenant scope is server-authoritative: the tenant is derived
from the authenticated request state (bound by the auth middleware) — a client
can never select tenant scope from headers, body, or query. The Aether tenant
surfaces (`models`, `tenant-default`) reject with HTTP 400 `tenant_required`
when no authenticated tenant is present (fail-closed). The Kyber operator
surfaces `registry`/`health`/`usage` are global — operator-authorized only, no
per-tenant data, no tenant scope required — so a tenantless workforce operator
is served. The tenant-scoped Kyber surfaces (`entitlements`, `traces`) resolve
their scope from the Kyber workforce access context when a workforce session is
present (a workforce actor is intentionally tenantless), else the legacy tenant
binding; a workforce session whose access context carries no tenant scope fails
closed with HTTP 403 `tenant_scope_required`.

**Credential hygiene.** Responses are credential-free; health/entitlement
reasons are sanitized. Never place API keys or secrets in the env templates —
placeholders only.

**Health.** `GET /v1/model-runtime/health` reports per-provider
configured/healthy state over the deterministic seed set until real adapters
are wired; `status` ∈ `ok` / `degraded` / `unhealthy`. Probes are
liveness-light and never invoke a provider `complete` call.

**Circuit breakers.** Provider dispatch is gated by a circuit registry keyed
per provider + model (+ tenant scope). After
`MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD` (default 5) consecutive failures a
circuit opens and calls are blocked fail-closed until
`MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S` (default 60s) elapses, then a
single half-open probe is allowed. Misconfigured thresholds (threshold < 1 or
recovery < 0) fail closed at startup.

---

## Incident Playbooks

### Failed Exports

1. Check `GET /v1/analytics/export/{id}` for job status
2. If `status: "failed"`, check backend logs for `Export query failed for job`
3. Verify Redis connectivity (exports depend on query cache)
4. Re-submit export — idempotency returns existing completed jobs

### Kafka Topic Provisioning

All 114 Kafka topics are provisioned by `deploy/legacy-staging/kafka_topics.sh`, called automatically from `bootstrap.sh` after leader election. If topics are missing:

1. Run `deploy/legacy-staging/kafka_topics.sh` manually — it uses `--if-not-exists` so re-running is safe
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
| SLA expiry worker | `services/notification_intelligence.lifecycle.start_sla_worker` | continuous (event-driven) |
| Dune polling worker | `services/dune_feeder.scheduler.start_dune_polling_worker` | 60 s tick; per-schedule cadence ≥ 300 s |

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

## Reward Enablement (A6) Operations

### Oracle Signer Key Safety

The reward proof signer uses `ORACLE_SIGNER_KEY`. In non-local environments, the default Hardhat/Anvil test key (`ac0974bec...`) is **blocked at startup** — the process raises `RuntimeError` before accepting traffic.

| Env | Behavior |
|-----|----------|
| `AETHER_ENV=local` | Default test key allowed (development only) |
| `AETHER_ENV=staging/production` | `ORACLE_SIGNER_KEY` must be set via secret manager; test key rejected |

If the backend fails to start with `ORACLE_SIGNER_KEY not set` or `Default Hardhat/Anvil test key detected`, set the key via the configured secret manager ref in `REWARD_SIGNER_KEY_REF`.

### Reward Delivery Monitoring

| Alert | Action |
|-------|--------|
| Webhook delivery failures | Check `reward_action_payloads` rows where `status='failed'`; review `last_delivery_error`; re-trigger via `POST /v1/rewards/actions/{id}/deliver` |
| Dead-letter queue depth | Kafka DLT `aether.rewards.delivery.dlq` — inspect failed payloads; fix rail config → re-enqueue |
| Proof generation failures | `ORACLE_SIGNER_KEY` misconfigured or contract not in tenant registry; check `reward_proofs` status |
| Fraud block rate spike | Legitimate `blocked_fraud` — review fraud thresholds; check `reward_eligibility_decisions` where `decision='blocked_fraud'` |

### Durable Storage Guard

`REWARD_REQUIRE_DURABLE_STORE=true` causes startup failure in non-local environments if database is unreachable. All reward state (campaigns, rules, decisions, proofs, payloads, audit log) requires PostgreSQL — there is no in-memory fallback in production.

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

---

## Fraud Intelligence Services

Three services mount conditionally in `main.py` based on feature flags:

```
FEATURE_FRAUD_NETWORKS=true    → mounts services/fraud_networks router at /v1/fraud/networks
FEATURE_FLOW_TRACE=true        → mounts services/flow_trace router at /v1/flow-trace
FEATURE_RISK_OVERLAYS=true     → mounts services/risk_overlay router at /v1/risk-overlay
```

### Enabling

Set the flags in your environment and restart the service. No migrations are required — repositories auto-create their stores at startup.

### Health

When enabled, check network build latency via Prometheus counter `fraud_network_built_total` and `flow_trace_created_total`. Elevated latency on `POST /v1/fraud/networks/build` usually indicates graph client saturation — check `GET /v1/health` for the `graph` component.

### Disabling

Set the flag to `false` and restart. Existing stored artifacts are preserved in their respective stores and become accessible again if the flag is re-enabled. No data is deleted on disable.

---

## External Agent Telemetry Plane

Two additional routers mount conditionally in `main.py` (all default OFF):

```
AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED=true  → mounts services/agent/deployment_routes at /v1/agent/deployments
KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED=true    → mounts Kyber diagnostics at /v1/admin/kyber/agent-telemetry
```

Enable by setting the flags and restarting; the deployment registry persists
via the shared durable store (`agent_deployments` / `agent_deployment_audit`
tables — run Alembic migrations first in hosted modes). Disable by clearing
the flags and restarting; registry data is preserved. See
`docs/source-of-truth/EXTERNAL_AGENT_TELEMETRY_PLANE.md` for the full runbook.

---

## Universal Provider Runtime

The provider runtime mounts conditionally in `main.py` (all default OFF):

```
AETHER_PROVIDER_RUNTIME_ENABLED=true       → mounts provider_runtime router at /v1/provider-connections
                                              + webhook gateway at /v1/provider-webhooks
KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED=true → additionally mounts the operator plane at
                                              /v1/admin/kyber/provider-connections
AETHER_PROVIDER_ENTRY_POINTS_ENABLED=true  → enable importlib.metadata entry-point plugin discovery
```

Enable by setting the flags and restarting; provider registries auto-populate
at startup from local plugins plus (when entry points are enabled) installed
distribution entry points. Disable by clearing the flags and restarting;
stored provider connections/raw records are preserved. Webhook delivery is
fail-closed: a signature scheme without a configured secret denies the
delivery, and `endpoint_secret` providers require a constant-time-matching
presented token. See
`docs/UNIVERSAL-PROVIDER-RUNTIME.md` for the full runtime guide.

### Follow-on program flags

New flags from the UPR follow-on build (shipped state). They default OFF, so
the runtime stays additive until activated:

```
AETHER_PROVIDER_SYNC_SCHEDULER_ENABLED=true   → starts the `provider_sync_scheduler`
                                                 WorkerSpec (WS5): a periodic loop
                                                 that pulls due provider connections
                                                 on their schedules and writes sync
                                                 runs to the same durable ledger as
                                                 manual syncs
AETHER_PROVIDER_MIGRATIONS_ENABLED=true       → gates the config/secret migration
                                                 projection + apply routes (WS6)
AETHER_PROVIDER_LEGACY_DECOMMISSION=true      → gates the per-provider legacy
                                                 connector decommission route (WS7)
KYBER_PROVIDER_RUNTIME_UI_ENABLED=true        → enables the Kyber manifest-driven
                                                 provider UI (WS3)
```

Cadence for the scheduler is set by `AETHER_PROVIDER_SYNC_INTERVAL_SECONDS`
(default 3600s) and is re-read each pass, so a runtime toggle takes effect
without a restart. `AETHER_PROVIDER_SYNC_CRON` remains reserved (unimplemented)
— this build is interval-driven only.

**Scheduler role:** the `provider_sync_scheduler` loop rides the existing
**`materializer`** role (exact precedent: `payment_rail_sync`,
`bronze_object_compaction`, and the four Kyber loops all ride existing roles).
A single periodic loop does not justify a new runtime role and its
deploy-profile/compose/Terraform/topology-validator fan-out; running under
`materializer` keeps scheduled sync on the same durable ledger without a new
deploy artifact. Because it runs as the `materializer` principal (not a tenant
principal), scheduled sync never elevates a tenant principal's rights.
