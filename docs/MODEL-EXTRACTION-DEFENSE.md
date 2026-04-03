# Model Extraction Defense v8.7.1

Modular defense layer against model extraction and knowledge distillation attacks on the Aether ML serving pipeline.

**v9.0.0 — Extraction Defense Mesh**: Multi-identity distributed budgets, expectation-based extraction signals, sibling extraction risk score, policy-driven disclosure control, canary/lineage attribution, and comprehensive telemetry.

---

## Architecture

```
                          ┌──────────────────────────────┐
                          │        API Gateway           │
                          │  (Auth + Base Rate Limiting)  │
                          └──────────────┬───────────────┘
                                         │
                          ┌──────────────▼───────────────┐
                          │  Extraction Defense Mesh      │
                          │                               │
                          │  ┌─────────────────────────┐  │
                          │  │  A. IDENTITY FABRIC      │  │
                          │  │  Normalize all caller    │  │
                          │  │  dimensions              │  │
                          │  └──────────┬──────────────┘  │
                          │             │                  │
                          │  ┌──────────▼──────────────┐  │
                          │  │  B. DISTRIBUTED BUDGETS  │  │
                          │  │  Multi-axis Redis checks │  │
                          │  │  per key/IP/device/      │  │
                          │  │  cluster/graph           │  │
                          │  └──────────┬──────────────┘  │
                          │             │                  │
                          │  ┌──────────▼──────────────┐  │
                          │  │  C. EXPECTATION ENGINE   │  │
                          │  │  Self/peer/graph         │  │
                          │  │  baselines + deviation   │  │
                          │  │  signals                 │  │
                          │  └──────────┬──────────────┘  │
                          │             │                  │
                          │  ┌──────────▼──────────────┐  │
                          │  │  D. EXTRACTION SCORER    │  │
                          │  │  Sibling score 0-100     │  │
                          │  │  (NOT merged into Trust) │  │
                          │  └──────────┬──────────────┘  │
                          │             │                  │
                          │  ┌──────────▼──────────────┐  │
                          │  │  E. POLICY ENGINE        │  │
                          │  │  Disclosure control,     │  │
                          │  │  access gating           │  │
                          │  │  (no perturbation)       │  │
                          │  └──────────┬──────────────┘  │
                          │             │                  │
                          │  ┌──────────▼──────────────┐  │
                          │  │  F. ATTRIBUTION/CANARY   │  │
                          │  │  Server-side lineage     │  │
                          │  └──────────┬──────────────┘  │
                          │             │                  │
                          │  ┌──────────▼──────────────┐  │
                          │  │  G. TELEMETRY/ALERTS     │  │
                          │  │  Events, metrics, alerts │  │
                          │  └─────────────────────────┘  │
                          └───────────────────────────────┘
                                         │
                          ┌──────────────▼───────────────┐
                          │      ML Model Inference       │
                          │  (disclosure-controlled output)│
                          └───────────────────────────────┘
```

---

## Defense Mesh Layers

### Layer A — Identity Fabric

Every ML inference request is enriched with a normalized `ExtractionIdentity`:

| Dimension | Source | Required |
|-----------|--------|----------|
| `api_key_id` | Auth middleware | No |
| `tenant_id` | Auth middleware | No |
| `user_id` | JWT payload | No |
| `session_id` | X-Session-ID header | No |
| `source_ip` | Request client | Yes (fallback: 0.0.0.0) |
| `ip_prefix` | /24 prefix clustering | Auto-derived |
| `user_agent_hash` | User-Agent hash | Auto-derived |
| `device_fingerprint` | X-Device-Fingerprint header | No |
| `tls_fingerprint` | X-TLS-Fingerprint header | No |
| `wallet_id` | X-Wallet-ID header | No |
| `identity_cluster_id` | Identity resolution | No |
| `graph_cluster_id` | Graph traversal | No |

**Design rule**: Score with whatever is available. Missing dimensions are tolerated.

### Layer B — Distributed Budget Engine

Redis-backed multi-axis budgets:

| Axis | Tier 1 (Critical) | Tier 2 (High) | Tier 3 (Standard) |
|------|-------------------|---------------|-------------------|
| API Key/min | 30 | 60 | 120 |
| API Key/hour | 500 | 1,000 | 3,000 |
| IP/min | 60 | 120 | 240 |
| Device/hour | 300 | 600 | 1,200 |
| Identity Cluster/hour | 2,000 | 5,000 | 10,000 |
| Graph Cluster/hour | 3,000 | 8,000 | 15,000 |

### Layer C — Extraction Expectation Engine

Internal-only. Detects:

| Signal | What It Detects |
|--------|----------------|
| `self_rate_deviation` | Unusual request rate vs self-history |
| `model_enumeration_signal` | Querying many distinct models |
| `feature_sweep_signal` | Systematic feature-space exploration |
| `boundary_probe_signal` | Probing near decision boundaries |
| `near_duplicate_burst_signal` | Repeated similar queries |
| `batch_usage_deviation` | Unusual batch size patterns |
| `unique_coverage_expansion_signal` | Steadily growing feature coverage |
| `confidence_harvest_signal` | Soft-label harvesting patterns |
| `identity_churn_signal` | Key rotation / device switching |
| `device_geo_contradiction_signal` | Contradictory device/IP combos |

### Layer D — Extraction Risk Scorer

**Independent sibling score to Trust Score.** Not merged.

| Band | Score | Meaning |
|------|-------|---------|
| Green | 0–29 | Normal behavior |
| Yellow | 30–54 | Slightly suspicious |
| Orange | 55–79 | Likely extraction |
| Red | 80–100 | Active attack |

### Layer E — Policy Engine

**No user-visible perturbation.** Disclosure minimization only:

| Band | Confidence | Secondary | Probabilities | Alert |
|------|-----------|-----------|--------------|-------|
| Green | Rounded (2dp) | Yes | Yes | No |
| Yellow | Bucketed (0.1) | No | Yes | No |
| Orange | Bucketed (0.1) | No | No | Yes |
| Red | DENIED | — | — | Yes |

Privileged callers get exact scores and batch access.

### Layer F — Attribution / Canary

Server-side only (no response watermarking):
- Secret canary input families
- Response lineage records
- Attribution fingerprints

### Layer G — Telemetry

Kafka events: `ML_EXTRACTION_REQUEST_SEEN`, `ML_EXTRACTION_SCORE_UPDATED`, `ML_EXTRACTION_POLICY_APPLIED`, `ML_EXTRACTION_CANARY_HIT`, `ML_EXTRACTION_ALERT_OPENED`, `ML_EXTRACTION_CLUSTER_ESCALATED`

---

## Model Sensitivity Tiers

| Tier | Models | Priority |
|------|--------|----------|
| **Tier 1 Critical** | churn_prediction, ltv_prediction, anomaly_detection | Highest business value |
| **Tier 2 High** | intent_prediction, bot_detection, campaign_attribution | Easiest to distill |
| **Tier 3 Standard** | session_scorer, journey_prediction, identity_resolution | Standard protection |

---

## Batch Prediction

`/v1/predict/batch` is **internal/privileged only**. Non-privileged callers receive HTTP 403.

---

## Configuration

```bash
ENABLE_EXTRACTION_MESH=true
EXTRACTION_BUDGET_ENABLED=true
EXTRACTION_EXPECTATION_ENABLED=true
EXTRACTION_POLICY_ENABLED=true
EXTRACTION_ATTRIBUTION_ENABLED=true
EXTRACTION_TELEMETRY_ENABLED=true
EXTRACTION_PRIVILEGED_TENANTS=internal-service
EXTRACTION_BATCH_INTERNAL_ONLY=true
EXTRACTION_OUTPUT_PRECISION=2
EXTRACTION_ALERT_ON_ORANGE=true
EXTRACTION_ALERT_ON_RED=true
```

---

## Legacy Defense Layer

The original `security/model_extraction_defense/` module remains functional and runs as a secondary defense when enabled via `ENABLE_EXTRACTION_DEFENSE=true`. The mesh and legacy layers are complementary — the mesh handles identity correlation and policy, while the legacy layer provides canary detection, output perturbation (when allowed), and watermarking.
