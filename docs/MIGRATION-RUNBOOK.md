# Migration Runbook — Aether Platform v8.7.1

Procedures for deploying new versions of the Aether platform with zero or minimal downtime. Covers database migrations, service rollouts, and phased traffic shifting.

---

## Pre-Migration Checklist

- [ ] All P0 findings from `DEPLOYMENT_ASSESSMENT.md` are resolved
- [ ] All `[REQUIRED IN PRODUCTION]` environment variables are set (see `.env.example`)
- [ ] Secrets generated and stored in vault (see `docs/SECRET-ROTATION.md`)
- [ ] Database backups verified (PostgreSQL WAL archiving enabled, Redis RDB snapshot taken)
- [ ] ML model artifacts trained, versioned, and uploaded to artifact store
- [ ] Docker images built and pushed to registry with version tags
- [ ] Rollback plan reviewed and communicated to on-call team
- [ ] Maintenance window scheduled and communicated (if required)

---

## Phase 1: Infrastructure Preparation

### 1.1 Database Schema Changes

Aether does not use an automated migration framework (no Alembic/Flyway). Schema changes are applied manually via SQL scripts.

```bash
# 1. Connect to PostgreSQL
psql "${DATABASE_URL}"

# 2. Run migration scripts in order
\i migrations/001_schema_change.sql

# 3. Verify schema
\dt   # list tables
\d <table_name>  # inspect specific table
```

**Rules for safe schema changes:**

| Change Type | Safe to Run Live? | Notes |
|---|---|---|
| `ADD COLUMN ... DEFAULT NULL` | Yes | Non-blocking in PostgreSQL |
| `ADD COLUMN ... DEFAULT <value>` | Yes (PG 11+) | Non-blocking with default |
| `DROP COLUMN` | No | Deploy code that stops reading first, then drop in next release |
| `ALTER COLUMN TYPE` | No | Requires table rewrite; use blue-green |
| `CREATE INDEX CONCURRENTLY` | Yes | Non-blocking; must run outside transaction |
| `DROP INDEX` | Yes | Fast, non-blocking |
| `ADD CONSTRAINT` | Depends | `NOT VALID` + `VALIDATE CONSTRAINT` is safe |

### 1.2 Redis Cache

Redis schema changes are backward-compatible by design (key prefix namespacing). No explicit migration needed.

```bash
# Verify Redis connectivity
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD ping
# Expected: PONG

# Flush stale caches if schema changed (optional)
redis-cli -h $REDIS_HOST -p $REDIS_PORT KEYS "aether:cache:*" | xargs redis-cli DEL
```

### 1.3 Neptune Graph Database

Graph schema is additive (new vertex/edge labels). No migration tool exists.

```bash
# Verify Neptune connectivity
curl -s "https://${NEPTUNE_ENDPOINT}:${NEPTUNE_PORT}/status"
# Expected: {"status":"healthy"}
```

### 1.4 Kafka Topics

New topics are auto-created by producers. Verify topic configuration:

```bash
kafka-topics --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --list
kafka-topics --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --describe --topic aether-events
```

---

## Phase 2: Blue-Green Deployment (Recommended)

### 2.1 Build New Images

```bash
# Tag with version
export VERSION=v8.7.1
docker compose build
docker tag aether-backend:latest aether-backend:${VERSION}
docker tag aether-ml-serving:latest aether-ml-serving:${VERSION}
```

### 2.2 Deploy Green Stack

```bash
# Start green stack alongside blue (on different ports or behind LB)
docker compose -f docker-compose.green.yml up -d backend ml-serving

# Wait for health checks
until curl -sf http://localhost:8001/v1/health; do sleep 2; done
until curl -sf http://localhost:8081/health; do sleep 2; done
```

### 2.3 Validate Green Stack

Run the full smoke test checklist (see `docs/SMOKE-TEST-CHECKLIST.md`):

```bash
# Health
curl -s http://localhost:8001/v1/health | jq .

# Ingest test event
curl -s -X POST http://localhost:8001/v1/ingest/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_KEY}" \
  -d '{"events": [{"type": "test", "properties": {"key": "migration_check"}}]}'

# ML prediction
curl -s -X POST http://localhost:8081/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"model": "intent", "features": {"session_duration": 120}}'
```

### 2.4 Switch Traffic

```bash
# Update load balancer / reverse proxy to point to green
# For AWS ECS: update service desired count
# For Docker Compose: stop blue, rename green ports

docker compose stop backend ml-serving        # stop blue
docker compose -f docker-compose.green.yml \
  up -d --scale backend=2 --scale ml-serving=2  # scale green
```

### 2.5 Decommission Blue

After 15 minutes with no errors:

```bash
docker compose -f docker-compose.blue.yml down
```

---

## Phase 3: Rolling Deployment (Alternative — ECS/K8s)

For AWS ECS deployments managed via Terraform:

```bash
cd "AWS Deployment/aether-aws"

# Plan changes
terraform plan -var="image_tag=${VERSION}"

# Apply (ECS performs rolling update automatically)
terraform apply -var="image_tag=${VERSION}"

# Monitor deployment
aws ecs describe-services \
  --cluster aether-prod \
  --services aether-backend aether-ml-serving \
  --query 'services[].{name:serviceName,running:runningCount,desired:desiredCount,status:status}'
```

ECS rolling update settings (in Terraform):
- `minimumHealthyPercent`: 100 (no capacity loss)
- `maximumPercent`: 200 (deploy new before removing old)
- Deregistration delay: 30s

---

## Phase 4: Post-Migration Validation

Run the complete post-deploy verification checklist from `docs/SMOKE-TEST-CHECKLIST.md`.

### 4.1 Verify All Services Healthy

```bash
# Backend
curl -sf http://localhost:8000/v1/health | jq .

# ML Serving
curl -sf http://localhost:8080/health | jq .

# Prometheus
curl -sf http://localhost:9090/-/healthy
```

### 4.2 Verify Data Continuity

```bash
# Query events ingested before migration
curl -s -X POST http://localhost:8000/v1/analytics/events/query \
  -H "Authorization: Bearer ${API_KEY}" \
  -d '{"timeRange": "last_1h"}'

# Verify identity graph
curl -s http://localhost:8000/v1/resolution/cluster/${TEST_USER_ID} \
  -H "Authorization: Bearer ${API_KEY}"
```

### 4.3 Monitor for 30 Minutes

Watch for:
- Error rate spike in Prometheus: `rate(http_requests_total{status=~"5.."}[5m])`
- Kafka consumer lag: `kafka_consumer_group_lag`
- Redis connection pool exhaustion: `redis_pool_connections_active`
- Memory usage trending upward (leak indicator)

---

## SDK Client Migration (v6 to v7)

For SDK migration details (breaking changes, removed APIs, new features), see `docs/MIGRATION-v7.md`.

**Key steps:**
1. Deploy backend v8.7.1 first (new endpoints required by v7 SDKs)
2. Update Web SDK: `npm install @aether/web-sdk@7.0.0`
3. Update mobile SDKs (iOS/Android/React Native)
4. Remove deprecated module flags from SDK config
5. Add identity resolution signals to `hydrateIdentity()` calls

---

## Rollback Triggers

Initiate rollback (see `docs/ROLLBACK-RUNBOOK.md`) if any of these occur within 30 minutes post-deploy:

| Trigger | Threshold |
|---------|-----------|
| 5xx error rate | > 5% of requests for 5 minutes |
| Health check failures | Any service unhealthy for > 2 minutes |
| Event ingestion stopped | Zero events for > 5 minutes |
| ML prediction errors | > 10% error rate for 5 minutes |
| Database connection errors | Any persistent connection failures |
| Kafka consumer lag | Growing continuously for > 10 minutes |
| Memory usage | > 90% on any service for > 5 minutes |

---

## Emergency Contacts

| Role | Responsibility |
|------|---------------|
| On-call engineer | Execute migration, monitor, initiate rollback |
| Database admin | Schema changes, PITR recovery |
| Platform lead | Go/no-go decisions, escalation |
| Security lead | Secret rotation, access issues |
