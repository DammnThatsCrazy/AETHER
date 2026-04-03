# Smoke Test & Post-Deploy Verification Checklist — Aether Platform v8.7.1

Run after every deployment. Failures in the **Smoke Tests** section are rollback triggers. Failures in **Extended Verification** may be acceptable depending on context.

---

## Prerequisites

```bash
# Set these before running tests
export BASE_URL="http://localhost:8000"     # Backend API
export ML_URL="http://localhost:8080"        # ML Serving
export PROM_URL="http://localhost:9090"      # Prometheus
export API_KEY="<admin-api-key>"
```

---

## Smoke Tests (P0 — Rollback if any fail)

### 1. Service Health

```bash
# Backend API
curl -sf ${BASE_URL}/v1/health | jq .
# Expected: {"status": "healthy", "dependencies": {"postgres": "ok", "redis": "ok", ...}}

# ML Serving
curl -sf ${ML_URL}/health | jq .
# Expected: {"status": "healthy", "models_loaded": [...]}

# Prometheus
curl -sf ${PROM_URL}/-/healthy
# Expected: 200 OK
```

- [ ] Backend health returns `healthy` with all dependencies `ok`
- [ ] ML serving health returns `healthy` with models loaded
- [ ] Prometheus is scraping targets

### 2. Authentication & Tenant Isolation

```bash
# Unauthenticated request must fail
curl -s -o /dev/null -w "%{http_code}" ${BASE_URL}/v1/analytics/events/query
# Expected: 401 or 403

# Authenticated request must succeed
curl -sf -H "Authorization: Bearer ${API_KEY}" ${BASE_URL}/v1/analytics/events/query \
  -d '{"timeRange": "last_1h"}' | jq .status
# Expected: 200 with results
```

- [ ] Unauthenticated requests are rejected (401/403)
- [ ] Authenticated requests succeed
- [ ] Cross-tenant access returns 404 (not 403, to prevent enumeration)

### 3. Event Ingestion Pipeline

```bash
# Ingest a test event
curl -sf -X POST ${BASE_URL}/v1/ingest/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_KEY}" \
  -d '{
    "events": [{
      "type": "smoke_test",
      "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
      "properties": {"source": "smoke_test", "deploy_version": "v8.7.1"}
    }]
  }'
# Expected: 200/202 with event ID(s)
```

- [ ] Event ingestion returns success (200/202)
- [ ] Event appears in query results within 10 seconds

### 4. ML Prediction

```bash
# Test ML inference
curl -sf -X POST ${ML_URL}/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model": "intent",
    "features": {"session_duration": 120, "page_views": 5, "scroll_depth": 0.7}
  }' | jq .
# Expected: prediction with confidence score
```

- [ ] ML prediction returns valid response with scores
- [ ] Response time < 500ms (p99)

### 5. Database Connectivity

```bash
# Verify via health check dependencies
curl -sf ${BASE_URL}/v1/health | jq '.dependencies'
# All should show "ok"
```

- [ ] PostgreSQL connection pool active
- [ ] Redis connection responsive
- [ ] Neptune graph (if enabled) reachable
- [ ] Kafka broker (if enabled) connected

### 6. Metrics Endpoint

```bash
# Prometheus metrics
curl -sf ${BASE_URL}/v1/metrics | head -20
# Expected: Prometheus text format with aether_* metrics
```

- [ ] Metrics endpoint returns Prometheus format
- [ ] `aether_http_requests_total` counter is incrementing
- [ ] `aether_http_request_duration_seconds` histogram is populated

---

## Extended Verification (P1 — Investigate but may not require rollback)

### 7. CORS Headers

```bash
# Preflight request
curl -sf -X OPTIONS ${BASE_URL}/v1/ingest/events \
  -H "Origin: https://app.aether.io" \
  -H "Access-Control-Request-Method: POST" \
  -D - -o /dev/null 2>&1 | grep -i "access-control"
# Expected: Access-Control-Allow-Origin matches configured CORS_ORIGINS
# Must NOT be "*" in production
```

- [ ] CORS headers present and match configured origins
- [ ] No wildcard `*` origin in production
- [ ] `Access-Control-Allow-Credentials` not set with wildcard origin

### 8. Data Lake Operations

```bash
# Write to bronze tier
curl -sf -X POST ${BASE_URL}/v1/lake/bronze \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"source": "smoke_test", "data": {"key": "value"}}' | jq .id

# Read back
curl -sf ${BASE_URL}/v1/lake/bronze?source=smoke_test \
  -H "Authorization: Bearer ${API_KEY}" | jq '.[0]'
```

- [ ] Bronze tier write succeeds
- [ ] Bronze tier read returns written data
- [ ] Tenant isolation enforced on lake queries

### 9. Identity Resolution

```bash
# Check identity cluster (if test user exists)
curl -sf ${BASE_URL}/v1/resolution/cluster/smoke-test-user \
  -H "Authorization: Bearer ${API_KEY}" | jq .
```

- [ ] Identity resolution endpoint responds
- [ ] Cluster data is consistent (no orphaned nodes)

### 10. Agent Layer

```bash
# List agent task types
curl -sf ${BASE_URL}/v1/agent/workers \
  -H "Authorization: Bearer ${API_KEY}" | jq '.workers'
# Expected: list of available worker types
```

- [ ] Agent worker list returns available workers
- [ ] Celery workers connected to Redis broker (check `celery inspect active`)

### 11. Extraction Defense (if enabled)

```bash
# Check defense status
curl -sf ${BASE_URL}/v1/defense/status | jq .
# Expected: {"enabled": true/false}

# Check defense metrics
curl -sf ${BASE_URL}/v1/defense/metrics | jq .
```

- [ ] Defense status endpoint responds
- [ ] Rate limiting counters are functional (test with repeated requests)
- [ ] Watermark and canary systems initialized (if enabled)

### 12. Kafka Consumer Health

```bash
# Check consumer group lag
kafka-consumer-groups \
  --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
  --describe --group aether-backend 2>/dev/null
```

- [ ] Consumer group is active
- [ ] Lag is zero or decreasing
- [ ] No partitions unassigned

### 13. Connection Pool Health

```bash
# Check active connections via metrics
curl -sf ${BASE_URL}/v1/metrics | grep -E "pool|connections"
```

- [ ] PostgreSQL pool: active connections < max pool size
- [ ] Redis pool: no connection errors
- [ ] No connection leak trend (monitor over 10 minutes)

### 14. Provider Gateway (if BYOK enabled)

```bash
# Check provider health
curl -sf ${BASE_URL}/v1/providers/health \
  -H "Authorization: Bearer ${API_KEY}" | jq .
```

- [ ] Provider gateway responds
- [ ] Configured providers show healthy status
- [ ] BYOK encryption key is functional (provider secrets can be decrypted)

### 15. Consent & GDPR

```bash
# Verify consent endpoint
curl -sf ${BASE_URL}/v1/consent/status \
  -H "Authorization: Bearer ${API_KEY}" | jq .
```

- [ ] Consent endpoint responds
- [ ] DSR (Data Subject Request) submission works

---

## Load Validation (P2 — Run in staging, optional in production)

### 16. Basic Load Test

```bash
# Quick load test with hey or ab
hey -n 100 -c 10 -H "Authorization: Bearer ${API_KEY}" \
  ${BASE_URL}/v1/health

# Or with Locust (full suite)
cd tests/load
locust -f locustfile.py --headless -u 10 -r 2 --run-time 60s \
  --host ${BASE_URL}
```

- [ ] p99 latency < 500ms at 10 concurrent users
- [ ] No 5xx errors under load
- [ ] Memory usage stable (no upward trend)
- [ ] CPU usage < 80% under test load

### 17. Connection Pool Exhaustion Test

```bash
# Rapid concurrent requests to test pool limits
hey -n 200 -c 50 -H "Authorization: Bearer ${API_KEY}" \
  ${BASE_URL}/v1/analytics/events/query \
  -d '{"timeRange": "last_1h"}'
```

- [ ] No connection pool exhaustion errors
- [ ] Requests queue gracefully when pool is full
- [ ] Pool recovers after burst

---

## Automated Smoke Test Script

Save as `scripts/smoke_test.sh` and run after each deploy:

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
ML_URL="${2:-http://localhost:8080}"
PASS=0
FAIL=0

check() {
  local name="$1"
  local cmd="$2"
  if eval "$cmd" > /dev/null 2>&1; then
    echo "  PASS  $name"
    ((PASS++))
  else
    echo "  FAIL  $name"
    ((FAIL++))
  fi
}

echo "=== Aether Smoke Tests ==="
echo "Backend: ${BASE_URL}"
echo "ML:      ${ML_URL}"
echo ""

check "Backend health"    "curl -sf ${BASE_URL}/v1/health"
check "ML health"         "curl -sf ${ML_URL}/health"
check "Metrics endpoint"  "curl -sf ${BASE_URL}/v1/metrics"
check "Auth rejection"    "curl -s -o /dev/null -w '%{http_code}' ${BASE_URL}/v1/analytics/events/query | grep -q '40[13]'"
check "CORS no wildcard"  "curl -sf -H 'Origin: https://evil.com' ${BASE_URL}/v1/health -D - -o /dev/null 2>&1 | grep -v 'Access-Control-Allow-Origin: \*'"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] && echo "ALL SMOKE TESTS PASSED" || echo "SMOKE TESTS FAILED — CONSIDER ROLLBACK"
exit $FAIL
```

---

## Sign-Off

| Check | Owner | Status | Timestamp |
|-------|-------|--------|-----------|
| Smoke tests (P0) | On-call engineer | | |
| Extended verification (P1) | On-call engineer | | |
| Load validation (P2) | Performance team | | |
| Stakeholder notification | Platform lead | | |
