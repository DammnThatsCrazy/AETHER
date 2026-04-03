# Model Extraction Defense Audit — Aether Platform v8.7.1

**Date:** 2026-03-17
**Scope:** All ML inference code, API gateway, middleware, model wrappers, monitoring systems

---

## 1. Existing Protections Found

### 1.1 Query Rate Limiting (PARTIAL)

**File:** `Backend Architecture/aether-backend/shared/rate_limit/limiter.py`

- Token bucket algorithm with per-tier limits (FREE/PRO/ENTERPRISE)
- Per-API-key tracking via in-memory dictionary
- 60-second rolling window, standard `X-RateLimit-*` headers
- Applied globally in `middleware/middleware.py` (lines 115-138)

**Gaps:** In-memory only (not distributed). No per-IP tracking. Simple window (not sliding). Easily circumvented with multiple API keys.

### 1.2 Authentication & Tenant Context (IMPLEMENTED)

**File:** `Backend Architecture/aether-backend/middleware/middleware.py`

- API key validation and JWT bearer tokens (lines 100-113)
- Tenant context extracted per request
- Request ID correlation (line 59)

### 1.3 Prediction Caching (IMPLEMENTED)

**File:** `ML Models/aether-ml/serving/src/cache.py`

- Redis-backed prediction cache with per-model TTLs (30s-24h)
- Deterministic cache keys from feature hashes
- Cache returns identical results for repeated queries — useful for performance, but not leveraged for anomaly detection

### 1.4 Fraud Detection Signals (NOT APPLIED TO ML)

**File:** `Backend Architecture/aether-backend/services/fraud/signals.py`

- Bot detection, velocity analysis, device fingerprinting, geographic analysis
- Excellent detection system but only applied to transaction/user-behavior endpoints
- NOT wired into ML inference paths

### 1.5 Drift Monitoring (NOT EXTRACTION-SPECIFIC)

**File:** `ML Models/aether-ml/monitoring/monitor.py`

- PSI, Kolmogorov-Smirnov, Jensen-Shannon divergence on feature distributions
- Monitors data drift in production, not query pattern anomalies

---

## 2. Missing Protections

| Defense | Status | Severity |
|---------|--------|----------|
| Output noise injection / stochastic responses | NOT IMPLEMENTED | **Critical** |
| Logit clipping / response truncation | NOT IMPLEMENTED | **Critical** |
| Model watermarking / fingerprinting | NOT IMPLEMENTED | **Critical** |
| Query pattern anomaly detection | NOT IMPLEMENTED | **Critical** |
| Canary outputs / trap queries | NOT IMPLEMENTED | **High** |
| Differential privacy during inference | NOT IMPLEMENTED | **High** |
| Output entropy throttling | NOT IMPLEMENTED | **High** |
| Per-IP rate limiting | NOT IMPLEMENTED | **Medium** |
| Device/TLS fingerprinting for ML endpoints | NOT IMPLEMENTED | **Medium** |
| Extraction risk scoring | NOT IMPLEMENTED | **Critical** |

---

## 3. Vulnerability Assessment: **HIGH**

### Attack Surface

The ML serving API (`ML Models/aether-ml/serving/src/api.py`) exposes 9 models across 8 prediction endpoints plus a batch endpoint. All return raw model outputs with 4-decimal precision. There is no output perturbation, no watermarking, and no query anomaly detection.

### Critical Vulnerability: Distillation Code

`ML Models/aether-ml/optimization/distillation.py` implements knowledge distillation including soft-label extraction via `predict_proba()`. An attacker could replicate this exact workflow against the API.

### Estimated Attack Complexity: **LOW**

An attacker with a valid API key can:
1. Query `/v1/predict/batch` with 1,000 synthetic feature vectors per request
2. Collect exact probability outputs at 4-decimal precision
3. Train a student model using standard distillation loss
4. Achieve functional model replication in under 30 minutes at minimal API cost

### Risk Rating

| Vector | Risk | Rationale |
|--------|------|-----------|
| Large-scale query sampling | **Critical** | Batch endpoint, no anomaly detection, high precision outputs |
| Gradient-free distillation | **Critical** | Exact soft labels returned, enabling KD without gradients |
| Adaptive querying | **High** | Deterministic outputs allow systematic feature-space exploration |
| Prompt/feature space exploration | **High** | No detection of systematic sweeps or adversarial probing |
| Membership inference | **Medium** | Deterministic outputs leak training data patterns |
| Feature inference | **Medium** | No perturbation means feature importance directly observable |

---

## 4. Files and Modules Inspected

| File | Lines | Finding |
|------|-------|---------|
| `ML Models/aether-ml/serving/src/api.py` | 778 | 9 model endpoints, no extraction defenses |
| `ML Models/aether-ml/serving/src/batch_predictor.py` | 539 | Batch scoring, no defenses |
| `ML Models/aether-ml/serving/src/cache.py` | 381 | Redis cache, defense potential unused |
| `ML Models/aether-ml/server/models.py` | 954 | 4 server models, no watermarking |
| `ML Models/aether-ml/edge/models.py` | ~400 | 3 edge models, no watermarking |
| `ML Models/aether-ml/optimization/distillation.py` | 262 | Enables extraction attacks |
| `ML Models/aether-ml/monitoring/monitor.py` | ~285 | Drift detection only |
| `Backend Architecture/aether-backend/middleware/middleware.py` | 177 | Auth + basic rate limiting |
| `Backend Architecture/aether-backend/shared/rate_limit/limiter.py` | 88 | Token bucket, in-memory |
| `Backend Architecture/aether-backend/services/fraud/signals.py` | ~392 | Fraud signals, not applied to ML |
| `Backend Architecture/aether-backend/services/fraud/engine.py` | ~300 | Fraud engine, not applied to ML |

---

## 5. Threat Model

### Attacker Profile

A sophisticated adversary with:
- One or more valid API keys (obtainable through free tier signup)
- Knowledge of standard model extraction techniques
- Ability to generate synthetic feature vectors across the input space
- Computational resources to train a distilled model

### Attack Scenarios

**Scenario 1 — Bulk Query Distillation**
1. Attacker generates N random feature vectors spanning the input domain
2. Queries `/v1/predict/batch` in chunks of 1,000
3. Collects (features, soft_label) pairs
4. Trains student model via standard KD loss: `L = alpha * KL(student || teacher) + (1-alpha) * CE`
5. At current rate limits (300 RPM enterprise): 300,000 labeled samples/hour
6. Result: functional model clone in <1 hour

**Scenario 2 — Adaptive Probing**
1. Attacker uses active learning to select maximally informative queries
2. Starts with uniform sampling, then focuses on decision boundary regions
3. Achieves higher fidelity with fewer queries (10x more efficient than random)
4. Undetectable by current rate limiter (stays within per-key budget)

**Scenario 3 — Multi-Key Distributed Extraction**
1. Attacker creates N free-tier API keys
2. Distributes queries across keys to stay under per-key rate limits
3. Aggregates responses into single training set
4. Current system has no cross-key anomaly detection

**Scenario 4 — Feature Space Exploration**
1. Attacker systematically varies individual features while holding others constant
2. Maps per-feature sensitivity and interaction effects
3. Reverse-engineers feature engineering pipeline
4. No detection of systematic one-at-a-time sweeps

### Current Architecture Gaps Exploited

```
CLIENT ──> AUTH ──> RATE LIMIT ──> MODEL.PREDICT() ──> RAW OUTPUT
                    (per-key,      (exact proba,        (no noise,
                     in-memory,     4-decimal,           no watermark,
                     simple          deterministic)       no anomaly
                     window)                              detection)
```

### Recommended Architecture

```
CLIENT ──> AUTH ──> EXTRACTION    ──> MODEL.PREDICT() ──> OUTPUT         ──> RESPONSE
                    DEFENSE LAYER                         PERTURBATION
                    ├─ Query rate limiter (per-key + IP)
                    ├─ Pattern detector (sweep/probe detection)
                    ├─ Canary input detector
                    ├─ Extraction risk scorer
                    │                                     ├─ Logit noise
                    │                                     ├─ Top-k clipping
                    │                                     ├─ Watermark embedding
                    │                                     └─ Entropy smoothing
                    └─ Anomaly alerting
```
