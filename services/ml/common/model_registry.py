"""
Aether ML — Canonical Model Registry

Single source of truth for all ML model identities, capabilities,
security tiers, artifact formats, and serving contracts.

No other file may define a divergent model list. All serving, training,
backend, docs generation, and tests must read from this registry.

Usage:
    from common.model_registry import (
        get_model, list_models, list_trainable_models,
        resolve_model_id, require_model, export_registry_for_docs,
    )
"""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("aether.ml.registry")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ImplementationType(str, Enum):
    TRAINABLE_ML = "trainable_ml"
    DETERMINISTIC_RULE_BASED = "deterministic_rule_based"
    COMPOSITE_SCORE = "composite_score"
    EXTERNAL_ENDPOINT = "external_endpoint"


class ModelTier(str, Enum):
    EDGE = "edge"
    SERVER = "server"
    SECURITY = "security"
    COMPOSITE = "composite"


class SensitivityTier(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    STANDARD = "standard"


class ModelStatus(str, Enum):
    LOCAL_STUB = "local_stub"
    TRAINABLE_SYNTHETIC = "trainable_synthetic"
    TRAINABLE_REAL_DATA = "trainable_real_data"
    STAGED = "staged"
    PROMOTED = "promoted"
    ACTIVE_DETERMINISTIC = "active_deterministic"
    DISABLED = "disabled"


class ArtifactFormat(str, Enum):
    PICKLE = "pickle"
    JOBLIB = "joblib"
    ONNX = "onnx"
    JSON = "json"
    NONE = "none"


class PromotionState(str, Enum):
    LOCAL = "local"
    TRAINED = "trained"
    CANDIDATE = "candidate"
    STAGED = "staged"
    PROMOTED = "promoted"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Registry entry
# ---------------------------------------------------------------------------


@dataclass
class ModelEntry:
    """Complete descriptor for one Aether ML model or scoring output."""

    model_id: str
    display_name: str
    category: str
    task_type: str
    algorithm: str
    implementation_type: ImplementationType
    tier: ModelTier
    sensitivity_tier: SensitivityTier
    current_status: ModelStatus
    training_supported: bool
    serving_supported: bool
    batch_supported: bool
    batch_requires_privileged: bool
    artifact_required: bool
    artifact_format: ArtifactFormat
    artifact_name: str
    feature_contract_id: str
    target_column: str
    training_entrypoint: str
    serving_endpoint: str
    # alias -> canonical resolution
    backend_model_aliases: list[str] = field(default_factory=list)
    deprecated_aliases: list[str] = field(default_factory=list)
    minimum_metrics: dict[str, float] = field(default_factory=dict)
    promotion_requirements: list[str] = field(default_factory=list)
    owner: str = "ml-platform"
    docs_slug: str = ""
    kyber_visible: bool = True
    tenant_visible: bool = True
    fail_closed_required: bool = False

    # ---- Model-governance metadata (additive, backward-compatible) --------
    # Purpose/consent scoping. Training and serving are distinct consent gates
    # and carry separate purpose declarations:
    #   - allowed_training_purposes: canonical consent-registry purposes this
    #     model's TRAINING data may legitimately be drawn from (enforced by the
    #     backend TrainingDataGate when admitting records into a training set).
    #   - required_inference_purposes: canonical consent-registry purposes a
    #     subject must have granted for this model to SERVE a prediction about
    #     them (enforced by the backend InferencePolicyGate at inference time).
    # Both lists must be non-empty and reference only keys defined in
    # packages/shared/contracts/consent-registry.json — validated by
    # scripts/validate_model_consent_purposes.py. A model with no declared
    # inference purposes is denied serving (fail closed).
    allowed_training_purposes: list[str] = field(default_factory=list)
    required_inference_purposes: list[str] = field(default_factory=list)
    forbidden_feature_tags: list[str] = field(default_factory=list)
    # Governance gates that must be satisfied before promotion.
    requires_privacy_review: bool = False
    requires_bias_audit: bool = False
    requires_model_card: bool = True
    requires_dataset_card: bool = True
    requires_training_manifest: bool = True
    requires_human_review: bool = False
    requires_dsr_invalidation: bool = False
    # Whether this model may ever be promoted to production.
    production_promotion_allowed: bool = True
    # Free-text reason a sensitive model omits a governance gate (audited).
    governance_notes: str = ""


# ---------------------------------------------------------------------------
# Canonical registry — ALL 11 intelligence outputs
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ModelEntry] = {

    # ── EDGE TIER — Trainable ML ──────────────────────────────────────── #

    "intent_prediction": ModelEntry(
        model_id="intent_prediction",
        display_name="Intent Prediction",
        category="behavioral_analytics",
        task_type="multiclass_classification",
        algorithm="LogisticRegression",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.EDGE,
        sensitivity_tier=SensitivityTier.HIGH,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=False,
        batch_requires_privileged=False,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="intent_prediction_v1",
        target_column="next_action",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/intent",
        backend_model_aliases=[],
        deprecated_aliases=[],
        minimum_metrics={"test_accuracy": 0.6, "test_f1": 0.55},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "feature_schema_hash",
            "privacy_review",
        ],
        docs_slug="intent-prediction",
        fail_closed_required=False,
        allowed_training_purposes=["analytics", "personalization"],
        required_inference_purposes=["analytics", "personalization"],
        requires_privacy_review=True,
    ),

    "bot_detection": ModelEntry(
        model_id="bot_detection",
        display_name="Bot Detection",
        category="security_analytics",
        task_type="binary_classification",
        algorithm="RandomForestClassifier",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.EDGE,
        sensitivity_tier=SensitivityTier.HIGH,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=False,
        batch_requires_privileged=False,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="bot_detection_v1",
        target_column="is_bot",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/bot",
        minimum_metrics={"test_accuracy": 0.85, "test_auc": 0.90},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "feature_schema_hash",
            "privacy_review",
            "bias_audit",
        ],
        docs_slug="bot-detection",
        fail_closed_required=True,
        allowed_training_purposes=["fraud_prevention"],
        required_inference_purposes=["fraud_prevention"],
        requires_privacy_review=True,
        requires_bias_audit=True,
    ),

    "session_scorer": ModelEntry(
        model_id="session_scorer",
        display_name="Session Engagement Scorer",
        category="behavioral_analytics",
        task_type="regression",
        algorithm="GradientBoostingRegressor",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.EDGE,
        sensitivity_tier=SensitivityTier.STANDARD,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=False,
        batch_requires_privileged=False,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="session_scorer_v1",
        target_column="high_engagement",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/session-score",
        minimum_metrics={"test_mae": 30.0, "test_r2": 0.3},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
        ],
        docs_slug="session-scorer",
        fail_closed_required=False,
        allowed_training_purposes=["analytics"],
        required_inference_purposes=["analytics"],
    ),

    # ── SERVER TIER — Trainable ML ────────────────────────────────────── #

    "identity_resolution": ModelEntry(
        model_id="identity_resolution",
        display_name="Identity Resolution",
        category="identity_intelligence",
        task_type="binary_classification",
        algorithm="GradientBoostingClassifier",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.SERVER,
        sensitivity_tier=SensitivityTier.STANDARD,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=True,
        batch_requires_privileged=True,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="identity_resolution_v1",
        target_column="same_identity",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/identity",
        # Deprecated API aliases — resolve to this canonical ID
        deprecated_aliases=["identity_gnn"],
        minimum_metrics={"test_accuracy": 0.80, "test_auc": 0.85},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "feature_schema_hash",
            "privacy_review",
            "bias_audit",
            "human_review",
        ],
        docs_slug="identity-resolution",
        fail_closed_required=False,
        allowed_training_purposes=["personalization", "fraud_prevention"],
        required_inference_purposes=["personalization", "fraud_prevention"],
        forbidden_feature_tags=["raw_pii"],
        requires_privacy_review=True,
        requires_bias_audit=True,
        requires_human_review=True,
        requires_dsr_invalidation=True,
    ),

    "journey_prediction": ModelEntry(
        model_id="journey_prediction",
        display_name="Journey Prediction",
        category="behavioral_analytics",
        task_type="binary_classification",
        algorithm="GradientBoostingClassifier",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.SERVER,
        sensitivity_tier=SensitivityTier.STANDARD,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=True,
        batch_requires_privileged=True,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="journey_prediction_v1",
        target_column="conversion_within_7d",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/journey",
        # Deprecated API aliases — resolve to this canonical ID
        deprecated_aliases=["journey_tft"],
        minimum_metrics={"test_accuracy": 0.65, "test_auc": 0.70},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "feature_schema_hash",
            "privacy_review",
        ],
        docs_slug="journey-prediction",
        fail_closed_required=False,
        allowed_training_purposes=["analytics"],
        required_inference_purposes=["analytics"],
        requires_privacy_review=True,
    ),

    "churn_prediction": ModelEntry(
        model_id="churn_prediction",
        display_name="Churn Prediction",
        category="retention_analytics",
        task_type="binary_classification",
        algorithm="XGBoostClassifier",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.SERVER,
        sensitivity_tier=SensitivityTier.CRITICAL,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=True,
        batch_requires_privileged=True,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="churn_prediction_v1",
        target_column="churned_30d",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/churn",
        minimum_metrics={"test_accuracy": 0.70, "test_auc": 0.75},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "feature_schema_hash",
            "privacy_review",
        ],
        docs_slug="churn-prediction",
        fail_closed_required=True,
        allowed_training_purposes=["analytics"],
        required_inference_purposes=["analytics"],
        requires_privacy_review=True,
        requires_dsr_invalidation=True,
    ),

    "ltv_prediction": ModelEntry(
        model_id="ltv_prediction",
        display_name="LTV Prediction",
        category="revenue_analytics",
        task_type="regression",
        algorithm="XGBoostRegressor",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.SERVER,
        sensitivity_tier=SensitivityTier.CRITICAL,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=True,
        batch_requires_privileged=True,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="ltv_prediction_v1",
        target_column="ltv_90d",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/ltv",
        minimum_metrics={"test_mae": 50.0, "test_r2": 0.4},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "feature_schema_hash",
            "privacy_review",
        ],
        docs_slug="ltv-prediction",
        fail_closed_required=True,
        allowed_training_purposes=["commerce"],
        required_inference_purposes=["commerce"],
        requires_privacy_review=True,
        requires_dsr_invalidation=True,
    ),

    "anomaly_detection": ModelEntry(
        model_id="anomaly_detection",
        display_name="Anomaly Detection",
        category="infrastructure_analytics",
        task_type="unsupervised_anomaly",
        algorithm="IsolationForest",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.SERVER,
        sensitivity_tier=SensitivityTier.CRITICAL,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=True,
        batch_requires_privileged=True,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="anomaly_detection_v1",
        target_column="",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/anomaly",
        minimum_metrics={"test_anomaly_rate": 0.1},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "privacy_review",
            "bias_audit",
        ],
        docs_slug="anomaly-detection",
        fail_closed_required=True,
        allowed_training_purposes=["analytics", "fraud_prevention"],
        required_inference_purposes=["analytics", "fraud_prevention"],
        requires_privacy_review=True,
        requires_bias_audit=True,
    ),

    "campaign_attribution": ModelEntry(
        model_id="campaign_attribution",
        display_name="Campaign Attribution",
        category="marketing_analytics",
        task_type="attribution",
        # Uses GradientBoostingClassifier trained on touchpoint features;
        # Shapley credit values are derived post-prediction at serve time.
        algorithm="GradientBoostingClassifier",
        implementation_type=ImplementationType.TRAINABLE_ML,
        tier=ModelTier.SERVER,
        sensitivity_tier=SensitivityTier.HIGH,
        current_status=ModelStatus.TRAINABLE_SYNTHETIC,
        training_supported=True,
        serving_supported=True,
        batch_supported=True,
        batch_requires_privileged=True,
        artifact_required=True,
        artifact_format=ArtifactFormat.JOBLIB,
        artifact_name="model.joblib",
        feature_contract_id="campaign_attribution_v1",
        target_column="converted",
        training_entrypoint="training.pipelines.train",
        serving_endpoint="/v1/predict/attribution",
        minimum_metrics={"test_accuracy": 0.60},
        promotion_requirements=[
            "real_data_only",
            "threshold_pass",
            "artifact_metadata",
            "privacy_review",
        ],
        docs_slug="campaign-attribution",
        fail_closed_required=False,
        allowed_training_purposes=["marketing"],
        required_inference_purposes=["marketing"],
        requires_privacy_review=True,
    ),

    # ── SECURITY / DETERMINISTIC outputs ─────────────────────────────── #

    "bytecode_risk": ModelEntry(
        model_id="bytecode_risk",
        display_name="Bytecode Risk Scoring",
        category="security_analytics",
        task_type="deterministic_scoring",
        algorithm="RuleEngine",
        implementation_type=ImplementationType.DETERMINISTIC_RULE_BASED,
        tier=ModelTier.SECURITY,
        sensitivity_tier=SensitivityTier.CRITICAL,
        current_status=ModelStatus.ACTIVE_DETERMINISTIC,
        training_supported=False,
        serving_supported=True,
        batch_supported=False,
        batch_requires_privileged=False,
        artifact_required=False,
        artifact_format=ArtifactFormat.NONE,
        artifact_name="",
        feature_contract_id="bytecode_risk_v1",
        target_column="",
        training_entrypoint="",
        serving_endpoint="/v1/score/bytecode",
        minimum_metrics={},
        promotion_requirements=[],
        docs_slug="bytecode-risk",
        fail_closed_required=True,
        allowed_training_purposes=["web3"],
        required_inference_purposes=["web3"],
        requires_model_card=False,
        requires_dataset_card=False,
        requires_training_manifest=False,
        governance_notes=(
            "Deterministic rule-based scorer: no trained artifact, model card, "
            "or dataset card applies. Operates on submitted bytecode only; no "
            "personal data is used, so no privacy review is required."
        ),
    ),

    "trust_score": ModelEntry(
        model_id="trust_score",
        display_name="Trust Score",
        category="composite_intelligence",
        task_type="composite_scoring",
        algorithm="WeightedComposite",
        implementation_type=ImplementationType.COMPOSITE_SCORE,
        tier=ModelTier.COMPOSITE,
        sensitivity_tier=SensitivityTier.CRITICAL,
        current_status=ModelStatus.ACTIVE_DETERMINISTIC,
        training_supported=False,
        serving_supported=True,
        batch_supported=False,
        batch_requires_privileged=False,
        artifact_required=False,
        artifact_format=ArtifactFormat.NONE,
        artifact_name="",
        feature_contract_id="trust_score_v1",
        target_column="",
        training_entrypoint="",
        serving_endpoint="/v1/score/trust",
        minimum_metrics={},
        promotion_requirements=[],
        docs_slug="trust-score",
        kyber_visible=True,
        tenant_visible=True,
        fail_closed_required=True,
        allowed_training_purposes=["analytics", "fraud_prevention"],
        required_inference_purposes=["analytics", "fraud_prevention"],
        requires_model_card=False,
        requires_dataset_card=False,
        requires_training_manifest=False,
        governance_notes=(
            "Composite weighted scorer over already-governed upstream model "
            "outputs and deterministic signals: no independently trained "
            "artifact, model card, or dataset card applies. Inherits the "
            "privacy posture of its upstream inputs."
        ),
    ),
}

# ---------------------------------------------------------------------------
# All aliases — maps alias → canonical model_id
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {}

for _entry in _REGISTRY.values():
    for _alias in _entry.deprecated_aliases:
        _ALIAS_MAP[_alias] = _entry.model_id
    for _alias in _entry.backend_model_aliases:
        _ALIAS_MAP[_alias] = _entry.model_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_models() -> list[ModelEntry]:
    """Return all registered model entries."""
    return list(_REGISTRY.values())


def list_trainable_models() -> list[ModelEntry]:
    """Return only models with training_supported=True."""
    return [m for m in _REGISTRY.values() if m.training_supported]


def list_serving_models() -> list[ModelEntry]:
    """Return only models with serving_supported=True."""
    return [m for m in _REGISTRY.values() if m.serving_supported]


def get_model(model_id: str) -> Optional[ModelEntry]:
    """Return a model entry by canonical ID, or None if not found."""
    return _REGISTRY.get(model_id)


def resolve_model_id(name_or_alias: str) -> Optional[str]:
    """
    Resolve any name or alias to the canonical model_id.

    Returns the canonical model_id, or None if unrecognised.
    Emits a deprecation warning when a deprecated alias is used.
    """
    if name_or_alias in _REGISTRY:
        return name_or_alias

    canonical = _ALIAS_MAP.get(name_or_alias)
    if canonical is not None:
        entry = _REGISTRY[canonical]
        if name_or_alias in entry.deprecated_aliases:
            warnings.warn(
                f"Model alias '{name_or_alias}' is deprecated. "
                f"Use canonical model_id '{canonical}' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            logger.warning(
                "Deprecated model alias used: '%s' -> '%s'",
                name_or_alias,
                canonical,
            )
        return canonical

    return None


def require_model(model_id: str) -> ModelEntry:
    """
    Return a model entry by canonical ID, raising ValueError if not found.

    Use this in serving/training code where an unknown model_id is a hard error.
    """
    entry = _REGISTRY.get(model_id)
    if entry is None:
        canonical = resolve_model_id(model_id)
        if canonical:
            return _REGISTRY[canonical]
        known = sorted(_REGISTRY.keys())
        aliases = sorted(_ALIAS_MAP.keys())
        raise ValueError(
            f"Unknown model '{model_id}'. "
            f"Known model IDs: {known}. "
            f"Known aliases (deprecated): {aliases}."
        )
    return entry


def is_batch_allowed(model_id: str, caller_context: dict[str, Any]) -> bool:
    """
    Return True if batch prediction is allowed for this model and caller.

    Args:
        model_id: Canonical model ID.
        caller_context: Dict with keys like 'is_privileged', 'role', 'env'.
    """
    canonical = resolve_model_id(model_id)
    if not canonical:
        return False
    entry = _REGISTRY[canonical]

    if not entry.batch_supported:
        return False

    if entry.batch_requires_privileged:
        return bool(caller_context.get("is_privileged", False))

    return True


def model_requires_artifact(model_id: str) -> bool:
    """Return True if this model requires a saved artifact to serve predictions."""
    canonical = resolve_model_id(model_id)
    if not canonical:
        return True
    return _REGISTRY[canonical].artifact_required


def model_is_stub_allowed(env: str, model_id: str) -> bool:
    """
    Return True if stub (untrained) models are allowed in this environment.

    Stubs are ONLY allowed in local/development environments. Never in staging
    or production.
    """
    env_lower = env.lower()
    if env_lower in ("production", "staging", "prod", "stage"):
        return False
    canonical = resolve_model_id(model_id)
    if not canonical:
        return False
    entry = _REGISTRY.get(canonical)
    return entry is not None and entry.implementation_type == ImplementationType.TRAINABLE_ML


def export_registry_for_docs() -> list[dict[str, Any]]:
    """
    Export the registry as a list of dicts suitable for doc generation.
    """
    rows = []
    for entry in _REGISTRY.values():
        rows.append({
            "model_id": entry.model_id,
            "display_name": entry.display_name,
            "category": entry.category,
            "implementation_type": entry.implementation_type.value,
            "tier": entry.tier.value,
            "sensitivity_tier": entry.sensitivity_tier.value,
            "training_supported": entry.training_supported,
            "serving_supported": entry.serving_supported,
            "batch_supported": entry.batch_supported,
            "batch_requires_privileged": entry.batch_requires_privileged,
            "artifact_required": entry.artifact_required,
            "artifact_format": entry.artifact_format.value,
            "serving_endpoint": entry.serving_endpoint,
            "deprecated_aliases": entry.deprecated_aliases,
            "current_status": entry.current_status.value,
            "docs_slug": entry.docs_slug,
            "fail_closed_required": entry.fail_closed_required,
        })
    return rows


def export_registry_for_backend() -> dict[str, Any]:
    """
    Export model names and aliases for backend gateway use.

    Returns:
        {
            "canonical_ids": [...],
            "deprecated_aliases": {alias: canonical},
            "serving_endpoints": {canonical: endpoint},
            "batch_policy": {canonical: requires_privileged},
        }
    """
    canonical_ids = list(_REGISTRY.keys())
    deprecated_aliases: dict[str, str] = {}
    serving_endpoints: dict[str, str] = {}
    batch_policy: dict[str, bool] = {}

    for entry in _REGISTRY.values():
        serving_endpoints[entry.model_id] = entry.serving_endpoint
        batch_policy[entry.model_id] = entry.batch_requires_privileged
        for alias in entry.deprecated_aliases:
            deprecated_aliases[alias] = entry.model_id

    return {
        "canonical_ids": canonical_ids,
        "deprecated_aliases": deprecated_aliases,
        "serving_endpoints": serving_endpoints,
        "batch_policy": batch_policy,
    }


def export_registry_for_serving() -> dict[str, Any]:
    """
    Export model info for the ML serving API.

    Returns names, types, sensitivity tiers, and whether stubs are safe.
    """
    return {
        entry.model_id: {
            "display_name": entry.display_name,
            "tier": entry.tier.value,
            "sensitivity_tier": entry.sensitivity_tier.value,
            "artifact_required": entry.artifact_required,
            "artifact_name": entry.artifact_name,
            "artifact_format": entry.artifact_format.value,
            "fail_closed_required": entry.fail_closed_required,
            "deprecated_aliases": entry.deprecated_aliases,
        }
        for entry in _REGISTRY.values()
        if entry.serving_supported
    }
