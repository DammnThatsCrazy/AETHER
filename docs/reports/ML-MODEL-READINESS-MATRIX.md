---
title: ML Model Readiness Matrix
slug: ai/ml-model-readiness-matrix
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: ml@aether
source_files: [ML Models/aether-ml/common/model_registry.py, ML Models/aether-ml/common/feature_contracts.py, ML Models/aether-ml/serving/src/api.py, ML Models/aether-ml/training/pipelines/train.py]
estimated_read_minutes: 6
toc_depth: 2
source_hashes:
  ML Models/aether-ml/common/feature_contracts.py: sha256:42b763eaa9d0cd71191a3ab3b7b58f03c5176deff6c550979272449cc671bd99
  ML Models/aether-ml/common/model_registry.py: sha256:6b27000fbdabb8c3c614157cddd68e1ee45da6c1d729a41287c644c5e4d1b113
  ML Models/aether-ml/serving/src/api.py: sha256:d9d1d8dd0cafaa6351737c1a7140a5abe5cb49d4265ccdf694e6361640a2ba4c
  ML Models/aether-ml/training/pipelines/train.py: sha256:98f93d379b93e93aa1e9a80eec03c8d1697408d7b58339e42ef4076a4c4cdbd8
---

# ML Model Readiness Matrix

> Per-model production readiness across training, serving, artifact lifecycle,
> monitoring, and security dimensions. Generated from canonical registry state
> as of v8.9.0.

## Dimension Key

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented and tested |
| ⚠️ | Implemented; external prerequisite required for production |
| ❌ | Not implemented |

## Readiness Matrix

| Model | Algorithm | Preprocessing Bundle | Dataset Manifest | Serving Endpoint | Freshness SLA | Service Token Auth | HMAC Signing | Rollback Capable | Drift Detection | Extraction Defense |
|-------|-----------|---------------------|-----------------|-----------------|--------------|-------------------|-------------|-----------------|-----------------|-------------------|
| `intent_prediction` | GradientBoostingClassifier | ✅ | ✅ | `/v1/predict/intent` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `bot_detection` | IsolationForest + GBM | ✅ | ✅ | `/v1/predict/bot` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `session_scorer` | GradientBoostingRegressor | ✅ | ✅ | `/v1/predict/session` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `identity_resolution` | ClusteringEnsemble | ✅ | ✅ | `/v1/predict/identity` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `journey_prediction` | GradientBoostingClassifier | ✅ | ✅ | `/v1/predict/journey` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `churn_prediction` | XGBClassifier | ✅ | ✅ | `/v1/predict/churn` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `ltv_prediction` | XGBRegressor | ✅ | ✅ | `/v1/predict/ltv` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `anomaly_detection` | IsolationForest | ✅ | ✅ | `/v1/predict/anomaly` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `campaign_attribution` | Shapley multi-touch | ✅ | ✅ | `/v1/predict/attribution` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |

**HMAC Signing (⚠️):** Signing logic is implemented in
`common/artifact_registry.py`. Production requires `ARTIFACT_SIGNING_KEY`
provisioned via Secrets Manager. In staging/production, artifact load fails
closed if the key is absent; in local/dev, signing is skipped.

## Artifact Package Completeness

Each of the 9 trainable models produces the following artifact files on every
training run:

| File | Contents | Produced by |
|------|----------|-------------|
| `model.joblib` | Serialized estimator | `train.py` |
| `preprocessing.joblib` | `ColumnTransformer` + `StandardScaler` pipeline | `train.py` |
| `metadata.json` | Version, training timestamp, HMAC signature | `artifact_registry.py` |
| `dataset_manifest.json` | Source, row count, schema hash, git SHA | `train.py` |
| `metrics.json` | Training + validation metrics | `train.py` |
| `thresholds.json` | Decision thresholds per metric | `train.py` |
| `feature_contract.json` | Contract snapshot at training time | `train.py` |
| `model_card.md` | Algorithm, intent, known limitations | `train.py` |
| `baseline.joblib` | Reference distribution for drift detection | `train.py` |
| `provenance.json` | Git SHA, training config, data hash, environment | `train.py` |
| `pipeline_report.json` | Cross-validation summary, feature importance | `train.py` |

## Feature Contract Coverage

All 9 trainable models have a corresponding feature contract in
`common/feature_contracts.py`. The contract schema hash covers: dtype, range,
nullable, allowed values, default, unit, aliases, aggregation window, freshness
SLA seconds, schema version. A hash mismatch between training-time and
serving-time contracts raises `ContractMismatchError` in strict mode.

The flat-dict serving endpoints (intent, bot, session, churn, ltv, anomaly,
identity) enforce the contract on every request via
`serving/src/api.py::_validated_frame`: missing required features, unknown
keys, non-finite values, and declared min/max range violations are rejected
with HTTP 422 before inference. Integral floats are accepted for int-dtype
features because the JSON request models coerce all numbers to float.

## Serving Endpoint Coverage

All 9 models have a dedicated prediction endpoint registered in
`serving/src/api.py`. The `/v1/predict/batch` endpoint supports all models via
`model_name` dispatch. The backend gateway in
`Backend Architecture/aether-backend/services/ml_serving/routes.py` proxies
requests and applies versioned cache keys
(`aether:ml:prediction:{model}:{entity}:{artifact_version}:{contract_hash}`).

## Data Source Readiness

All models currently train on **synthetic deterministic fixtures** (enforced by
`test_synthetic_artifact_not_production_allowed`). Production training requires:
- Real data via S3 loader (`boto3 + Parquet`) or PostgreSQL loader (`psycopg2 + SQL`)
- `ARTIFACT_STORE=s3` env var pointing to the provisioned S3 bucket
- Data quality gates: minimum rows, max missingness, target distribution, no PII
