# Rollback Runbook — Aether Platform v8.7.1

Step-by-step procedures for rolling back the Aether platform after a failed deployment or production incident.

---

## Decision Framework

### When to Roll Back

| Signal | Threshold | Action |
|--------|-----------|--------|
| 5xx error rate | > 5% for 5 min | Rollback |
| Health check failure | Any service down > 2 min | Rollback affected service |
| Data corruption | Any confirmed case | Immediate rollback + incident |
| Event ingestion halted | Zero events > 5 min | Rollback ingestion path |
| ML prediction failure | > 10% error rate > 5 min | Rollback ML serving |
| Memory leak | OOM kill or > 90% for 5 min | Rollback affected service |

### When NOT to Roll Back

- Transient network errors (retry first)
- Single-tenant issues (investigate tenant config)
- Expected behavior changes from the release
- Metric gaps due to Prometheus scrape issues

---

## Rollback Procedures by Component

### 1. Application Rollback (Docker Compose)

**Time to recovery: < 5 minutes**

```bash
# 1. Stop current services
docker compose stop backend ml-serving

# 2. Check out previous known-good version
git fetch origin --tags
git checkout v8.6.0  # or previous stable tag

# 3. Rebuild and restart
docker compose build backend ml-serving
docker compose up -d backend ml-serving

# 4. Verify health
curl -sf http://localhost:8000/v1/health
curl -sf http://localhost:8080/health
```

If images are pre-built and tagged:

```bash
# Faster: just swap image tags
docker compose down backend ml-serving

# Edit docker-compose.yml or use override
export BACKEND_IMAGE=aether-backend:v8.6.0
export ML_IMAGE=aether-ml-serving:v8.6.0
docker compose up -d backend ml-serving
```

### 2. Application Rollback (AWS ECS)

**Time to recovery: 5-10 minutes**

```bash
cd "AWS Deployment/aether-aws"

# Roll back to previous task definition revision
aws ecs update-service \
  --cluster aether-prod \
  --service aether-backend \
  --task-definition aether-backend:<previous-revision>

aws ecs update-service \
  --cluster aether-prod \
  --service aether-ml-serving \
  --task-definition aether-ml-serving:<previous-revision>

# Monitor rollback
watch -n 5 'aws ecs describe-services \
  --cluster aether-prod \
  --services aether-backend aether-ml-serving \
  --query "services[].{name:serviceName,running:runningCount,desired:desiredCount}"'
```

Alternatively, revert Terraform:

```bash
git checkout v8.6.0 -- "AWS Deployment/aether-aws/"
terraform plan -var="image_tag=v8.6.0"
terraform apply -var="image_tag=v8.6.0"
```

### 3. Database Rollback (PostgreSQL)

#### 3a. Point-in-Time Recovery (PITR)

**Prerequisites:** WAL archiving must be enabled. Verify:

```bash
psql -c "SHOW archive_mode;"       # must be 'on'
psql -c "SHOW archive_command;"    # must be configured
```

**Procedure:**

```bash
# 1. Note the timestamp BEFORE the migration started
#    (record this in the migration log)
RECOVERY_TARGET="2026-04-03 14:30:00 UTC"

# 2. Stop the application
docker compose stop backend ml-serving

# 3. For AWS RDS: restore to point in time
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier aether-prod \
  --target-db-instance-identifier aether-prod-recovery \
  --restore-time "${RECOVERY_TARGET}"

# 4. Wait for restoration
aws rds wait db-instance-available \
  --db-instance-identifier aether-prod-recovery

# 5. Update DATABASE_URL to point to recovery instance
# 6. Restart application
docker compose up -d backend ml-serving
```

#### 3b. Schema-Only Rollback

If the migration was a schema change (no data loss):

```bash
# Apply reverse migration script
psql "${DATABASE_URL}" -f migrations/001_schema_change_rollback.sql

# Verify schema
psql "${DATABASE_URL}" -c "\d <affected_table>"
```

#### 3c. Two-Phase Column Drop Rollback

If a column was dropped in a two-phase approach:

- **Phase 1 deployed (code stopped reading column):** Safe — just redeploy old code
- **Phase 2 deployed (column dropped):** Cannot undo without PITR. Use PITR or restore from backup.

### 4. Redis Rollback

**Time to recovery: < 1 minute**

Redis data is ephemeral (cache + rate limits). No rollback needed — caches rebuild automatically.

```bash
# If poisoned data in cache, flush specific prefixes
redis-cli -h $REDIS_HOST -p $REDIS_PORT KEYS "aether:cache:*" | xargs redis-cli DEL

# Nuclear option: flush all (causes temporary cache miss storm)
redis-cli -h $REDIS_HOST -p $REDIS_PORT FLUSHDB
```

**Warning:** Flushing Redis resets all rate limit counters and extraction defense budgets. Monitor for abuse spikes after flush.

### 5. Kafka Rollback

#### 5a. Consumer Group Reset

If consumers processed bad messages:

```bash
# 1. Stop consumers
docker compose stop backend

# 2. Reset consumer group to timestamp before migration
kafka-consumer-groups \
  --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
  --group aether-backend \
  --reset-offsets \
  --to-datetime "2026-04-03T14:30:00.000" \
  --topic aether-events \
  --execute

# 3. Restart consumers with old code
docker compose up -d backend
```

#### 5b. Dead Letter Queue

If bad messages are causing consumer crashes:

```bash
# Skip problematic messages
kafka-consumer-groups \
  --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
  --group aether-backend \
  --reset-offsets \
  --shift-by 1 \
  --topic aether-events \
  --execute
```

### 6. Neptune Graph Rollback

Neptune does not support PITR. Graph changes must be reverted manually.

```bash
# If new vertex/edge labels were added (additive, usually safe):
# No action needed — old code ignores unknown labels

# If vertices/edges were modified or deleted:
# Restore from most recent Neptune snapshot
aws neptune restore-db-cluster-from-snapshot \
  --db-cluster-identifier aether-graph-recovery \
  --snapshot-identifier aether-graph-pre-migration \
  --engine neptune
```

### 7. ML Model Rollback

```bash
# 1. List available model versions
ls -la /models/  # or S3: aws s3 ls s3://aether-models/

# 2. Update ML_MODEL_VERSION environment variable
export ML_MODEL_VERSION=v2.3.0  # previous stable version

# 3. Restart ML serving
docker compose restart ml-serving

# 4. Verify models loaded
curl -s http://localhost:8080/health | jq '.models_loaded'
```

### 8. Configuration Rollback

```bash
# 1. Restore previous .env from backup
cp .env.backup .env

# 2. Restart affected services
docker compose restart backend ml-serving

# 3. Verify configuration
curl -s http://localhost:8000/v1/health | jq .
```

---

## Rollback Verification

After any rollback, verify:

- [ ] `GET /v1/health` returns `{"status": "healthy"}` with all dependencies OK
- [ ] `GET /health` (ML serving) returns healthy with models loaded
- [ ] Ingest a test event successfully via `POST /v1/ingest/events`
- [ ] Query the test event back via `POST /v1/analytics/events/query`
- [ ] ML prediction returns valid response via `POST /v1/ml/predict`
- [ ] Prometheus metrics flowing: `curl http://localhost:9090/api/v1/query?query=up`
- [ ] Error rate returns to baseline within 5 minutes
- [ ] Kafka consumer lag is decreasing
- [ ] No OOM kills in `docker compose logs`

---

## Post-Rollback Actions

1. **Communicate:** Notify stakeholders of rollback and current status
2. **Preserve evidence:** Collect logs from failed deployment before they rotate
   ```bash
   docker compose logs --since 1h > rollback_evidence_$(date +%Y%m%d_%H%M%S).log
   ```
3. **Root cause analysis:** Open incident ticket with:
   - Timeline of events
   - Rollback trigger (which threshold was breached)
   - Logs and metrics from the failed deployment
   - Proposed fix before next attempt
4. **Test the fix:** Validate in staging before re-attempting production deployment
5. **Update this runbook:** If the rollback exposed a gap, document it

---

## Blast Radius Reference

| Component | Rollback Impact | Data Loss Risk |
|-----------|----------------|----------------|
| Backend API | Stateless — only affects new requests | None |
| ML Serving | Stateless — cached predictions may differ | None |
| PostgreSQL | PITR can lose recent writes after recovery point | Minutes of data |
| Redis | Flush loses caches + rate limits | Temporary (rebuilds) |
| Kafka | Offset reset may replay or skip events | Possible duplicates |
| Neptune | Snapshot restore loses changes since snapshot | Hours of data |
| Config (.env) | Immediate effect on restart | None |

---

## Time-to-Recovery Targets

| Scenario | Target | Procedure |
|----------|--------|-----------|
| Application code rollback | < 5 min | Docker image swap |
| ECS task definition rollback | < 10 min | Previous revision |
| Database PITR | < 30 min | RDS point-in-time restore |
| Full stack rollback | < 15 min | Docker Compose down + checkout + up |
| Config-only rollback | < 2 min | Restore .env + restart |
