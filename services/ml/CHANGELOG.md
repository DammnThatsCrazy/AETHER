# Changelog — aether-ml

## [4.0.0] — 2026-03-01

### Added
- **9 Production ML Models** across edge and server deployment targets
  - Edge: Intent Prediction, Bot Detection, Session Scorer
  - Server: Identity Resolution (GNN), Journey Prediction (TFT), Churn Prediction (XGBoost),
    LTV Prediction (ensemble), Anomaly Detection (IsoForest+AE), Campaign Attribution (Shapley)
- **Feature Engineering Pipeline** — batch (SageMaker Processing) and streaming (Kafka/Kinesis)
- **Feature Registry** — centralized schema, lineage, and versioning for all feature groups
- **Feature Store** — Redis (online, sub-ms) + S3 Parquet (offline, historical)
- **Model Serving API** — FastAPI with multi-model inference, caching, and batch prediction
- **Training Pipelines** — end-to-end orchestration with champion/challenger evaluation
- **Hyperparameter Optimization** — Optuna with pruning and multi-objective support
- **Model Export** — TF.js, ONNX, TF Lite, CoreML converters for edge deployment
- **Monitoring & Alerting** — drift detection (PSI, KS, Jensen-Shannon), latency tracking,
  CloudWatch/SNS integration, automatic rollback triggers
- **Data Preprocessing** — reproducible, serializable pipelines with imputation, encoding,
  scaling, outlier handling, and class balancing (SMOTE/ADASYN)
- **Data Validation** — schema enforcement, statistical checks, anomaly flagging
- **Comprehensive Test Suite** — unit tests, integration tests, synthetic data fixtures
- **Docker** — multi-stage build, docker-compose with Redis/MLflow/Prometheus
- **SageMaker Integration** — training jobs, endpoints, processing configs

### Architecture
- Common base: `AetherModel` ABC, `ModelMetadata` (Pydantic), `ModelRegistry` (MLflow)
- Deployment targets: `EDGE_TFJS`, `EDGE_TFLITE`, `EDGE_ONNX`, `SERVER_SAGEMAKER`, `SERVER_LAMBDA`, `SERVER_ECS`
- Feature store: dual-layer (Redis online, S3/Parquet offline) with TTL management
- Model stages: development → staging → production → archived
