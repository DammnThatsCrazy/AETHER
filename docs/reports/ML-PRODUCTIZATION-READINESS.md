---
title: ML Productization Readiness Report
version: 1.0
generated_at: 2026-06-13
source_files:
  - ML Models/aether-ml/common/model_registry.py
  - ML Models/aether-ml/common/feature_contracts.py
  - ML Models/aether-ml/common/artifact_registry.py
  - ML Models/aether-ml/training/pipelines/train.py
  - ML Models/aether-ml/serving/src/api.py
  - Backend Architecture/aether-backend/services/ml_serving/routes.py
  - security/model_extraction_defense/defense_layer.py
last_synced_commit: HEAD
---

# Aether ML Productization Readiness Report

## Executive Summary

Aether's ML system comprises **9 trainable ML models** and **2 additional intelligence/scoring outputs** (bytecode risk scoring, trust score). This report documents the current implementation state, identified gaps, implemented fixes, and remaining production blockers.

---

## Section 0: Baseline Inventory (Pre-Fix State)

### Model Count Drift (CONFIRMED — FIXED)

| Claim | Location | Count | Notes |
|-------|----------|-------|-------|
| README ML section | README.md | 9 | Trainable models (correct) |
| ML Training Guide | docs/ML-TRAINING-GUIDE.md | 9 | Behavioral models (correct) |
| Training config | training/configs/model_configs.py | 9 | Registered (correct) |
| Serving API | serving/src/api.py `MODEL_NAMES` | 9 | Canonical names (correct) |
| Backend routes `AVAILABLE_MODELS` | routes.py L57 | 9 | **WRONG: used `identity_gnn`, `journey_tft`** |
| Canonical Registry (new) | common/model_registry.py | 11 | 9 trainable + 2 deterministic |

**Verdict**: README and training config were correct (9 trainable). Backend routes used stale API alias names (`identity_gnn`, `journey_tft`) instead of canonical names (`identity_resolution`, `journey_prediction`). **FIXED.**

### Confirmed Bugs (All Fixed)

| Bug | File | Line | Fix |
|-----|------|------|-----|
| `AVAILABLE_MODELS` used `identity_gnn`, `journey_tft` | routes.py | 57-61 | Replaced with canonical registry resolution |
| `_MODEL_ENDPOINTS` mapped `identity_gnn` to `/v1/predict/batch` | routes.py | 64-74 | Replaced with registry-backed endpoint lookup |
| `post_result.modified_output` (field does not exist) | routes.py | 204 | Fixed to `post_result.output` |
| Pre-request extraction defense not enforced in backend | routes.py | 134-276 | Added `defense.pre_request()` call |
| Batch endpoint missing privileged-only enforcement | routes.py | 279-326 | Added `ml:batch` permission + registry policy |
| No canonical model registry | — | — | Created `common/model_registry.py` |
| No feature contracts | — | — | Created `common/feature_contracts.py` |
| No artifact registry | — | — | Created `common/artifact_registry.py` |
| Training artifacts missing `synthetic_data` flag | train.py | 600-624 | Added `synthetic_data` field to metadata |
| Training missing threshold gates | train.py | — | Added `_check_thresholds()` |

---

## Section 1: Model Registry Status

**Location**: `ML Models/aether-ml/common/model_registry.py`

| model_id | type | tier | trainable | serving | batch_privileged | status |
|----------|------|------|-----------|---------|-----------------|--------|
| intent_prediction | trainable_ml | edge | ✅ | ✅ | no | trainable_synthetic |
| bot_detection | trainable_ml | edge | ✅ | ✅ | no | trainable_synthetic |
| session_scorer | trainable_ml | edge | ✅ | ✅ | no | trainable_synthetic |
| identity_resolution | trainable_ml | server | ✅ | ✅ | yes | trainable_synthetic |
| journey_prediction | trainable_ml | server | ✅ | ✅ | yes | trainable_synthetic |
| churn_prediction | trainable_ml | server | ✅ | ✅ | yes | trainable_synthetic |
| ltv_prediction | trainable_ml | server | ✅ | ✅ | yes | trainable_synthetic |
| anomaly_detection | trainable_ml | server | ✅ | ✅ | yes | trainable_synthetic |
| campaign_attribution | trainable_ml | server | ✅ | ✅ | yes | trainable_synthetic |
| bytecode_risk | deterministic | security | ❌ | ✅ | no | active_deterministic |
| trust_score | composite | composite | ❌ | ✅ | no | active_deterministic |

**Deprecated aliases (resolved to canonical IDs)**:
- `identity_gnn` → `identity_resolution`
- `journey_tft` → `journey_prediction`

---

## Section 2: Feature Contracts Status

**Location**: `ML Models/aether-ml/common/feature_contracts.py`

All 9 trainable models and 2 deterministic outputs now have feature contracts.

| model_id | contract_id | required_features | schema_hash | freshness_sla |
|----------|-------------|-------------------|-------------|---------------|
| intent_prediction | intent_prediction_v1 | 14 | (stable) | 60s |
| bot_detection | bot_detection_v1 | 14 | (stable) | 30s |
| session_scorer | session_scorer_v1 | 6 required, 3 optional | (stable) | 60s |
| identity_resolution | identity_resolution_v1 | 8 required, 1 optional | (stable) | 3600s |
| journey_prediction | journey_prediction_v1 | 6 required, 1 optional | (stable) | 1800s |
| churn_prediction | churn_prediction_v1 | 11 | (stable) | 86400s |
| ltv_prediction | ltv_prediction_v1 | 9 required, 2 optional | (stable) | 86400s |
| anomaly_detection | anomaly_detection_v1 | 9 | (stable) | 300s |
| campaign_attribution | campaign_attribution_v1 | 5 | (stable) | 3600s |
| bytecode_risk | bytecode_risk_v1 | 5 | (stable) | 0s |
| trust_score | trust_score_v1 | 0 required, 4 optional | (stable) | 300s |

---

## Section 3: Training Pipeline Status

**Location**: `ML Models/aether-ml/training/pipelines/train.py`

All 9 trainable models can train on synthetic data via:
```bash
python -m training.pipelines.train --model <model_id> --data synthetic
python -m training.pipelines.train --model all --data synthetic
```

Training now produces:
- `model.joblib` — serialized scikit-learn estimator
- `metadata.json` — full canonical metadata including:
  - `synthetic_data: true` for synthetic training runs
  - `production_allowed: false` for all synthetic artifacts
  - `threshold_passed` — whether minimum metrics were met
  - `feature_schema_hash` — tied to feature contract version
  - `promotion_state: "trained"` — must be promoted before production use

**Threshold gates implemented** (see `_check_thresholds()`). Synthetic artifacts are explicitly marked `production_allowed=false`.

---

## Section 4: Artifact Registry Status

**Location**: `ML Models/aether-ml/common/artifact_registry.py`

Promotion states: `local → trained → candidate → staged → promoted → disabled`

Loading policy by environment:
- **local/dev**: may load `local/trained/candidate/staged/promoted`
- **staging**: may load `staged/candidate` (NOT synthetic)
- **production**: may load `promoted` only, with `production_allowed=true` and `synthetic_data=false`

Enforced by `_enforce_load_policy()`. Fails closed on any policy violation.

---

## Section 5: Serving API Status

**Location**: `ML Models/aether-ml/serving/src/api.py`

| Endpoint | Status | Notes |
|----------|--------|-------|
| GET /health | ✅ | Returns model load status |
| GET /models | ✅ | Returns all 9 model infos |
| POST /v1/predict/intent | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/bot | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/session-score | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/churn | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/ltv | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/journey | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/attribution | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/batch | ✅ | Privileged-only |
| GET /v1/defense/status | ✅ | Defense status |
| GET /v1/defense/metrics | ✅ | Defense metrics |

Stub policy: stubs load only when `AETHER_ENV` ∉ {`production`, `staging`}. Production and staging serve 503 when artifacts are missing.

**Missing serving endpoint for identity_resolution**: The serving API exposes `/v1/predict/intent` etc. but not a dedicated `/v1/predict/identity` route. The `identity_resolution` model falls back to `/v1/predict/batch`. A dedicated route should be added in a future iteration.

---

## Section 6: Backend ML Gateway Status

**Location**: `Backend Architecture/aether-backend/services/ml_serving/routes.py`

All bugs fixed:

| Fix | Status |
|-----|--------|
| Canonical model ID resolution via registry | ✅ |
| `identity_gnn`/`journey_tft` deprecated alias support | ✅ |
| Pre-request extraction defense before inference | ✅ |
| `post_result.output` (not `.modified_output`) | ✅ |
| Batch requires `ml:batch` permission | ✅ |
| Registry-backed `/models` response | ✅ |
| `canonical_model_id` in all prediction responses | ✅ |
| Deprecated alias warning in response | ✅ |
| Tenant isolation in feature endpoint | ✅ |

---

## Section 7: Extraction Defense Status

**Location**: `security/model_extraction_defense/defense_layer.py`

| Component | Status |
|-----------|--------|
| `pre_request()` enforcement (backend) | ✅ Fixed |
| `post_response()` using `.output` (not `.modified_output`) | ✅ Fixed |
| Serving middleware pre-request | ✅ Existing |
| Rate limiting (multi-axis) | ✅ Existing |
| Pattern detection | ✅ Existing |
| Risk scoring | ✅ Existing |
| Canary detection | ✅ Existing |
| Output perturbation | ✅ Existing |
| Watermark embedding | ✅ Existing |
| Batch non-privileged denial | ✅ Backend + Serving |
| Metrics/telemetry | ✅ Existing |

**Note**: The extraction defense mesh (Layers A–G documented in `docs/MODEL-EXTRACTION-DEFENSE.md`) is partially implemented. The rate limiter, pattern detector, risk scorer, canary detector, output perturbation, and watermark are real. The mesh identity fabric (Layer A) and distributed Redis budgets (Layer B) require real Redis to function. In local/dev mode these degrade gracefully.

---

## Section 8: Monitoring Status

**Location**: `ML Models/aether-ml/monitoring/`

Prometheus metrics and alerts exist in `monitoring/monitor.py` and `monitoring/alerts.py`. Integration with the serving API is via the `defense_metrics` endpoint.

Remaining: dedicated per-model drift detection, per-model data freshness SLA tracking, and Kyber admin dashboard hooks are partially implemented (see Section 9 below).

---

## Section 9: Kyber Admin Hooks

Backend admin routes for ML operational state are defined in:
- `Backend Architecture/aether-backend/services/ml_serving/routes.py` (production gateway)
- Kyber admin hooks require a dedicated `/v1/admin/kyber/ml/` router (to be added)

---

## Gap Table (Post-Fix)

| Area | Gap | Severity | Status |
|------|-----|----------|--------|
| Model registry | None — canonical registry created | — | ✅ |
| Feature contracts | None — all 11 contracts created | — | ✅ |
| Artifact registry | None — full lifecycle implemented | — | ✅ |
| Backend routes | All bugs fixed | — | ✅ |
| Training pipeline | Synthetic flag, thresholds added | — | ✅ |
| Serving `/ready` env-awareness | Exists but not fully SLA-gated | Medium | ⚠️ |
| Identity resolution serving route | Falls back to batch (not dedicated) | Low | ⚠️ |
| Kyber admin ML hooks | Not yet added as separate router | Medium | ⚠️ |
| Real data training path | Requires external infrastructure | Infra | 🔧 |
| MLflow tracking | Available, fails gracefully if unreachable | Infra | 🔧 |
| S3 artifact store | Requires AWS credentials | Infra | 🔧 |
| Redis feature store | Requires Redis instance | Infra | 🔧 |
| Drift detection | Framework exists, per-model baselines needed | Medium | ⚠️ |
| CI for ML registry drift | See Section 13 of main plan | Medium | ⚠️ |

---

## Implementation Plan (Remaining)

### Immediate (blocking staging)
1. Add dedicated `/v1/predict/identity` serving route for identity_resolution
2. Add Kyber admin ML hooks router at `/v1/admin/kyber/ml/`
3. Add CI job for ML registry drift validation
4. Add training smoke tests to CI

### Pre-Staging
1. Provision Redis, S3, MLflow tracking infrastructure
2. Generate real data sample for staging training
3. Run training pipeline with real data
4. Promote artifacts through `trained → candidate → staged`
5. Set `AETHER_REQUIRE_PROMOTED_MODELS=true` in staging

### Pre-Production
1. Run full training on production real data
2. Pass all minimum metric thresholds
3. Promote artifacts to `promoted` state
4. Conduct extraction defense audit
5. Enable drift monitoring alerts
6. Set `AETHER_REQUIRE_PROMOTED_MODELS=true` in production

---

## Release Gates

### Local/Dev ✅ READY
- [x] All 9 trainable models train on synthetic data
- [x] Artifacts saved with correct metadata
- [x] Synthetic flag set correctly
- [x] Serving returns stub or artifact prediction
- [x] Backend routes use canonical IDs
- [x] Extraction defense enforced (if enabled)

### Staging 🔧 BLOCKED (infra)
- [ ] Real data sample available
- [ ] Redis online feature store configured
- [ ] S3 artifact store configured
- [ ] Models trained on real data sample
- [ ] Artifacts in `staged` state
- [ ] Feature contracts validated on real data
- [ ] Drift baselines established

### Production 🔧 BLOCKED (infra + real data)
- [ ] Real production data training
- [ ] All thresholds passed
- [ ] Artifacts in `promoted` state with `production_allowed=true`
- [ ] Drift monitoring active
- [ ] Extraction defense audit complete
- [ ] Canary inputs seeded
- [ ] SRE on-call runbook complete

---

## Final Status Summary

| Component | Local/Dev | Staging | Production |
|-----------|-----------|---------|------------|
| Registry | ✅ | ✅ | ✅ |
| Feature contracts | ✅ | ✅ | ✅ |
| Artifact registry | ✅ | 🔧 infra | 🔧 infra |
| Training (synthetic) | ✅ | N/A | N/A |
| Training (real data) | ✅ if data exists | 🔧 data | 🔧 data |
| Serving (stubs) | ✅ | ❌ | ❌ |
| Serving (artifacts) | ✅ if trained | 🔧 | 🔧 |
| Backend gateway | ✅ | ✅ | ✅ |
| Extraction defense | ✅ | ✅ | ✅ |
| Monitoring | ⚠️ basic | 🔧 | 🔧 |
| Investor demo | ✅ (synthetic labeled) | N/A | N/A |

> **Note**: "Investor demo" uses synthetic-trained artifacts explicitly labeled as such. These are never promoted to production and all responses include `synthetic_data: true`.
