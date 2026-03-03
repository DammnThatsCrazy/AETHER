"""SageMaker training job and endpoint configurations for Aether ML server models.

Defines instance types, storage, runtime limits, S3 paths, and framework
versions for launching training jobs on AWS SageMaker, as well as endpoint
configurations for real-time inference.

Usage::

    from training.configs.sagemaker import SAGEMAKER_CONFIGS, get_training_config

    cfg = get_training_config("churn_prediction")
    print(cfg.instance_type, cfg.s3_data_path)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------


class SageMakerTrainingConfig(BaseModel):
    """Configuration for an AWS SageMaker training job."""

    instance_type: str
    instance_count: int = 1
    volume_size_gb: int = 50
    max_runtime_seconds: int = 7200
    s3_data_path: str
    s3_output_path: str
    framework: str  # "pytorch", "sklearn", "xgboost"
    framework_version: str
    py_version: str = "py310"
    spot_instances: bool = False
    max_wait_seconds: int = 14400
    hyperparameters: dict[str, str] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)


class SageMakerEndpointConfig(BaseModel):
    """Configuration for an AWS SageMaker real-time inference endpoint."""

    instance_type: str
    instance_count: int = 1
    model_name: str
    endpoint_name: str
    auto_scaling_min: int = 1
    auto_scaling_max: int = 4
    target_invocations_per_instance: int = 100


# ---------------------------------------------------------------------------
# Per-model training configs (server models only -- edge models are trained
# locally and exported to TF.js / ONNX)
# ---------------------------------------------------------------------------

_S3_BUCKET = "aether-ml-data"
_S3_OUTPUT = "aether-ml-models"

SAGEMAKER_TRAINING_CONFIGS: dict[str, SageMakerTrainingConfig] = {
    # --- Edge models (lighter compute, trained on SageMaker for CI/CD) ---
    "intent_prediction": SageMakerTrainingConfig(
        instance_type="ml.m5.xlarge",
        instance_count=1,
        volume_size_gb=30,
        max_runtime_seconds=1800,
        s3_data_path=f"s3://{_S3_BUCKET}/features/session_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/intent_prediction/",
        framework="sklearn",
        framework_version="1.2-1",
        spot_instances=True,
        hyperparameters={
            "model": "intent_prediction",
            "C": "1.0",
            "max_iter": "1000",
            "export_tfjs": "true",
        },
        tags={"tier": "edge", "project": "aether"},
    ),
    "bot_detection": SageMakerTrainingConfig(
        instance_type="ml.m5.xlarge",
        instance_count=1,
        volume_size_gb=30,
        max_runtime_seconds=1800,
        s3_data_path=f"s3://{_S3_BUCKET}/features/behavioral_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/bot_detection/",
        framework="sklearn",
        framework_version="1.2-1",
        spot_instances=True,
        hyperparameters={
            "model": "bot_detection",
            "n_estimators": "100",
            "max_depth": "12",
            "export_onnx": "true",
        },
        tags={"tier": "edge", "project": "aether"},
    ),
    "session_scorer": SageMakerTrainingConfig(
        instance_type="ml.m5.large",
        instance_count=1,
        volume_size_gb=20,
        max_runtime_seconds=1200,
        s3_data_path=f"s3://{_S3_BUCKET}/features/session_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/session_scorer/",
        framework="sklearn",
        framework_version="1.2-1",
        spot_instances=True,
        hyperparameters={
            "model": "session_scorer",
            "C": "0.5",
        },
        tags={"tier": "edge", "project": "aether"},
    ),
    # --- Server models (heavier compute) ---
    "identity_resolution": SageMakerTrainingConfig(
        instance_type="ml.g4dn.xlarge",
        instance_count=1,
        volume_size_gb=50,
        max_runtime_seconds=3600,
        s3_data_path=f"s3://{_S3_BUCKET}/features/identity_pairs/",
        s3_output_path=f"s3://{_S3_OUTPUT}/identity_resolution/",
        framework="pytorch",
        framework_version="2.1.0",
        hyperparameters={
            "model": "identity_resolution",
            "hidden_dim_1": "64",
            "hidden_dim_2": "32",
            "epochs": "20",
            "lr": "0.001",
        },
        tags={"tier": "server", "project": "aether"},
    ),
    "journey_prediction": SageMakerTrainingConfig(
        instance_type="ml.g4dn.xlarge",
        instance_count=1,
        volume_size_gb=100,
        max_runtime_seconds=7200,
        s3_data_path=f"s3://{_S3_BUCKET}/features/journey_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/journey_prediction/",
        framework="pytorch",
        framework_version="2.1.0",
        hyperparameters={
            "model": "journey_prediction",
            "d_model": "64",
            "n_heads": "4",
            "n_layers": "2",
            "epochs": "30",
            "lr": "0.001",
        },
        tags={"tier": "server", "project": "aether"},
    ),
    "churn_prediction": SageMakerTrainingConfig(
        instance_type="ml.m5.2xlarge",
        instance_count=1,
        volume_size_gb=50,
        max_runtime_seconds=3600,
        s3_data_path=f"s3://{_S3_BUCKET}/features/identity_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/churn_prediction/",
        framework="xgboost",
        framework_version="1.7-1",
        hyperparameters={
            "model": "churn_prediction",
            "n_estimators": "200",
            "max_depth": "6",
            "learning_rate": "0.05",
        },
        tags={"tier": "server", "project": "aether"},
    ),
    "ltv_prediction": SageMakerTrainingConfig(
        instance_type="ml.m5.2xlarge",
        instance_count=1,
        volume_size_gb=50,
        max_runtime_seconds=3600,
        s3_data_path=f"s3://{_S3_BUCKET}/features/identity_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/ltv_prediction/",
        framework="xgboost",
        framework_version="1.7-1",
        hyperparameters={
            "model": "ltv_prediction",
            "n_estimators": "300",
            "max_depth": "6",
            "learning_rate": "0.05",
        },
        tags={"tier": "server", "project": "aether"},
    ),
    "anomaly_detection": SageMakerTrainingConfig(
        instance_type="ml.m5.xlarge",
        instance_count=1,
        volume_size_gb=30,
        max_runtime_seconds=1800,
        s3_data_path=f"s3://{_S3_BUCKET}/features/anomaly_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/anomaly_detection/",
        framework="sklearn",
        framework_version="1.2-1",
        spot_instances=True,
        hyperparameters={
            "model": "anomaly_detection",
            "n_estimators": "200",
            "contamination": "0.05",
        },
        tags={"tier": "server", "project": "aether"},
    ),
    "campaign_attribution": SageMakerTrainingConfig(
        instance_type="ml.m5.xlarge",
        instance_count=1,
        volume_size_gb=30,
        max_runtime_seconds=2400,
        s3_data_path=f"s3://{_S3_BUCKET}/features/attribution_features/",
        s3_output_path=f"s3://{_S3_OUTPUT}/campaign_attribution/",
        framework="sklearn",
        framework_version="1.2-1",
        spot_instances=True,
        hyperparameters={
            "model": "campaign_attribution",
            "attribution_model": "shapley",
            "n_shapley_samples": "1000",
        },
        tags={"tier": "server", "project": "aether"},
    ),
}


# ---------------------------------------------------------------------------
# Per-model endpoint configs
# ---------------------------------------------------------------------------

SAGEMAKER_ENDPOINT_CONFIGS: dict[str, SageMakerEndpointConfig] = {
    "identity_resolution": SageMakerEndpointConfig(
        instance_type="ml.m5.xlarge",
        instance_count=1,
        model_name="aether-identity-resolution",
        endpoint_name="aether-identity-resolution-prod",
        auto_scaling_min=1,
        auto_scaling_max=4,
        target_invocations_per_instance=200,
    ),
    "journey_prediction": SageMakerEndpointConfig(
        instance_type="ml.g4dn.xlarge",
        instance_count=1,
        model_name="aether-journey-prediction",
        endpoint_name="aether-journey-prediction-prod",
        auto_scaling_min=1,
        auto_scaling_max=3,
        target_invocations_per_instance=100,
    ),
    "churn_prediction": SageMakerEndpointConfig(
        instance_type="ml.m5.large",
        instance_count=1,
        model_name="aether-churn-prediction",
        endpoint_name="aether-churn-prediction-prod",
        auto_scaling_min=1,
        auto_scaling_max=4,
        target_invocations_per_instance=300,
    ),
    "ltv_prediction": SageMakerEndpointConfig(
        instance_type="ml.m5.large",
        instance_count=1,
        model_name="aether-ltv-prediction",
        endpoint_name="aether-ltv-prediction-prod",
        auto_scaling_min=1,
        auto_scaling_max=4,
        target_invocations_per_instance=300,
    ),
    "anomaly_detection": SageMakerEndpointConfig(
        instance_type="ml.m5.large",
        instance_count=1,
        model_name="aether-anomaly-detection",
        endpoint_name="aether-anomaly-detection-prod",
        auto_scaling_min=1,
        auto_scaling_max=2,
        target_invocations_per_instance=150,
    ),
    "campaign_attribution": SageMakerEndpointConfig(
        instance_type="ml.m5.large",
        instance_count=1,
        model_name="aether-campaign-attribution",
        endpoint_name="aether-campaign-attribution-prod",
        auto_scaling_min=1,
        auto_scaling_max=2,
        target_invocations_per_instance=100,
    ),
}


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def get_training_config(model_name: str) -> SageMakerTrainingConfig:
    """Get the SageMaker training job config for a model.

    Args:
        model_name: One of the 9 Aether model identifiers.

    Returns:
        The ``SageMakerTrainingConfig`` for the requested model.

    Raises:
        KeyError: If the model name is not found.
    """
    if model_name not in SAGEMAKER_TRAINING_CONFIGS:
        raise KeyError(
            f"No SageMaker training config for '{model_name}'. "
            f"Available: {sorted(SAGEMAKER_TRAINING_CONFIGS.keys())}"
        )
    return SAGEMAKER_TRAINING_CONFIGS[model_name]


def get_endpoint_config(model_name: str) -> SageMakerEndpointConfig:
    """Get the SageMaker endpoint config for a model.

    Args:
        model_name: One of the server-side Aether model identifiers.

    Returns:
        The ``SageMakerEndpointConfig`` for the requested model.

    Raises:
        KeyError: If the model name is not found.
    """
    if model_name not in SAGEMAKER_ENDPOINT_CONFIGS:
        raise KeyError(
            f"No SageMaker endpoint config for '{model_name}'. "
            f"Available: {sorted(SAGEMAKER_ENDPOINT_CONFIGS.keys())}"
        )
    return SAGEMAKER_ENDPOINT_CONFIGS[model_name]
