---
title: ML Security Threat Model
slug: ai/ml-security-threat-model
section: ai
visibility: I
audience: [ai, dev-senior, architect, security]
status: stable
since_version: "8.9.0"
canonical_owner: ml@aether
source_files:
  - security/model_extraction_defense/__init__.py
  - security/model_extraction_defense/defense_layer.py
  - security/model_extraction_defense/rate_limiter.py
  - ML Models/aether-ml/common/artifact_registry.py
  - ML Models/aether-ml/serving/src/api.py
  - Backend Architecture/aether-backend/services/ml_serving/routes.py
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: "4e6fdad"
---

# ML Security Threat Model

> Threat inventory, control mapping, and residual risk for the Aether ML stack
> as of v8.9.0. Covers model extraction, artifact integrity, serving authentication,
> and inference-time attacks.

## Threat Categories

### T1 — Model Extraction

**Description:** An adversary queries prediction endpoints at high volume or with
crafted inputs to reconstruct a surrogate model, stealing IP embedded in training
data and model weights.

**Affected models:** All 9 serving endpoints, particularly `intent_prediction`,
`bot_detection`, and `churn_prediction` (highest commercial value).

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| Per-key query rate limiter (sliding window) | `rate_limiter.QueryRateLimiter` | ✅ |
| Redis-backed distributed budget (multi-replica safe) | `rate_limiter.RedisRateLimiter` | ✅ (when `REDIS_URL` set) |
| Adaptive output perturbation | `output_perturbation.py` | ✅ |
| Watermarking (canary tracking) | `watermarking.py` | ✅ |
| Batch size inspection (all rows examined) | `defense_layer.py` | ✅ |
| Canary detector (known extraction patterns) | `canary_detector.py` | ✅ |
| Extraction monitor (event log + summary) | `monitor.ExtractionDefenseMonitor` | ✅ |
| Prometheus alert: extraction attack | `deploy/observability/prometheus/alert_rules.yml` | ✅ |

**Residual risk:** In-memory budget falls back when Redis is unavailable. Multi-replica
deployments without Redis allow per-replica quota multiplication. Mitigated by
fail-closed Redis requirement in staging/production (`AETHER_ENV in {staging, production}`).

---

### T2 — Artifact Tampering

**Description:** An adversary replaces a model artifact (`model.joblib`,
`preprocessing.joblib`) with a backdoored version, causing the serving layer to
load malicious weights or transformers.

**Affected surface:** Artifact store (local or S3), deployment pipeline.

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| SHA-256 checksum on every artifact | `artifact_registry.ArtifactMetadata` | ✅ |
| HMAC-SHA256 signing (`ARTIFACT_SIGNING_KEY`) | `artifact_registry.py` | ✅ (⚠️ requires key provisioning) |
| Fail-closed on missing key in staging/production | `artifact_registry.py` | ✅ |
| Atomic save (`.tmp` + `os.replace`) | `ArtifactMetadata.save()` | ✅ |
| Promotion audit log (append-only JSONL) | `{model_dir}/promotion_audit.jsonl` | ✅ |
| Rollback to prior promoted version | `rollback_artifact()` | ✅ |
| Prometheus alert: signature failure | `alert_rules.yml` | ✅ |

**Residual risk:** Signing is skipped in local/dev when `ARTIFACT_SIGNING_KEY` is
absent. Production deployment is gated on key provisioning via Secrets Manager
(external prerequisite).

**S3 artifact store:** AES256 SSE enforced. Public access blocked. Least-privilege
IAM read/write policies. Versioning enabled with 90-day noncurrent expiry.

---

### T3 — Serving Authentication Bypass

**Description:** An adversary calls ML serving endpoints directly, bypassing
backend gateway access controls and tenant isolation.

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| Service token auth (`X-Service-Token` vs `ML_SERVICE_TOKEN`) | `serving/src/api.py` | ✅ (⚠️ requires token provisioning) |
| Token skipped only in local/dev (env absent) | `_require_service_token` dependency | ✅ |
| Backend proxies all ML requests (single entry point) | `ml_serving/routes.py` | ✅ |
| Extraction defense applied before cache lookup | `defense_layer.py` | ✅ |
| Versioned cache keys (artifact_version + contract_hash) | `shared/cache/cache.py` | ✅ |

**Residual risk:** mTLS between backend and ML serving is not yet implemented
(documented path; requires certificate provisioning). `ML_SERVICE_TOKEN` is a
shared secret — rotation requires coordinated backend + serving redeploy.

---

### T4 — Feature Contract Violation / Training-Serving Skew

**Description:** An adversary (or misconfiguration) supplies features that differ
in schema, range, or semantics from the training distribution, causing the model to
produce unreliable predictions that may be exploitable.

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| Feature contract validation on every prediction request | `feature_contracts.validate_features()` | ✅ |
| Declared min/max bounds, finiteness, and unknown-key rejection enforced at the serving boundary (HTTP 422) | `serving/src/api.py` `_validated_frame()` | ✅ |
| `ContractMismatchError` in strict mode on schema hash mismatch | `feature_contracts.py` | ✅ |
| Preprocessing bundle loaded from artifact (no runtime reconstruction) | `serving` artifact loader | ✅ |
| `feature_contract.json` snapshot stored with every artifact | `train.py` | ✅ |
| Schema hash covers dtype, range, nullable, aliases, unit, freshness SLA | `_compute_schema_hash()` | ✅ |
| Freshness SLA enforcement per feature group | `DataFreshnessSLATracker` | ✅ |
| Prometheus alert: freshness breach | `alert_rules.yml` | ✅ |

**Residual risk:** Freshness SLA is per feature group, not per-row. Stale features
from a single source can pass if other sources are fresh. Mitigated by per-group
SLA thresholds in feature contracts.

---

### T5 — Privilege Escalation via Batch Headers

**Description:** A caller supplies `X-Batch-Privilege: elevated` or similar
caller-controlled headers to bypass per-key extraction budgets.

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| `X-Batch-Privilege` header ignored; privilege level from server config | `defense_layer.py` | ✅ |
| Batch inspection covers all rows (not just first) | `defense_layer.py` | ✅ |
| Budget enforced regardless of claimed privilege | `rate_limiter.py` | ✅ |

**Residual risk:** None known at code level. External prerequisite: API key to
privilege-level mapping stored in Secrets Manager (not caller-controlled).

---

### T6 — Data Poisoning via Synthetic Fixtures in Production

**Description:** An adversary or misconfiguration causes production training to
run on synthetic deterministic fixtures, producing models that are not grounded
in real user behavior and may be gameable.

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| `test_synthetic_artifact_not_production_allowed` gate | `tests/unit/test_training_pipeline.py` | ✅ |
| `synthetic: true` flag in `dataset_manifest.json` | `train.py` | ✅ |
| `ArtifactMetadata.promotion_state` blocks promotion of synthetic artifacts | `artifact_registry.py` | ✅ |

**Residual risk:** Production training on real data requires external data
provisioning (S3 or PostgreSQL). Until real data is wired, all trained models
are synthetic-only and cannot be promoted to production.

---

### T7 — Container Privilege Escalation

**Description:** A compromised process inside an ML serving container escalates
to root and modifies model artifacts or serving code.

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| Non-root `aether` user (uid/gid 1001) in all 4 Docker stages | `Dockerfile` | ✅ |
| `/opt/ml/models` owned by `aether` user | `Dockerfile` | ✅ |
| HEALTHCHECK targets correct port (8080) | `Dockerfile` | ✅ |

**Residual risk:** Read-only root filesystem not enforced at Dockerfile level
(recommended: add `--read-only` in compose/K8s pod spec).

---

### T8 — Drift-Based Prediction Degradation

**Description:** Data distribution shifts post-deployment, causing model predictions
to degrade silently. Adversaries exploiting this can obtain consistently miscategorized
outputs.

**Controls implemented:**

| Control | Location | State |
|---------|----------|-------|
| Baseline distribution stored per artifact (`baseline.joblib`) | `train.py` | ✅ |
| Drift detector (statistical comparison against baseline) | `monitoring/monitor.py DriftDetector` | ✅ |
| Background drift detection loop (300s interval via asyncio task) | `serving/src/api.py lifespan` | ✅ |
| Prometheus alert: critical drift | `alert_rules.yml` | ✅ |

**Residual risk:** Drift detection requires a loaded baseline. If baseline is
missing from artifact package, drift check degrades to no-op. Mitigated by
artifact completeness gate in CI.

---

## Control Coverage Summary

| Threat | Controls Implemented | Residual Risk Level |
|--------|---------------------|---------------------|
| T1 Model Extraction | Rate limiting + perturbation + watermarking + monitoring | Low (Redis required in prod) |
| T2 Artifact Tampering | HMAC signing + atomic save + audit log + rollback | Low (key provisioning required) |
| T3 Auth Bypass | Service token + gateway proxy | Medium (mTLS not yet implemented) |
| T4 Feature Skew | Contract validation + preprocessing bundle + freshness | Low |
| T5 Privilege Escalation (headers) | Header ignored + all-row batch inspection | Low |
| T6 Data Poisoning | Synthetic gate + manifest flag + promotion block | Low (real data provisioning required) |
| T7 Container Escalation | Non-root user across all stages | Low (read-only FS recommended) |
| T8 Drift Degradation | Baseline + drift detection + background loop + alert | Low |

## External Prerequisites for Full Security Posture

| Prerequisite | Threat Mitigated |
|---|---|
| `ARTIFACT_SIGNING_KEY` in Secrets Manager | T2 |
| `ML_SERVICE_TOKEN` in Secrets Manager | T3 |
| Redis in staging/production | T1 (distributed budget) |
| mTLS between backend and ML serving | T3 (defense-in-depth) |
| Real training data (S3 / PostgreSQL) | T6 |
| Read-only container FS (K8s pod spec) | T7 |

## Model-governance controls (consent-scoped training & inference)

Additive controls that harden the data-provenance surface (see
`docs/source-of-truth/MODEL_GOVERNANCE.md`):

| Control | Mitigates |
|---|---|
| **TrainingDataGate** — consent-scoped admission: quarantines data collected under non-trainable purposes, purposes requiring a separate training opt-in, and unconsented identity-derived labels | T6 Data Poisoning / unlawful training data |
| **Promotion governance gate** — `artifact_registry.promote_artifact` blocks staging/promotion when a required governance artifact (model card, dataset card, privacy review, training manifest, bias audit) is missing, and honors `production_promotion_allowed` | T2 / T6 (unreviewed model reaching production) |
| **InferencePolicyGate** — every inference records a `serve_inference` consent PolicyDecision in the shared audit ledger; fail-closed under `ML_INFERENCE_POLICY_ENFORCE` or a `fail_closed_required` model | Unconsented inference / missing audit evidence |

Enforced in CI by `scripts/validate_model_governance.py` and
`scripts/validate_ml_registry.py`.
