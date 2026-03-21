"""Per-model training configurations for all 9 Aether ML models.

Each model has a ``TrainingConfig`` that specifies batch size, epochs, learning
rate, early stopping, data split ratios, default hyper-parameters, feature
columns, and target column.

Usage::

    from training.configs.model_configs import get_config, MODEL_CONFIGS

    cfg = get_config("churn_prediction")
    print(cfg.learning_rate, cfg.features)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Training config schema (Pydantic)
# ---------------------------------------------------------------------------


class TrainingConfig(BaseModel):
    """Configuration for training a single Aether ML model."""

    model_name: str
    batch_size: int = 1024
    epochs: int = 100
    learning_rate: float = 0.001
    early_stopping_patience: int = 10
    validation_split: float = 0.2
    test_split: float = 0.1
    random_state: int = 42
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    target_column: str = "target"


# ---------------------------------------------------------------------------
# Edge model configs
# ---------------------------------------------------------------------------

INTENT_PREDICTION_CONFIG = TrainingConfig(
    model_name="intent_prediction",
    batch_size=512,
    epochs=50,
    learning_rate=0.001,
    early_stopping_patience=8,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "C": 1.0,
        "max_iter": 1000,
        "solver": "lbfgs",

    },
    features=[
        "mouse_velocity_mean", "mouse_velocity_std",
        "scroll_depth_max", "scroll_velocity_mean",
        "hover_duration_mean", "time_between_actions_mean",
        "time_between_actions_std", "click_to_scroll_ratio",
        "active_ratio", "page_depth", "session_duration_s",
        "click_count", "scroll_count", "keypress_count",
    ],
    target_column="next_action",
)

BOT_DETECTION_CONFIG = TrainingConfig(
    model_name="bot_detection",
    batch_size=1024,
    epochs=1,  # Tree ensemble -- single fit
    learning_rate=0.0,  # Not applicable for RF
    early_stopping_patience=0,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "n_estimators": 100,
        "max_depth": 12,
        "min_samples_leaf": 5,
        "class_weight": "balanced",
        "criterion": "gini",
    },
    features=[
        "avg_time_between_actions", "time_variance",
        "click_to_scroll_ratio", "mouse_velocity_mean", "mouse_velocity_std",
        "mouse_entropy", "navigation_entropy", "interaction_diversity",
        "has_natural_pauses", "has_erratic_movement", "has_perfect_timing",
        "keypress_count", "unique_action_types", "action_rate",
    ],
    target_column="is_bot",
)

SESSION_SCORER_CONFIG = TrainingConfig(
    model_name="session_scorer",
    batch_size=512,
    epochs=50,
    learning_rate=0.001,
    early_stopping_patience=8,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "C": 0.5,
        "max_iter": 500,
        "penalty": "l2",
    },
    features=[
        "page_count", "event_count", "session_duration_s",
        "max_scroll_depth", "form_interaction_count",
        "is_return_visit", "referral_source_score",
        "click_count", "active_ratio",
    ],
    target_column="high_engagement",
)


# ---------------------------------------------------------------------------
# Server model configs
# ---------------------------------------------------------------------------

IDENTITY_RESOLUTION_CONFIG = TrainingConfig(
    model_name="identity_resolution",
    batch_size=256,
    epochs=20,
    learning_rate=0.001,
    early_stopping_patience=5,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "hidden_dim_1": 64,
        "hidden_dim_2": 32,
        "dropout_1": 0.3,
        "dropout_2": 0.2,
    },
    features=[
        "device_fingerprint_sim", "behavioral_sim", "temporal_overlap",
        "shared_ip_count", "session_sequence_score", "wallet_link_score",
        "geo_distance", "browser_match", "os_match",
    ],
    target_column="same_identity",
)

JOURNEY_PREDICTION_CONFIG = TrainingConfig(
    model_name="journey_prediction",
    batch_size=128,
    epochs=30,
    learning_rate=0.001,
    early_stopping_patience=7,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "d_model": 64,
        "n_heads": 4,
        "n_layers": 2,
        "dropout": 0.1,
    },
    features=[
        "page_sequence", "time_deltas", "device_type",
        "referrer_type", "session_number", "day_of_week", "hour_of_day",
    ],
    target_column="conversion_within_7d",
)

CHURN_PREDICTION_CONFIG = TrainingConfig(
    model_name="churn_prediction",
    batch_size=1024,
    epochs=1,  # XGBoost uses n_estimators
    learning_rate=0.05,
    early_stopping_patience=10,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "n_estimators": 200,
        "max_depth": 6,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 1,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
        "eval_metric": "auc",
    },
    features=[
        "days_since_last_visit", "visit_frequency_trend", "feature_usage_breadth",
        "session_duration_trend", "support_ticket_count", "billing_status",
        "engagement_percentile", "total_sessions", "avg_session_duration",
        "conversion_rate", "days_since_first_visit",
    ],
    target_column="churned_30d",
)

LTV_PREDICTION_CONFIG = TrainingConfig(
    model_name="ltv_prediction",
    batch_size=1024,
    epochs=1,  # XGBoost uses n_estimators
    learning_rate=0.05,
    early_stopping_patience=10,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "n_estimators": 300,
        "max_depth": 6,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
    },
    features=[
        "purchase_frequency", "recency_days", "monetary_mean", "monetary_total",
        "avg_session_duration", "total_sessions", "conversion_rate",
        "acquisition_channel_score", "engagement_percentile",
        "web3_tx_count", "web3_total_value",
    ],
    target_column="ltv_90d",
)

ANOMALY_DETECTION_CONFIG = TrainingConfig(
    model_name="anomaly_detection",
    batch_size=1024,
    epochs=1,  # Isolation Forest -- single fit
    learning_rate=0.0,
    early_stopping_patience=0,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "n_estimators": 200,
        "contamination": 0.05,
        "max_samples": "auto",
    },
    features=[
        "traffic_volume", "conversion_rate", "avg_session_duration",
        "bounce_rate", "error_rate", "api_latency_p99",
        "bot_traffic_ratio", "unique_visitors", "revenue",
    ],
    target_column="",  # Unsupervised
)

CAMPAIGN_ATTRIBUTION_CONFIG = TrainingConfig(
    model_name="campaign_attribution",
    batch_size=512,
    epochs=50,
    learning_rate=0.001,
    early_stopping_patience=8,
    validation_split=0.2,
    test_split=0.1,
    hyperparams={
        "attribution_model": "shapley",
        "decay_rate": 0.7,
        "lookback_window_days": 30,
        "position_weight": 0.4,
    },
    features=[
        "touchpoint_sequence", "channel_ids", "time_deltas",
        "conversion_value", "device_types",
    ],
    target_column="converted",
)


# ---------------------------------------------------------------------------
# Aggregated registry
# ---------------------------------------------------------------------------

MODEL_CONFIGS: dict[str, TrainingConfig] = {
    "intent_prediction": INTENT_PREDICTION_CONFIG,
    "bot_detection": BOT_DETECTION_CONFIG,
    "session_scorer": SESSION_SCORER_CONFIG,
    "identity_resolution": IDENTITY_RESOLUTION_CONFIG,
    "journey_prediction": JOURNEY_PREDICTION_CONFIG,
    "churn_prediction": CHURN_PREDICTION_CONFIG,
    "ltv_prediction": LTV_PREDICTION_CONFIG,
    "anomaly_detection": ANOMALY_DETECTION_CONFIG,
    "campaign_attribution": CAMPAIGN_ATTRIBUTION_CONFIG,
}


def get_config(model_name: str) -> TrainingConfig:
    """Retrieve the training configuration for a given model.

    Args:
        model_name: One of the 9 Aether model identifiers.

    Returns:
        The corresponding ``TrainingConfig``.

    Raises:
        KeyError: If the model name is not registered.
    """
    if model_name not in MODEL_CONFIGS:
        raise KeyError(
            f"Unknown model '{model_name}'. "
            f"Available: {sorted(MODEL_CONFIGS.keys())}"
        )
    return MODEL_CONFIGS[model_name]
