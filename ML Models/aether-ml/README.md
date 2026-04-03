# Aether ML

![Version](https://img.shields.io/badge/version-8.7.0-blue)
![Python](https://img.shields.io/badge/python-%3E%3D3.10-brightgreen)
![PyTorch](https://img.shields.io/badge/PyTorch-2.2%2B-ee4c2c)
![TensorFlow](https://img.shields.io/badge/TensorFlow-2.15%2B-ff6f00)
![License](https://img.shields.io/badge/license-Proprietary-red)
![Build](https://img.shields.io/badge/build-passing-brightgreen)

Production-grade machine learning system powering Aether's behavioral analytics, Web3 intelligence, and campaign attribution. Nine models span two deployment tiers -- edge inference for sub-100ms browser and mobile predictions, and server-side models running on SageMaker and ECS for heavy analytical workloads.

---

## Table of Contents

- [Model Catalog](#model-catalog)
- [Architecture](#architecture)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [Model Details](#model-details)
- [Serving API](#serving-api)
- [Feature Pipeline](#feature-pipeline)
- [Monitoring](#monitoring)
- [Development](#development)
- [Repository Structure](#repository-structure)
- [License](#license)

---

## Model Catalog

### Edge Models -- Browser / Mobile, < 100ms

| # | Model | Framework | Algorithm | Latency | Export Format | Use Case |
|---|-------|-----------|-----------|---------|---------------|----------|
| 1 | Intent Prediction | scikit-learn | Logistic Regression (planned GRU upgrade) | < 10ms | TF.js | Predict next user action in real time to personalize UI and pre-fetch content |
| 2 | Bot Detection | scikit-learn | Random Forest (100 trees) | < 5ms | ONNX | Classify sessions as human or bot using behavioral signals (mouse entropy, timing variance) |
| 3 | Session Scoring | scikit-learn | Logistic Regression | < 5ms | TF.js | Score session engagement quality for real-time segmentation and trigger-based campaigns |

### Server Models -- SageMaker / ECS

| # | Model | Framework | Algorithm | Retrain Cadence | Instance Type | Use Case |
|---|-------|-----------|-----------|-----------------|---------------|----------|
| 4 | Identity Resolution | PyTorch | Graph Neural Network (GAT) | Daily | ml.g4dn.xlarge | Link anonymous visitors to known identities across devices and sessions |
| 5 | Journey Prediction | PyTorch | LSTM Encoder-Decoder + Attention | Weekly | ml.g4dn.xlarge | Predict the next steps in a user journey from ordered event sequences |
| 6 | Churn Prediction | XGBoost | Gradient Boosted Trees | Bi-weekly | ml.m5.2xlarge | Identify users at risk of churning based on behavioral and transactional features |
| 7 | Lifetime Value | XGBoost + scikit-learn | Ensemble (BG/NBD + Gamma-Gamma + XGBoost Regressor) | Weekly | ml.m5.2xlarge | Estimate customer lifetime revenue for prioritization and budget allocation |
| 8 | Anomaly Detection | scikit-learn + PyTorch | Isolation Forest + AutoEncoder | Weekly | ml.m5.xlarge | Detect traffic anomalies, fraud patterns, and infrastructure issues from hourly aggregates |
| 9 | Campaign Attribution | Custom | Shapley Values + Heuristic Models | Weekly | ml.m5.xlarge | Compute multi-touch attribution across marketing channels using game-theoretic methods |

---

## Architecture

```
                          AETHER ML PIPELINE
 ===================================================================

  Raw Events              Feature Layer              Model Training
 +-----------+      +----------------------+      +----------------+
 | Kafka /   | ---> | Feature Pipeline     | ---> | Training       |
 | Kinesis   |      | (Batch + Streaming)  |      | Pipelines      |
 | Streams   |      |                      |      |                |
 +-----------+      | - Feature Registry   |      | - Optuna       |
                    | - Redis + S3 Store   |      |   Hyperopt     |
                    | - Schema Validation  |      | - Cross-Val    |
                    +----------+-----------+      | - Bias Audit   |
                               |                  +-------+--------+
                               |                          |
                               v                          v
                    +----------------------+      +----------------+
                    | Feature Store        |      | MLflow         |
                    | (Redis + S3)         |      | Model Registry |
                    +----------+-----------+      +-------+--------+
                               |                          |
                               |                  +-------v--------+
                               |                  | Optimization   |
                               |                  | Pipeline       |
                               |                  | - Quantization |
                               |                  | - Distillation |
                               |                  | - Pruning      |
                               |                  +-------+--------+
                               |                          |
              +----------------+--------------------------+-------+
              |                |                                   |
              v                v                                   v
     +----------------+ +--------------+              +-------------------+
     | Edge Runtime   | | FastAPI      |              | SageMaker         |
     | (ONNX / TFLite)| | Serving API  |              | Endpoints         |
     |                | |              |              |                   |
     | - Intent       | | - REST API   |              | - Identity (GNN)  |
     | - Bot Detect   | | - Redis      |              | - Journey (LSTM)  |
     | - Session Score| |   Cache      |              | - Churn (XGB)     |
     +----------------+ | - Batch      |              | - LTV (Ensemble)  |
              |         |   Predictor  |              | - Anomaly (IF+AE) |
              v         +--------------+              | - Attribution     |
     +----------------+        |                      +-------------------+
     | Browser / Mobile|       |                               |
     | (TF.js, CoreML) |       +-------------------------------+
     +----------------+                        |
                                               v
                                      +----------------+
                                      | Monitoring     |
                                      | - Drift Detect |
                                      | - Perf Monitor |
                                      | - CloudWatch   |
                                      | - SNS / Slack  |
                                      +----------------+
```

---

## Features

**Training and Evaluation**
- Unified training runner for all 9 models with per-model configuration
- Optuna-based Bayesian hyperparameter optimization with early pruning
- k-fold cross-validation with stratified splits
- Bias auditing across demographic groups
- Champion/challenger model comparison
- MLflow experiment tracking, model versioning, and artifact storage

**Feature Engineering**
- Batch feature pipeline via SageMaker Processing
- Streaming feature computation from Kafka and Kinesis
- Feature registry with schema enforcement, lineage tracking, and versioning
- Web3-specific features: transaction counts, chain usage, gas metrics

**Serving and Inference**
- FastAPI inference server with endpoints for all 9 models
- Redis-backed prediction caching for repeated queries
- Batch predictor for bulk inference workloads
- Edge inference runtime supporting ONNX, TFLite, and scikit-learn models

**Edge Export**
- TensorFlow.js for browser deployment
- ONNX for cross-platform inference
- TFLite for mobile (Android)
- CoreML for iOS

**Monitoring and Alerting**
- Data drift detection (PSI for numeric, chi-squared for categorical)
- Performance degradation tracking against training baselines
- Prediction distribution shift analysis
- CloudWatch metrics with SNS and Slack alerting

**Infrastructure**
- Multi-stage Docker builds for training, serving, features, and monitoring
- Docker Compose local stack with Redis, MLflow, Prometheus, and Jupyter
- SageMaker integration for training jobs and hosted endpoints

---

## Installation

**Prerequisites:** Python >= 3.10, pip

### Standard Install (all dependencies)

```bash
pip install -e .
```

### Development Install (includes testing, linting, and notebook tools)

```bash
pip install -e ".[dev]"
```

### Optional: Docker Stack

```bash
# Start full local development stack (Redis, MLflow, Prometheus, Jupyter)
docker compose -f docker/docker-compose.yml up -d
```

### Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| torch | >= 2.2.0 | GNN (Identity Resolution), LSTM (Journey Prediction), AutoEncoder (Anomaly) |
| tensorflow | >= 2.15.0 | TF.js and TFLite export |
| scikit-learn | >= 1.4.0 | Edge models, Isolation Forest, preprocessing |
| xgboost | >= 2.0.0 | Churn prediction, LTV ensemble |
| mlflow | >= 2.11.0 | Experiment tracking, model registry |
| fastapi | >= 0.110.0 | Inference server |
| onnx / onnxruntime | >= 1.15.0 / >= 1.17.0 | Edge model export and runtime |
| redis | >= 5.0.0 | Prediction caching, feature store |
| boto3 | >= 1.34.0 | SageMaker, S3 integration |
| networkx | >= 3.2.0 | Graph construction for Identity Resolution |
| lifetimes | >= 0.11.0 | BG/NBD and Gamma-Gamma models for LTV |

---

## Quick Start

### Train a Model

```bash
# Train a single model
bash scripts/dev.sh train churn_prediction

# Train all 9 models
bash scripts/dev.sh train all
```

### Start the Serving API

```bash
# Start FastAPI inference server
bash scripts/dev.sh serve
```

The server starts at `http://localhost:8000`. See [Serving API](#serving-api) for available endpoints.

### Export an Edge Model

```bash
# Export edge models for browser/mobile deployment
bash scripts/dev.sh export

# Supported formats: tfjs, onnx, tflite, coreml
```

### Run with Docker

```bash
# Start full stack (serving + Redis + MLflow + Prometheus + Jupyter)
bash scripts/dev.sh docker-up
```

### Make a Prediction

```bash
# Churn prediction
curl -X POST http://localhost:8000/v1/predict/churn \
  -H "Content-Type: application/json" \
  -d '{"user_id": "usr_123", "features": {"days_since_last_visit": 14, "session_count_30d": 3}}'

# Bot detection
curl -X POST http://localhost:8000/v1/predict/bot \
  -H "Content-Type: application/json" \
  -d '{"session_id": "sess_456", "features": {"mouse_entropy": 0.12, "timing_variance": 0.03}}'
```

---

## Configuration Reference

Model training configurations live in `training/configs/model_configs.py`. Each model has its own configuration class. SageMaker-specific settings are in `training/configs/sagemaker.py`.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MLFLOW_TRACKING_URI` | MLflow server URL | `http://localhost:5000` |
| `REDIS_URL` | Redis connection string for caching and feature store | `redis://localhost:6379` |
| `AWS_DEFAULT_REGION` | AWS region for SageMaker and S3 | `us-east-1` |
| `MODEL_REGISTRY_S3_BUCKET` | S3 bucket for model artifacts | -- |
| `SAGEMAKER_ROLE_ARN` | IAM role for SageMaker training and endpoints | -- |
| `FEATURE_STORE_S3_PATH` | S3 path prefix for batch feature storage | -- |
| `SERVING_PORT` | Port for the FastAPI inference server | `8000` |
| `SERVING_WORKERS` | Uvicorn worker count | `4` |
| `CACHE_TTL_SECONDS` | Redis prediction cache TTL | `300` |
| `MONITORING_INTERVAL` | Monitoring pipeline run interval | `3600` |
| `SNS_ALERT_TOPIC_ARN` | SNS topic for monitoring alerts | -- |
| `SLACK_WEBHOOK_URL` | Slack webhook for alert notifications | -- |

### Training Configuration Structure

```python
# Example: Churn model config (training/configs/model_configs.py)
{
    "model_name": "churn_prediction",
    "algorithm": "xgboost",
    "hyperparameters": {
        "max_depth": 6,
        "learning_rate": 0.1,
        "n_estimators": 500,
        "subsample": 0.8,
    },
    "cross_validation": {
        "n_splits": 5,
        "stratified": True,
    },
    "bias_audit": {
        "protected_attributes": ["region", "device_type"],
    },
}
```

---

## Model Details

### 1. Intent Prediction (Edge)

Predicts the next user action (purchase, browse, leave) in real time from session-level features including click counts, scroll depth, timing, and device information. Uses logistic regression for sub-10ms inference with a planned upgrade path to GRU for sequential pattern capture. Exported as TF.js for browser-side deployment.

### 2. Bot Detection (Edge)

Classifies sessions as human or bot using behavioral biometrics -- mouse movement entropy, click timing variance, scroll patterns, and navigation cadence. A 100-tree Random Forest achieves reliable separation with < 5ms latency. Exported as ONNX for cross-platform edge inference.

### 3. Session Scoring (Edge)

Scores each session's engagement quality on a continuous scale, enabling real-time segmentation and trigger-based campaign activation. Runs as logistic regression in < 5ms. Exported as TF.js.

### 4. Identity Resolution (Server)

Links anonymous visitors to known identities across devices and sessions using a Graph Attention Network (GAT). Constructs a visitor graph from session, device, and behavioral similarity edges, then propagates identity labels through attention-weighted message passing. Retrained daily to incorporate new visitor data. Built with PyTorch and NetworkX.

### 5. Journey Prediction (Server)

Predicts the next steps in a user journey from ordered event sequences using an LSTM encoder-decoder architecture with attention. The encoder processes the historical sequence; the attention mechanism focuses on the most relevant past events; and the decoder generates a probability distribution over possible next actions. Retrained weekly.

### 6. Churn Prediction (Server)

Identifies users at risk of churning using XGBoost gradient-boosted trees over behavioral, transactional, and engagement features. Supports stratified cross-validation and bias auditing across demographic groups. Retrained bi-weekly on a rolling window.

### 7. Lifetime Value Prediction (Server)

Estimates customer lifetime revenue using an ensemble of three components: a BG/NBD model for purchase frequency, a Gamma-Gamma model for monetary value, and an XGBoost regressor for feature-based correction. The ensemble output is used for customer prioritization and budget allocation. Retrained weekly.

### 8. Anomaly Detection (Server)

Detects traffic anomalies, fraud patterns, and infrastructure issues from hourly aggregate metrics. Combines an Isolation Forest for unsupervised outlier detection with a PyTorch AutoEncoder for reconstruction-error-based anomaly scoring. Dual signals are merged to reduce false positives. Retrained weekly.

### 9. Campaign Attribution (Server)

Computes multi-touch marketing attribution across channels using Shapley value computation (game-theoretic fair allocation) alongside heuristic models (first-touch, last-touch, linear, time-decay). Produces per-channel contribution scores for budget optimization. Retrained weekly.

---

## Serving API

The FastAPI inference server exposes the following endpoints:

```
POST /v1/predict/intent          Real-time intent prediction
POST /v1/predict/bot             Bot vs human classification
POST /v1/predict/session-score   Session engagement scoring
POST /v1/predict/churn           Churn risk prediction
POST /v1/predict/ltv             Lifetime value estimation
POST /v1/predict/journey         Next journey step prediction
POST /v1/predict/attribution     Multi-touch campaign attribution
POST /v1/predict/batch           Batch prediction (any model)
GET  /health                     Health check
GET  /models                     List loaded models
```

All prediction endpoints accept JSON payloads with `user_id` or `session_id` and a `features` map. Responses include the prediction result, model version, and inference latency. The Redis cache layer deduplicates repeated requests within the configured TTL.

---

## Feature Pipeline

The feature layer computes inputs for all 9 models from raw event data. It supports both batch (SageMaker Processing) and streaming (Kafka / Kinesis) modes.

| Feature Group | Features | Used By |
|---------------|----------|---------|
| Session | Click counts, scroll depth, timing, device info | Intent, Session Scoring, Churn |
| Identity | Visit frequency, conversion rate, tenure | Identity Resolution, LTV |
| Behavioral | Mouse entropy, timing variance, scroll patterns | Bot Detection |
| Journey Sequences | Ordered event chains | Journey Prediction |
| Attribution Touchpoints | Channel sequences with timestamps | Campaign Attribution |
| Web3 | Transaction counts, chain usage, gas metrics | Identity Resolution, LTV, Anomaly |
| Anomaly Aggregates | Hourly traffic volumes, error rates | Anomaly Detection |

The Feature Registry (`features/registry.py`) enforces schemas, tracks lineage, and manages feature versioning.

---

## Monitoring

Production monitoring runs on a configurable interval (default: hourly) and covers four dimensions:

**Data Drift Detection**
- Population Stability Index (PSI) for numeric feature distributions
- Chi-squared test for categorical feature distributions
- Configurable thresholds with automatic alerting on breach

**Performance Monitoring**
- Tracks live model metrics against training baselines
- Detects metric degradation (accuracy, AUC, RMSE as appropriate per model)
- Champion/challenger comparison for staged rollouts

**Prediction Distribution**
- Monitors shift in prediction mean, variance, and percentiles
- Flags unexpected changes in prediction volume or distribution shape

**Alerting**
- CloudWatch custom metrics for all monitoring signals
- SNS notifications for threshold breaches
- Slack webhooks for team-level alerting
- PagerDuty integration for critical drift events

---

## Development

### CLI Commands (scripts/dev.sh)

```bash
bash scripts/dev.sh train <model_name|all>    # Train a model or all models
bash scripts/dev.sh serve                      # Start FastAPI inference server
bash scripts/dev.sh test                       # Run full test suite
bash scripts/dev.sh export                     # Export edge models
bash scripts/dev.sh lint                       # Run ruff + mypy
bash scripts/dev.sh docker-up                  # Start Docker Compose stack
```

### Testing

```bash
# Run all tests
bash scripts/dev.sh test

# Run unit tests only
pytest tests/unit/

# Run integration tests only
pytest tests/integration/

# Run with coverage
pytest --cov=. tests/
```

Tests use synthetic data fixtures defined in `tests/conftest.py`, generating realistic data shapes for all model types without requiring access to production data.

### Linting and Type Checking

```bash
# Ruff linter (line length: 120, target: py310)
ruff check .

# Black formatter
black --check .

# Mypy strict type checking
mypy --strict .
```

### Docker

```bash
# Build multi-stage image
docker build -f docker/Dockerfile --target serving -t aether-ml:serving .
docker build -f docker/Dockerfile --target training -t aether-ml:training .

# Run full stack locally
docker compose -f docker/docker-compose.yml up -d

# Stack includes: Redis, MLflow, Prometheus, Jupyter
```

---

## Repository Structure

```
aether-ml/
├── common/src/                    Base classes, feature engineering, data pipeline
│   ├── base.py                    AetherModel ABC, FeatureStore, ModelRegistry, FeatureEngineer
│   ├── preprocessing.py           PreprocessingPipeline: encoding, imputation, scaling, SMOTE
│   ├── validation.py              DataValidator: schema enforcement, statistical checks
│   └── metrics.py                 MetricsCollector: unified metric computation + tracking
├── edge/                          Edge models (browser + mobile, < 100ms)
│   ├── models.py                  IntentPrediction, BotDetection, SessionScorer
│   └── runtime.py                 EdgeInferenceRuntime: ONNX / TFLite / sklearn model runner
├── server/                        Server models (SageMaker / ECS)
│   ├── models.py                  IdentityResolution, Churn, LTV, Anomaly
│   ├── journey_prediction.py      LSTM encoder-decoder with attention mechanism
│   └── campaign_attribution.py    Shapley-based + heuristic multi-touch attribution
├── features/                      Feature engineering layer
│   ├── pipeline.py                Batch (SageMaker Processing) + streaming pipeline
│   ├── registry.py                Feature registry: schema, lineage, versioning
│   └── streaming.py               Kafka / Kinesis real-time feature computation
├── training/                      Training orchestration
│   ├── pipelines/
│   │   ├── train.py               Unified training runner (all 9 models)
│   │   ├── evaluation.py          Champion/challenger, cross-validation, bias auditing
│   │   └── hyperopt.py            Optuna Bayesian optimization with pruning
│   └── configs/
│       ├── model_configs.py       Per-model training configurations
│       └── sagemaker.py           SageMaker training job + endpoint configs
├── serving/src/                   Model serving
│   ├── api.py                     FastAPI inference server (all 9 model endpoints)
│   ├── cache.py                   PredictionCache: Redis-backed result caching
│   └── batch_predictor.py         Batch prediction for bulk inference
├── monitoring/                    Production monitoring
│   ├── monitor.py                 DriftDetector, PerformanceMonitor, MonitoringPipeline
│   └── alerts.py                  CloudWatch metrics, SNS alerting, Slack webhooks
├── optimization/                  Model optimization pipeline
│   ├── pipeline.py                Orchestrates quantization, distillation, pruning
│   ├── quantization.py            Post-training and quantization-aware training
│   ├── distillation.py            Knowledge distillation (teacher-student)
│   └── pruning.py                 Structured and unstructured weight pruning
├── export/
│   └── exporter.py                TF.js, ONNX, TFLite, CoreML converters
├── tests/
│   ├── conftest.py                Synthetic data fixtures for all model types
│   ├── unit/                      Model, feature, and serving unit tests
│   └── integration/               API integration tests
├── docker/
│   ├── Dockerfile                 Multi-stage (training, serving, features, monitoring)
│   └── docker-compose.yml         Local dev stack (Redis, MLflow, Prometheus, Jupyter)
├── scripts/
│   └── dev.sh                     Development CLI (train, serve, test, export, lint)
├── pyproject.toml                 Dependencies + tool configs
├── Makefile                       Build targets
└── README.md
```

---

## License

Proprietary -- All rights reserved. See [LICENSE](LICENSE) for terms.
