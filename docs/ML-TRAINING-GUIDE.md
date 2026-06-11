---
title: ML Model Training Guide
slug: ai/ml-training
section: ai
visibility: P
audience: [ai, dev-senior]
status: stable
since_version: "8.8.0"
source_files:
  - ML Models/aether-ml/training/
canonical_owner: ml@aether
estimated_read_minutes: 4
toc_depth: 3
last_synced_commit: 401ceb7
---
# ML Model Training Guide

## Overview

Aether includes 9 ML models for behavioral analytics. The training pipeline is in `ML Models/aether-ml/training/`.

## Models

| Model | Type | Config |
|-------|------|--------|
| Intent Prediction | Multi-class classification (LogisticRegression) | `training/configs/model_configs.py` |
| Bot Detection | Binary classification (RandomForest) | Same |
| Session Scorer | Regression (LogisticRegression) | Same |
| Churn Prediction | Binary classification (XGBoost) | Same |
| LTV Prediction | Regression (XGBoost) | Same |
| Identity Resolution | Binary classification | Same |
| Journey Prediction | Multi-class | Same |
| Anomaly Detection | Unsupervised (IsolationForest) | Same |
| Campaign Attribution | Multi-touch attribution | Same |

## Local Training (Development)

```bash
# Install ML dependencies
pip install -e ".[ml]"

# Run training with synthetic data
cd "ML Models/aether-ml"
python -m training.pipelines.train --model intent_prediction --data synthetic
python -m training.pipelines.train --model bot_detection --data synthetic
python -m training.pipelines.train --model all --data synthetic
```

This produces `.pkl` files in the local `models/` directory.

## Production Training

Production training requires:
1. **Training data** in PostgreSQL or S3
2. **Feature store** for computed features
3. **Training compute** (local GPU, SageMaker, or equivalent)
4. **Model registry** (S3 bucket or MLflow)

```bash
# Production training (requires real data + compute)
python -m training.pipelines.train \
  --model all \
  --data-source postgresql \
  --output s3://aether-models/v1/ \
  --tracking mlflow
```

## Model Artifacts

Training produces:
- `.pkl` files (scikit-learn, XGBoost serialized models)
- `metadata.json` (model version, training date, metrics)
- Feature pipeline state (preprocessor configuration)

## Serving

The ML serving API (`ML Models/aether-ml/serving/src/api.py`) loads model artifacts at startup:
- If `.pkl` files exist → loads trained models
- If no artifacts → loads in-process stub models (untrained, for development only)

## ML Ingestion Readiness

| Environment | Ready? | Requirements |
|-------------|--------|-------------|
| Local/dev | **YES** | `pip install -e ".[ml]"` + synthetic data |
| Staging | **NO** | PostgreSQL + S3 + training compute + real data sample |
| Production | **NO** | All staging requirements + validated model metrics + A/B test framework |
| Investor demo | **YES** | Local training with synthetic data; predictions will be from trained-on-synthetic models |

## Feature Engineering

The feature pipeline (`features/pipeline.py`) computes 5 feature types:
- Session features (duration, page_views, click_count)
- Behavioral features (scroll_depth, mouse_velocity)
- Identity features (device_count, ip_count)
- Journey features (step sequences, conversion paths)
- Anomaly features (z-scores, deviation metrics)
