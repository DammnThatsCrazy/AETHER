# Model Extraction Defense v8.3.1

Modular defense layer against model extraction and knowledge distillation attacks on the Aether ML serving pipeline.

---

## Architecture

```
                          ┌──────────────────────────────┐
                          │        API Gateway           │
                          │  (Auth + Base Rate Limiting)  │
                          └──────────────┬───────────────┘
                                         │
                          ┌──────────────▼───────────────┐
                          │  Extraction Defense Middleware │
                          │                               │
                          │  ┌─────────────────────────┐  │
                          │  │   PRE-REQUEST CHECKS     │  │
                          │  │                          │  │
                          │  │  1. Query Rate Limiter   │  │
                          │  │     (per-key + per-IP)   │  │
                          │  │                          │  │
                          │  │  2. Canary Detector      │  │
                          │  │     (trap input check)   │  │
                          │  │                          │  │
                          │  │  3. Pattern Detector     │  │
                          │  │     (sweep / entropy /   │  │
                          │  │      timing analysis)    │  │
                          │  │                          │  │
                          │  │  4. Risk Scorer          │  │
                          │  │     (aggregate signal)   │  │
                          │  └────────────┬────────────┘  │
                          │               │ blocked?       │
                          │          ┌────┴────┐           │
                          │          │ 429/403 │           │
                          │          └─────────┘           │
                          └──────────────┬───────────────┘
                                         │ allowed
                          ┌──────────────▼───────────────┐
                          │      Model Inference          │
                          │   (existing pipeline, no      │
                          │    modifications required)    │
                          └──────────────┬───────────────┘
                                         │ raw output
                          ┌──────────────▼───────────────┐
                          │  POST-RESPONSE PROCESSING     │
                          │                               │
                          │  ┌─────────────────────────┐  │
                          │  │  Output Perturbation     │  │
                          │  │  • Logit noise           │  │
                          │  │  • Top-k clipping        │  │
                          │  │  • Entropy smoothing     │  │
                          │  │  • Precision rounding    │  │
                          │  └────────────┬────────────┘  │
                          │  ┌────────────▼────────────┐  │
                          │  │  Watermark Embedding     │  │
                          │  │  • Probabilistic bias    │  │
                          │  │  • Keyed HMAC pattern    │  │
                          │  └─────────────────────────┘  │
                          └──────────────┬───────────────┘
                                         │ safe output
                          ┌──────────────▼───────────────┐
                          │        HTTP Response          │
                          └──────────────────────────────┘
```

---

## Components

### 1. Query Rate Limiter

**File:** `security/model_extraction_defense/rate_limiter.py`

Dual-axis sliding window rate limiter tracking both API key and IP address independently. Prevents:
- Single-key high-velocity extraction
- Multi-key attacks from a single IP
- Batch endpoint abuse (cost-based token accounting)

Three time windows per axis: per-minute, per-hour, per-day.

### 2. Query Pattern Detector

**File:** `security/model_extraction_defense/pattern_detector.py`

Maintains a sliding window of recent queries per client and computes four anomaly signals:

| Signal | Detects | Method |
|--------|---------|--------|
| Sweep score | Systematic feature sweeps | Per-feature variance concentration |
| Similarity score | Decision boundary probing | Pairwise cosine similarity clustering |
| Entropy score | Uniform random probing | Feature histogram entropy vs max entropy |
| Timing score | Bot-like fixed-interval queries | Inter-query timing coefficient of variation |

Aggregate anomaly score: weighted mean with max-boost.

### 3. Output Perturbation Layer

**File:** `security/model_extraction_defense/output_perturbation.py`

Applies configurable stochastic noise to model outputs:

| Strategy | Effect |
|----------|--------|
| Logit noise | Gaussian noise added to probabilities |
| Top-k clipping | Zero out all but top-k class probabilities |
| Entropy smoothing | Blend predictions toward uniform distribution |
| Precision rounding | Reduce decimal precision of outputs |

All perturbation scales with the extraction risk score — low risk clients experience near-zero noise; high risk clients get aggressive degradation.

### 4. Model Watermarking

**File:** `security/model_extraction_defense/watermark.py`

Embeds a probabilistic signature in outputs using HMAC-derived bias patterns:
- Deterministic per-query bias from `secret_key + query_fingerprint`
- Zero-sum bias (preserves probability mass)
- Undetectable per-query, statistically significant over many queries
- Verification: correlate suspect model outputs against expected bias patterns

### 5. Canary Input Detector

**File:** `security/model_extraction_defense/canary_detector.py`

Generates synthetic "impossible" feature vectors from a secret seed. If a query matches a canary:
- Strong evidence of systematic input-space exploration
- Triggers configurable response: throttle, block, or alert
- Applies cooldown period to the client

Three canary strategies: sparse (near-zero), extreme (high-magnitude), and patterned (alternating).

### 6. Extraction Risk Scorer

**File:** `security/model_extraction_defense/risk_scorer.py`

Combines all signals into a single `extraction_risk` score in `[0, 1]`:

| Score Range | Tier | Response |
|-------------|------|----------|
| 0.0 – 0.3 | Normal | Minimal noise (1x multiplier) |
| 0.3 – 0.6 | Elevated | Moderate noise (3x multiplier) |
| 0.6 – 0.8 | High | Aggressive noise (8x multiplier) |
| 0.8 – 1.0 | Critical | Maximum degradation (15x), consider blocking |

Uses EMA smoothing to prevent single-query spikes and applies time decay when queries stop.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_EXTRACTION_DEFENSE` | `false` | Master switch for the defense layer |
| `ENABLE_OUTPUT_NOISE` | `true` | Enable output perturbation |
| `ENABLE_WATERMARK` | `true` | Enable watermark embedding |
| `ENABLE_QUERY_ANALYSIS` | `true` | Enable pattern detection and risk scoring |
| `WATERMARK_SECRET_KEY` | (default) | **MUST change in production** — secret for watermark generation |
| `CANARY_SECRET_SEED` | (default) | **MUST change in production** — seed for canary input generation |

### Enabling the Defense Layer

```bash
# Enable in production
export ENABLE_EXTRACTION_DEFENSE=true
export WATERMARK_SECRET_KEY=your-production-secret-key
export CANARY_SECRET_SEED=your-production-canary-seed
```

### Programmatic Configuration

```python
from security.model_extraction_defense import ExtractionDefenseLayer, ExtractionDefenseConfig
from security.model_extraction_defense.config import RateLimiterConfig

config = ExtractionDefenseConfig(
    enable_extraction_defense=True,
    rate_limiter=RateLimiterConfig(
        key_max_per_minute=100,
        key_max_per_hour=2000,
    ),
)
defense = ExtractionDefenseLayer(config)
```

---

## Integration

The defense layer integrates with the ML serving API via FastAPI middleware. No changes to core model code are required.

### Middleware Flow

1. **Pre-request middleware** (`extraction_defense_middleware`) intercepts all `/v1/predict/*` requests
2. Extracts API key, IP, and features from the request
3. Runs rate limit check, canary detection, pattern analysis, and risk scoring
4. If blocked: returns 429 (rate limit) or 403 (security policy)
5. If allowed: stores risk score on `request.state` for post-response use
6. **Post-response helper** (`_apply_output_defense`) perturbs and watermarks individual outputs within each endpoint

### Endpoint Integration

Each prediction endpoint calls `_apply_output_defense()` on probability/score outputs:

```python
# Before:
confidence = round(confidence, 4)

# After:
confidence = _apply_output_defense(request, confidence, req.features)
```

The helper returns the value unchanged when defense is disabled, so no conditional logic is needed in endpoints.

---

## Operational Guidance

### Monitoring Metrics

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| `extraction_risk_score` per client | Risk scorer | > 0.6 sustained |
| `canary_trigger_count` | Canary detector | Any trigger |
| `rate_limit_exceeded` per key/IP | Rate limiter | > 10/hour |
| `pattern_anomaly_flags` | Pattern detector | `systematic_feature_sweep` |
| `watermark_verification_score` | Watermark verifier | Used for forensics |

### Verifying Watermarks

If you suspect a model was extracted from Aether:

```python
from security.model_extraction_defense import ModelWatermark
from security.model_extraction_defense.config import WatermarkConfig

wm = ModelWatermark(WatermarkConfig(secret_key="your-production-key"))

# Collect outputs from the suspect model on probe inputs
probe_features = [...]  # list of feature dicts
suspect_outputs = [suspect_model.predict(f) for f in probe_features]
fingerprints = [ModelWatermark.fingerprint_features(f) for f in probe_features]

if wm.is_watermarked(suspect_outputs, fingerprints):
    print("Watermark detected — model was extracted from Aether")
```

### Tuning Thresholds

Start conservative and tighten based on production data:

1. Deploy with `ENABLE_EXTRACTION_DEFENSE=true` but high rate limits
2. Monitor risk scores and pattern flags for 1-2 weeks
3. Identify the natural distribution of legitimate usage
4. Tighten limits to 2-3x the observed p99 of legitimate traffic
5. Enable canary detection once you've validated false positive rates

### Cleanup

The defense layer maintains in-memory state. Run periodic cleanup to prevent memory growth:

```python
defense.cleanup()  # Remove expired rate limit buckets, old query records, decayed risk states
```

In production, call this every 5-10 minutes via a background task or Celery beat schedule.

---

## Files

| File | Description |
|------|-------------|
| `security/model_extraction_defense/__init__.py` | Public API and re-exports |
| `security/model_extraction_defense/config.py` | All configuration dataclasses |
| `security/model_extraction_defense/rate_limiter.py` | Dual-axis sliding window rate limiter |
| `security/model_extraction_defense/pattern_detector.py` | Query pattern anomaly detection |
| `security/model_extraction_defense/output_perturbation.py` | Stochastic output perturbation |
| `security/model_extraction_defense/watermark.py` | Probabilistic watermark embedding/verification |
| `security/model_extraction_defense/canary_detector.py` | Canary input generation and detection |
| `security/model_extraction_defense/risk_scorer.py` | Aggregated extraction risk scoring |
| `security/model_extraction_defense/defense_layer.py` | Facade orchestrating all components |
| `ML Models/aether-ml/serving/src/api.py` | Integrated middleware and endpoint hooks |
| `tests/security/test_model_extraction_defense.py` | Comprehensive test suite |
| `EXTRACTION_DEFENSE_AUDIT.md` | Initial audit report and threat model |
