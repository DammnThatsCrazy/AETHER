---
title: ML Productization Readiness Report
slug: ai/ml-productization-readiness
section: ai
visibility: I
audience: [ai, dev-senior, architect]
since_version: "8.9.0"
canonical_owner: ml@aether
source_files:
  - ML Models/aether-ml/common/model_registry.py
  - ML Models/aether-ml/common/feature_contracts.py
  - ML Models/aether-ml/common/artifact_registry.py
  - ML Models/aether-ml/training/pipelines/train.py
  - ML Models/aether-ml/serving/src/api.py
  - Backend Architecture/aether-backend/services/ml_serving/routes.py
  - security/model_extraction_defense/defense_layer.py
last_synced_commit: "f8d00d3"
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

Training derives the model list from the canonical registry (`list_trainable_models()`); there is no separate hardcoded `MODEL_REGISTRY` dict in `train.py`. Churn/LTV use `XGBClassifier`/`XGBRegressor` when xgboost is available (GBM fallback). `campaign_attribution` uses `GradientBoostingClassifier`.

Training now produces:
- `model.joblib` — serialized scikit-learn estimator
- `preprocessing.joblib` — fitted `ColumnTransformer` (imputer + scaler) matching training input, required by serving to avoid training-serving skew
- `metadata.json` — full canonical metadata including:
  - `synthetic_data: true` for synthetic training runs
  - `production_allowed: false` for all synthetic artifacts
  - `threshold_passed` — whether minimum metrics were met
  - `feature_schema_hash` — tied to feature contract version
  - `promotion_state: "trained"` — must be promoted before production use
- `dataset_manifest.json` — source, row count, entity count, schema hash, synthetic flag, git SHA, and timestamp for every training run

**Threshold gates implemented** (see `_check_thresholds()`). Synthetic artifacts are explicitly marked `production_allowed=false`. `train_all()` exits non-zero if any model fails threshold gates.

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
| GET /health | ✅ | Liveness — returns model load status (sub-ms) |
| GET /ready | ✅ | Readiness — SLA violation rate gate (503 if > 10%) |
| GET /models | ✅ | Returns all 9 model infos |
| POST /v1/predict/intent | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/bot | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/session-score | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/churn | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/ltv | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/journey | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/attribution | ✅ | Lazy-loads artifact or stub |
| POST /v1/predict/identity | ✅ | Real-time single-pair identity resolution |
| POST /v1/predict/anomaly | ✅ | Single-record anomaly detection |
| POST /v1/predict/batch | ✅ | Privileged-only |
| GET /v1/defense/status | ✅ | Defense status |
| GET /v1/defense/metrics | ✅ | Defense metrics |
| GET /v1/monitoring/freshness | ✅ | Feature freshness SLA summary |
| GET /v1/monitoring/extraction | ✅ | Extraction defense event summary |

Stub policy: stubs load only when `AETHER_ENV` ∉ {`production`, `staging`}. Production and staging serve 503 when artifacts are missing.

`DataFreshnessSLATracker` is instantiated at serving startup and records per-model SLA checks against freshness contracts. The `/ready` endpoint gates load-balancer traffic when the violation rate exceeds 10%.

`ExtractionDefenseMonitor` is instantiated at serving startup and records every extraction defense decision (both allowed and blocked) through `extraction_defense_middleware`. Telemetry is available at `/v1/monitoring/extraction`.

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
| Rate limiting (multi-axis, in-memory) | ✅ Existing |
| Rate limiting (Redis-backed, multi-replica) | ✅ G23 — `RedisRateLimiter` dispatched when `REDIS_URL` set; fails closed in staging/prod |
| Pattern detection | ✅ Existing |
| Risk scoring | ✅ Existing |
| Canary detection | ✅ Existing |
| Output perturbation | ✅ Existing |
| Watermark embedding | ✅ Existing |
| Batch non-privileged denial | ✅ Backend + Serving |
| Metrics/telemetry | ✅ Existing |

**Note**: The extraction defense mesh (Layers A–G documented in `docs/MODEL-EXTRACTION-DEFENSE.md`) is partially implemented. The rate limiter (both in-memory and Redis-backed), pattern detector, risk scorer, canary detector, output perturbation, and watermark are real. Redis-backed `RedisRateLimiter` activates when `REDIS_URL` is set; in local/dev without Redis, falls back to in-memory gracefully.

---

## Section 8: Monitoring Status

**Location**: `ML Models/aether-ml/monitoring/`

Prometheus metrics and alerts exist in `monitoring/monitor.py` and `monitoring/alerts.py`. Integration with the serving API is via the `defense_metrics` endpoint.

Drift detection is now fully wired: training saves a `baseline.joblib` sample (up to 1 000 rows) per model; serving maintains per-model prediction buffers (deque, max 500); a background task (`_drift_check_periodic`, 300 s interval, started in lifespan) runs PSI/KS/JS divergence checks via `MonitoringPipeline`; results are exposed at `GET /v1/monitoring/drift`. Per-model data freshness SLA tracking is live at `GET /v1/monitoring/freshness`. Kyber admin dashboard hooks are live at `/v1/admin/kyber/ml/`.

**Durable monitoring state (G19):** `ExtractionDefenseMonitor` and `DataFreshnessSLATracker` both support Redis write-through via `set_redis()`. When `REDIS_URL` is set, the serving lifespan wires a Redis client (db=3, isolated from rate-limiter db=2 and cache db=0) and restores in-memory state from Redis on startup. This makes monitoring state durable across restarts and consistent across replicas. Fails open in all environments — monitoring loss is not a production blocker.

**Prometheus ML alerts:** `deploy/observability/prometheus/alert_rules.yml` now includes an `aether_ml_health` group with 8 ML-specific rules: `MLModelNotLoaded` (critical), `MLPredictionErrorRate`, `MLPredictionLatencyHigh`, `MLFreshnessViolationRate`, `MLDriftDetected`, `MLArtifactSignatureFailure` (critical), `MLExtractionAttackSustained`, `MLModelRolledBack` (info).

---

## Section 9: Kyber Admin Hooks

Backend admin routes for ML operational state are defined in:
- `Backend Architecture/aether-backend/services/ml_serving/routes.py` (production gateway)
- `Backend Architecture/aether-backend/services/ml_serving/kyber_ml_admin.py` — 14 admin routes at `/v1/admin/kyber/ml/` ✅
  - Includes 4 new routes: `/alerts`, `/audit`, `/models/{id}/rollback-eligibility`, `/models/{id}/training-history`

**Kyber ML frontend page**: `frontend/kyber/src/pages/ml/ml-admin-page.tsx` — `/ml` route registered in Kyber router. Displays fleet overview health card (fleet_status, models_loaded/total, extraction defense toggle, readiness badge) and model fleet table via `useMLModels()` + `useMLOverview()` hooks. Frontend API callers for all 14 admin routes are in `frontend/kyber/src/lib/api/endpoints.ts` under `api.ml.*` ✅

---

## Gap Table (Post-Fix)

### Original gaps (all fixed)

| Area | Gap | Severity | Status |
|------|-----|----------|--------|
| Model registry | None — canonical registry created | — | ✅ |
| Feature contracts | None — all 11 contracts created | — | ✅ |
| Artifact registry | None — full lifecycle implemented | — | ✅ |
| Backend routes | All bugs fixed | — | ✅ |
| Training pipeline | Synthetic flag, thresholds added | — | ✅ |
| Serving `/ready` env-awareness | `/ready` endpoint + SLA gate added | Medium | ✅ |
| Identity resolution serving route | `/v1/predict/identity` added | Low | ✅ |
| Kyber admin ML hooks | `/v1/admin/kyber/ml/` router added | Medium | ✅ |
| Drift detection | Baselines saved at training; buffer + `/v1/monitoring/drift` endpoint live | Medium | ✅ |
| CI for ML registry drift | `validate_ml_registry.py` gate added to CI | Medium | ✅ |
| Freshness SLA monitoring | `DataFreshnessSLATracker` wired into serving | Medium | ✅ |

### Phase 1–2 gaps (all fixed)

| # | Area | Gap | Severity | Status |
|---|------|-----|----------|--------|
| G1 | Training | Hardcoded `MODEL_REGISTRY` dict in `train.py` — no registry import | Critical | ✅ |
| G2 | Training | Churn/LTV registry says XGBoost; training used GradientBoosting | High | ✅ XGBClassifier/XGBRegressor (GBM fallback) |
| G3 | Training | `campaign_attribution` registry said ShapleyValues; training used GBM | High | ✅ Registry aligned to GradientBoostingClassifier |
| G4 | Features | Pipeline output `click_interval_mean/std`; contract expected `avg_time_between_actions/time_variance` | High | ✅ Pipeline rewritten to canonical names; aliases added to contract |
| G5 | Features | Pipeline output `action_type_entropy`, `js_execution_time` not in bot_detection contract | High | ✅ Canonical names in pipeline (`interaction_diversity`, `action_rate`); aliases in contract |
| G6 | Serving | `_extraction_monitor` never called in middleware | High | ✅ Wired in `extraction_defense_middleware` |
| G7 | Serving | No `GET /v1/predict/anomaly` endpoint | High | ✅ Added |
| G8 | Serving | Freshness SLA missing from 5 endpoints | Medium | ✅ All 9 prediction endpoints call `_freshness_tracker.check()` (anomaly, journey, attribution added in Phase 3-5) |
| G9 | Serving | No `GET /v1/monitoring/extraction` endpoint | Medium | ✅ Added |
| G10 | Contracts | Schema hash covered only name/dtype/required | Medium | ✅ Extended to default, nullable, min_value, max_value, allowed_values, aliases, freshness_sla |
| G11 | Contracts | String dtype not validated in `validate_features()` | Medium | ✅ Added `elif spec.dtype == "str"` branch |
| G15 | Training | Preprocessing pipeline not persisted with artifact | High | ✅ `preprocessing.joblib` saved alongside `model.joblib` |
| G18 | Training | No dataset manifest produced by training | High | ✅ `dataset_manifest.json` produced every run |
| G20 | CI/Make | No ML-specific Makefile targets | Medium | ✅ `ml-validate`, `ml-test-*`, `ml-train-smoke`, `ml-artifact-verify`, `ml-ci` added |
| G21 | Validation | Registry validator used string checks, not runtime inspection | Medium | ✅ Runtime FastAPI route inspection; endpoint presence verified in `api.py` |
| G22 | Docs | No `ml-implementation-manifest.json` | Medium | ✅ `scripts/generate_ml_manifest.py` + `docs/_generated/ml-implementation-manifest.json` |

### Remaining gaps (infra / post-code)

| Area | Gap | Severity | Status |
|------|-----|----------|--------|
| Real data training path (S3/PostgreSQL data loaders) | G13 — S3 + PostgreSQL loaders | Medium | ✅ Implemented (`_load_from_s3`, `_load_from_postgresql`); requires cloud credentials |
| Digital artifact signing (HMAC-SHA256) | G14 — `ARTIFACT_SIGNING_KEY` sign/verify | Medium | ✅ Implemented; fails closed in staging/production when key absent |
| Atomic artifact metadata save | Phase 4 — write-then-rename | Medium | ✅ Implemented (`.tmp` + `os.replace()`) |
| Promotion audit log | Phase 4 — append-only JSONL per model | Medium | ✅ Implemented (`promotion_audit.jsonl`) |
| Complete rollback with active pointer | Phase 4 — `active_artifact.json` pointer | Medium | ✅ Implemented; `resolve_active_artifact` honours pointer |
| Service token auth (serving) | Phase 5 — `X-Service-Token` header | Medium | ✅ Implemented; `ML_SERVICE_TOKEN` env var; no-op when absent |
| MLflow tracking | Available, fails gracefully if unreachable | Infra | 🔧 |
| S3 artifact store | G11.6 — S3ArtifactStore class for artifact persistence | Infra | 🔧 Requires AWS credentials |
| Redis instance for distributed budgets | Requires Redis instance; code dispatches to it when `REDIS_URL` set | Infra | 🔧 |
| Versioned cache keys in backend | G25 — `CacheKey.prediction()` accepts `artifact_version`; `_model_version_cache` wired in routes | High | ✅ Implemented; activates when serving API returns `artifact_version` field |
| Dockerfile non-root user | G24 — `USER aether` (uid 1001) added to all 4 stages | Medium | ✅ Implemented |
| Kyber ML operations page | `/ml` route + `MLAdminPage` + `useMLOverview()` hook | Medium | ✅ Implemented |
| Durable monitoring state | G19 — `ExtractionDefenseMonitor` + `DataFreshnessSLATracker` Redis write-through; wired in lifespan | High | ✅ Implemented |
| ML Prometheus alert rules | 8 ML-specific alerts in `aether_ml_health` group | Medium | ✅ Implemented |
| Kyber ML admin alerts/audit/rollback endpoints | 4 new admin routes added | Medium | ✅ Implemented |
| Background drift monitoring loop | G27 — `_drift_check_periodic` asyncio task, 300 s interval, started in lifespan | Medium | ✅ Implemented |
| ML CI path-based triggers | G26 — path filter + `ml-validate`/`ml-tests`/`ml-docs-check` steps in `repo-health.yml`; `ml-container-build` Makefile target | High | ✅ Implemented |

---

## Implementation Plan (Remaining)

### Immediate (blocking staging) — COMPLETE ✅
1. ✅ Add dedicated `/v1/predict/identity` serving route for identity_resolution
2. ✅ Add Kyber admin ML hooks router at `/v1/admin/kyber/ml/`
3. ✅ Add CI gate for ML registry drift validation (`scripts/validate_ml_registry.py`)
4. ✅ Add `/ready` readiness probe with freshness SLA gate
5. ✅ Wire `DataFreshnessSLATracker` into serving at startup

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
| Monitoring | ✅ | 🔧 | 🔧 |
| Investor demo | ✅ (synthetic labeled) | N/A | N/A |

> **Note**: "Investor demo" uses synthetic-trained artifacts explicitly labeled as such. These are never promoted to production and all responses include `synthetic_data: true`.

## Model governance gates

The registry now carries per-model governance metadata (`allowed_training_purposes`,
`requires_privacy_review`, `requires_bias_audit`, `requires_model_card`,
`requires_dataset_card`, `requires_training_manifest`, `production_promotion_allowed`),
and `artifact_registry.promote_artifact` blocks staging/promotion when required
governance artifacts (model card, dataset card, privacy review, training manifest,
bias audit) are missing. The backend enforces two additional gates
(`services/model_governance`, see `docs/source-of-truth/MODEL_GOVERNANCE.md`):

- **TrainingDataGate** — consent-scoped training-data admission: data collected
  under non-trainable purposes (`web3`/`credit`/`location`) or purposes needing a
  separate model-training opt-in (`financial_activity`/`economic_observability`/
  `cross_chain_observability`) is quarantined, as are unconsented identity-derived
  labels.
- **InferencePolicyGate** — every inference records a `serve_inference` consent
  PolicyDecision; fail-closed under `ML_INFERENCE_POLICY_ENFORCE` or a
  `fail_closed_required` model.

These are enforced in CI by `scripts/validate_ml_registry.py` and
`scripts/validate_model_governance.py`.
