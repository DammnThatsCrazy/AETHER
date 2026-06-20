---
title: ML Incident Runbook
slug: ai/ml-incident-runbook
section: ai
visibility: I
audience: [ai, dev-senior, ops]
status: stable
since_version: "8.9.0"
canonical_owner: ml@aether
source_files:
  - ML Models/aether-ml/serving/src/api.py
  - ML Models/aether-ml/common/artifact_registry.py
  - ML Models/aether-ml/monitoring/monitor.py
  - deploy/observability/prometheus/alert_rules.yml
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: 605cc1c
---

# ML Incident Runbook

> Operational runbook for on-call engineers responding to ML serving incidents.
> Covers alert triage, diagnosis, and remediation for all 8 Prometheus alert rules
> in the `aether_ml_health` group.

## Alert Index

| Alert | Severity | Runbook Section |
|-------|----------|-----------------|
| `MLModelLoadFailure` | critical | [§1](#1-mlmodelloadfailure) |
| `MLHighErrorRate` | critical | [§2](#2-mlhigherrorrate) |
| `MLHighLatency` | warning | [§3](#3-mlhighlatency) |
| `MLFreshnessBreach` | warning | [§4](#4-mlfreshnessbreach) |
| `MLDriftCritical` | warning | [§5](#5-mldriftcritical) |
| `MLSignatureFailure` | critical | [§6](#6-mlsignaturefailure) |
| `MLExtractionAttack` | warning | [§7](#7-mlextractionattack) |
| `MLRollbackEvent` | info | [§8](#8-mlrollbackevent) |

---

## 1. MLModelLoadFailure

**Fires when:** `ml_model_load_success == 0` for any model for 2m.

**Impact:** Predictions for the affected model return 503. Downstream features
dependent on this model (e.g., intent-gated journeys) are unavailable.

**Diagnosis:**

```bash
# Check serving logs for the specific model
docker logs aether-ml-serving 2>&1 | grep -E "ERROR|model_load|artifact" | tail -50

# Check active artifact pointer
cat /opt/ml/models/<model_id>/active_artifact.json

# Verify artifact files present
ls /opt/ml/models/<model_id>/$(cat /opt/ml/models/<model_id>/active_artifact.json | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])")/

# Check HMAC signature key (staging/production: must be present)
echo "Signing key set: $([[ -n $ARTIFACT_SIGNING_KEY ]] && echo YES || echo NO)"
```

**Remediation:**

1. **Missing artifact files** — re-publish from S3: `make ml-artifacts ML_ARTIFACT_BUCKET=<bucket> ML_SERVING_URL=<url>`
2. **HMAC signature mismatch** — artifact may be corrupt or tampered. Do NOT load. Rollback:
   ```bash
   curl -X POST http://localhost:8080/v1/admin/kyber/ml/models/<model_id>/rollback \
     -H "X-Service-Token: $ML_SERVICE_TOKEN"
   ```
3. **Missing signing key** — provision `ARTIFACT_SIGNING_KEY` via Secrets Manager and restart serving.
4. **XGBoost not installed** (churn/ltv) — serving image built without `[serving]` extras; rebuild with `make ml-container-build`.

**Escalation:** If rollback also fails, serve from shadow/canary or disable the endpoint and page ML on-call.

---

## 2. MLHighErrorRate

**Fires when:** `rate(ml_prediction_errors_total[5m]) > 0.05` for 5m (>5% error rate).

**Impact:** Users see degraded ML-dependent features. Error rate above 5% suggests systematic failure, not transient noise.

**Diagnosis:**

```bash
# Error distribution by model and error type
curl -s http://localhost:8080/v1/admin/kyber/ml/overview \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Freshness status (stale features cause validation errors)
curl -s http://localhost:8080/v1/monitoring/freshness \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Feature contract violations in logs
docker logs aether-ml-serving 2>&1 | grep "ContractMismatch\|validation_error" | tail -30
```

**Common causes:**

| Symptom in logs | Cause | Fix |
|-----------------|-------|-----|
| `ContractMismatchError` | Schema version mismatch between training and serving | Rollback artifact or redeploy matching serving image |
| `ValidationError` on features | Upstream feature pipeline renamed fields | Check `features/pipeline.py` vs feature contract |
| `503` on all models | Redis unreachable and fail-closed | Restore Redis connectivity; check `REDIS_URL` |
| `401 Unauthorized` | `ML_SERVICE_TOKEN` rotation not propagated | Update token in both backend and ML serving env |

**Remediation:** Fix root cause per table above. If rate drops below 5% within 10 minutes, alert auto-resolves.

---

## 3. MLHighLatency

**Fires when:** `histogram_quantile(0.95, ml_prediction_latency_seconds) > 2.0` for 10m (p95 > 2s).

**Impact:** User-facing journeys that call ML synchronously will time out or degrade.

**Diagnosis:**

```bash
# Per-model p95 latency from Prometheus
curl -s http://localhost:9090/api/v1/query \
  --data-urlencode 'query=histogram_quantile(0.95, sum(rate(ml_prediction_latency_seconds_bucket[5m])) by (le, model_name))'

# Check resource saturation
docker stats aether-ml-serving --no-stream
```

**Remediation:**

1. **Single slow model** — check if drift detection background task is CPU-contending; disable temporarily via env var `ML_DRIFT_CHECK_INTERVAL_SECONDS=0` and restart.
2. **All models slow** — scale serving replicas or check host CPU/memory saturation.
3. **Batch request flood** — extraction defense rate limiter should be kicking; check `curl http://localhost:8080/v1/monitoring/extraction`.
4. **Cold start after rollback** — allow 60–120s warm-up after artifact swap.

---

## 4. MLFreshnessBreach

**Fires when:** `ml_feature_freshness_breach_total > 0` for 15m.

**Impact:** Model predictions are based on stale feature data. Severity depends on model and staleness duration.

**Diagnosis:**

```bash
# Freshness status per model and feature group
curl -s http://localhost:8080/v1/monitoring/freshness \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Check feature pipeline logs
docker logs aether-features 2>&1 | grep -E "ERROR|staleness|freshness" | tail -30
```

**SLA thresholds by model** (from feature contracts):

| Model | Feature Group | SLA |
|-------|--------------|-----|
| `intent_prediction` | behavioral_features | 300s |
| `bot_detection` | behavioral_features | 300s |
| `session_scorer` | session_features | 120s |
| `churn_prediction` | behavioral_features | 3600s |
| `ltv_prediction` | behavioral_features | 3600s |
| `anomaly_detection` | record_features | 300s |
| `journey_prediction` | journey_features | 300s |
| `campaign_attribution` | attribution_features | 3600s |
| `identity_resolution` | identity_features | 900s |

**Remediation:**

1. **Feature pipeline down** — restart the features container; check upstream data source connectivity.
2. **Single feature group stale** — isolate upstream source; serve from stale features with degraded confidence flag if SLA < 2×threshold.
3. **Persistent breach** — page data engineering; consider disabling affected endpoint until pipeline recovers.

---

## 5. MLDriftCritical

**Fires when:** `ml_drift_score > 0.3` for 30m (sustained drift above critical threshold).

**Impact:** Model predictions may be unreliable. The underlying feature distribution has
shifted significantly from the training distribution.

**Diagnosis:**

```bash
# Drift scores per model
curl -s "http://localhost:8080/v1/admin/kyber/ml/models/<model_id>/drift" \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Check when the baseline was recorded
cat /opt/ml/models/<model_id>/<artifact_version>/baseline.joblib  # binary — check metadata
cat /opt/ml/models/<model_id>/<artifact_version>/metadata.json | python3 -m json.tool
```

**Remediation:**

1. **Seasonal drift (expected)** — schedule retraining: `make ml-train-smoke` with real data.
2. **Sudden drift (unexpected)** — investigate upstream data pipeline for anomalies; may indicate data poisoning (see T6 in threat model).
3. **Stale baseline** — if artifact was promoted months ago, record a new baseline from a stable recent window:
   ```bash
   # After retraining with updated data
   make ml-artifacts ML_ARTIFACT_BUCKET=<bucket> ML_SERVING_URL=<url>
   ```
4. **Alert threshold too sensitive** — adjust `ml_drift_score > 0.3` threshold in `alert_rules.yml` if business context warrants.

---

## 6. MLSignatureFailure

**Fires when:** `ml_artifact_signature_failures_total > 0` (any signature failure).

**Impact:** An artifact load was rejected due to HMAC mismatch. Possible artifact
corruption, tampering, or key rotation without re-signing.

**SEVERITY: Treat as potential security incident until ruled out.**

**Immediate actions:**

1. **Do not load the artifact.** The serving layer already fails closed.
2. **Capture the evidence:**
   ```bash
   # Identify which artifact failed
   docker logs aether-ml-serving 2>&1 | grep "signature\|HMAC\|ArtifactChecksumMismatch" | tail -20

   # Check S3 object metadata for unexpected modifications
   aws s3api head-object --bucket $ML_ARTIFACT_BUCKET --key <path-to-artifact>
   ```
3. **Rollback to last known-good:**
   ```bash
   curl -X POST http://localhost:8080/v1/admin/kyber/ml/models/<model_id>/rollback \
     -H "X-Service-Token: $ML_SERVICE_TOKEN"
   ```
4. **Page security on-call** — attach evidence from step 2.
5. **After investigation** — if corruption (not tampering), re-sign artifact with `ARTIFACT_SIGNING_KEY` and re-promote.

---

## 7. MLExtractionAttack

**Fires when:** `ml_extraction_risk_high_total > 10` in 5m window (>10 high-risk events).

**Impact:** Possible model extraction attempt. Adversary may be systematically
querying endpoints to reconstruct a surrogate model.

**Diagnosis:**

```bash
# Extraction event summary
curl -s http://localhost:8080/v1/monitoring/extraction \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Identify top querying API keys from backend logs
docker logs aether-backend 2>&1 | grep "ml_predict\|extraction" | \
  awk '{print $NF}' | sort | uniq -c | sort -rn | head -20
```

**Remediation:**

1. **Automated defense (already active):**
   - Per-key budget exceeded → 429 responses with perturbation
   - Watermarks embedded in responses for later attribution

2. **Manual escalation:**
   - Identify API key(s) generating high-risk events
   - Revoke key(s) in tenant management console
   - If watermarked responses appear in a public model, engage legal

3. **Budget tightening** (if attack is sustained):
   - Reduce `max_queries_per_window` in extraction defense config
   - Enable stricter perturbation band

---

## 8. MLRollbackEvent

**Fires when:** `ml_rollback_events_total > 0` (any rollback).

**Severity:** Info — not an emergency, but warrants investigation of why rollback occurred.

**Diagnosis:**

```bash
# Audit log for the rolled-back model
tail -20 /opt/ml/models/<model_id>/promotion_audit.jsonl | python3 -m json.tool

# Check current active artifact
curl -s http://localhost:8080/v1/admin/kyber/ml/models/<model_id> \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool
```

**Follow-up:**

1. Confirm the rolled-back version is serving correctly (error rate, latency).
2. Identify the initiator (`actor` field in audit log).
3. If automated rollback (triggered by error rate threshold), review root cause before re-promoting.
4. If manual rollback, confirm the trigger was valid and document in the incident ticket.

---

## General Diagnostic Commands

```bash
# Serving health
curl http://localhost:8080/health
curl http://localhost:8080/ready

# All model statuses
curl -s http://localhost:8080/v1/admin/kyber/ml/overview \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Rollback eligibility check
curl -s http://localhost:8080/v1/admin/kyber/ml/models/<model_id>/rollback-eligibility \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Per-model artifact version
curl -s http://localhost:8080/v1/admin/kyber/ml/models/<model_id>/artifacts \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool

# Training history
curl -s http://localhost:8080/v1/admin/kyber/ml/models/<model_id>/training-history \
  -H "X-Service-Token: $ML_SERVICE_TOKEN" | python3 -m json.tool
```

## Escalation Path

| Condition | Escalate to |
|-----------|-------------|
| `MLSignatureFailure` | Security on-call immediately |
| `MLModelLoadFailure` + rollback fails | ML on-call |
| `MLExtractionAttack` sustained > 30m | Security on-call + ML on-call |
| `MLDriftCritical` sustained > 2h | ML on-call + data engineering |
| Any alert in production after business hours | PagerDuty ML rotation |
