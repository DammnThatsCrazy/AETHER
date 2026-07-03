"""
Aether ML — Feature Contracts

Defines the exact input schema for every trainable ML model.
Used by training, serving, and backend to validate, normalize, and
explain features before inference.

Rules:
- Missing required features raise FeatureValidationError.
- Type mismatches raise FeatureValidationError.
- Aliases are silently normalised to canonical feature names.
- Defaults are applied for optional features if declared.

Usage:
    from common.feature_contracts import (
        get_feature_contract, validate_features,
        normalize_features, generate_example_features,
    )

    contract = get_feature_contract("churn_prediction")
    validate_features("churn_prediction", my_features)
    clean = normalize_features("churn_prediction", my_features)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import numpy as np
    _HAS_NUMPY = True
except ModuleNotFoundError:
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

logger = logging.getLogger("aether.ml.feature_contracts")


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class FeatureValidationError(ValueError):
    """Raised when feature input fails schema validation."""

    def __init__(self, model_id: str, message: str, missing: list[str] | None = None,
                 type_errors: list[str] | None = None):
        self.model_id = model_id
        self.missing = missing or []
        self.type_errors = type_errors or []
        super().__init__(f"[{model_id}] Feature validation failed: {message}")


# ---------------------------------------------------------------------------
# Feature descriptor
# ---------------------------------------------------------------------------


@dataclass
class FeatureSpec:
    """Specification for a single feature."""

    name: str
    dtype: str  # "float", "int", "bool", "str"
    required: bool = True
    default: Optional[Any] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[list[Any]] = None
    nullable: bool = False
    aliases: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feature contract
# ---------------------------------------------------------------------------


@dataclass
class FeatureContract:
    """Complete input schema for one model."""

    contract_id: str
    model_id: str
    schema_version: str
    features: list[FeatureSpec]
    source_feature_groups: list[str] = field(default_factory=list)
    online_key_patterns: list[str] = field(default_factory=list)
    freshness_sla_seconds: int = 3600
    owner: str = "ml-platform"

    # Derived at init time
    _required: list[str] = field(default_factory=list, init=False, repr=False)
    _optional: list[str] = field(default_factory=list, init=False, repr=False)
    _alias_map: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _spec_map: dict[str, FeatureSpec] = field(default_factory=dict, init=False, repr=False)
    _schema_hash: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        for spec in self.features:
            self._spec_map[spec.name] = spec
            if spec.required:
                self._required.append(spec.name)
            else:
                self._optional.append(spec.name)
            for alias in spec.aliases:
                self._alias_map[alias] = spec.name

        self._schema_hash = self._compute_schema_hash()

    def _compute_schema_hash(self) -> str:
        # Hash covers all behaviorally significant contract fields so that
        # any change that would cause training-serving skew rotates the hash.
        schema_repr = {
            "contract_id": self.contract_id,
            "schema_version": self.schema_version,
            "freshness_sla_seconds": self.freshness_sla_seconds,
            "features": sorted([
                {
                    "name": f.name,
                    "dtype": f.dtype,
                    "required": f.required,
                    "default": f.default,
                    "nullable": f.nullable,
                    "min_value": f.min_value,
                    "max_value": f.max_value,
                    "allowed_values": sorted(f.allowed_values) if f.allowed_values else None,
                    "aliases": sorted(f.aliases) if f.aliases else [],
                }
                for f in self.features
            ], key=lambda x: x["name"]),
        }
        return hashlib.sha256(
            json.dumps(schema_repr, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    @property
    def schema_hash(self) -> str:
        return self._schema_hash

    @property
    def required_features(self) -> list[str]:
        return self._required

    @property
    def optional_features(self) -> list[str]:
        return self._optional


# ---------------------------------------------------------------------------
# Contract definitions
# ---------------------------------------------------------------------------

_CONTRACTS: dict[str, FeatureContract] = {}


def _register(contract: FeatureContract) -> FeatureContract:
    _CONTRACTS[contract.model_id] = contract
    return contract


_register(FeatureContract(
    contract_id="intent_prediction_v1",
    model_id="intent_prediction",
    schema_version="1.0",
    source_feature_groups=["session_features", "behavioral_features"],
    freshness_sla_seconds=60,
    features=[
        FeatureSpec("mouse_velocity_mean", "float"),
        FeatureSpec("mouse_velocity_std", "float"),
        FeatureSpec("scroll_depth_max", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("scroll_velocity_mean", "float"),
        FeatureSpec("hover_duration_mean", "float", min_value=0.0),
        FeatureSpec("time_between_actions_mean", "float", min_value=0.0),
        FeatureSpec("time_between_actions_std", "float", min_value=0.0),
        FeatureSpec("click_to_scroll_ratio", "float", min_value=0.0),
        FeatureSpec("active_ratio", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("page_depth", "int", min_value=0),
        FeatureSpec("session_duration_s", "float", min_value=0.0,
                    aliases=["session_duration"]),
        FeatureSpec("click_count", "int", min_value=0),
        FeatureSpec("scroll_count", "int", min_value=0),
        FeatureSpec("keypress_count", "int", min_value=0),
    ],
))

_register(FeatureContract(
    contract_id="bot_detection_v1",
    model_id="bot_detection",
    schema_version="1.0",
    source_feature_groups=["behavioral_features"],
    freshness_sla_seconds=30,
    features=[
        # Aliases bridge pipeline output names → canonical contract names
        FeatureSpec("avg_time_between_actions", "float", min_value=0.0,
                    aliases=["click_interval_mean"]),
        FeatureSpec("time_variance", "float", min_value=0.0,
                    aliases=["click_interval_std"]),
        FeatureSpec("click_to_scroll_ratio", "float", min_value=0.0),
        FeatureSpec("mouse_velocity_mean", "float",
                    aliases=["mouse_speed_mean"]),
        FeatureSpec("mouse_velocity_std", "float",
                    aliases=["mouse_speed_std"]),
        FeatureSpec("mouse_entropy", "float", min_value=0.0),
        FeatureSpec("navigation_entropy", "float", min_value=0.0,
                    aliases=["scroll_pattern_entropy"]),
        FeatureSpec("interaction_diversity", "float", min_value=0.0, max_value=1.0,
                    aliases=["action_type_entropy"]),
        FeatureSpec("has_natural_pauses", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("has_erratic_movement", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("has_perfect_timing", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("keypress_count", "int", min_value=0),
        FeatureSpec("unique_action_types", "int", min_value=0),
        FeatureSpec("action_rate", "float", min_value=0.0,
                    aliases=["js_execution_time"]),
    ],
))

_register(FeatureContract(
    contract_id="session_scorer_v1",
    model_id="session_scorer",
    schema_version="1.0",
    source_feature_groups=["session_features"],
    freshness_sla_seconds=60,
    features=[
        FeatureSpec("page_count", "int", min_value=0,
                    aliases=["pages_viewed"]),
        FeatureSpec("event_count", "int", min_value=0),
        FeatureSpec("session_duration_s", "float", min_value=0.0,
                    aliases=["session_duration"]),
        FeatureSpec("max_scroll_depth", "float", min_value=0.0, max_value=1.0,
                    aliases=["scroll_depth"]),
        FeatureSpec("form_interaction_count", "int", min_value=0,
                    required=False, default=0),
        FeatureSpec("is_return_visit", "float", min_value=0.0, max_value=1.0,
                    required=False, default=0.0),
        FeatureSpec("referral_source_score", "float", min_value=0.0,
                    required=False, default=0.5),
        FeatureSpec("click_count", "int", min_value=0),
        FeatureSpec("active_ratio", "float", min_value=0.0, max_value=1.0),
    ],
))

_register(FeatureContract(
    contract_id="identity_resolution_v1",
    model_id="identity_resolution",
    schema_version="1.0",
    source_feature_groups=["identity_features"],
    freshness_sla_seconds=3600,
    features=[
        FeatureSpec("device_fingerprint_sim", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("behavioral_sim", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("temporal_overlap", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("shared_ip_count", "int", min_value=0),
        FeatureSpec("session_sequence_score", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("wallet_link_score", "float", min_value=0.0, max_value=1.0,
                    required=False, default=0.0),
        FeatureSpec("geo_distance", "float", min_value=0.0),
        FeatureSpec("browser_match", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("os_match", "float", min_value=0.0, max_value=1.0),
    ],
))

_register(FeatureContract(
    contract_id="journey_prediction_v1",
    model_id="journey_prediction",
    schema_version="1.0",
    source_feature_groups=["journey_features"],
    freshness_sla_seconds=1800,
    features=[
        FeatureSpec("page_sequence_len", "int", min_value=0,
                    aliases=["page_sequence"]),
        FeatureSpec("avg_time_delta", "float", min_value=0.0,
                    aliases=["time_deltas"]),
        FeatureSpec("device_type_encoded", "float",
                    aliases=["device_type"]),
        FeatureSpec("referrer_type_encoded", "float",
                    required=False, default=0.0,
                    aliases=["referrer_type"]),
        FeatureSpec("session_number", "int", min_value=1),
        FeatureSpec("day_of_week", "int", min_value=0, max_value=6),
        FeatureSpec("hour_of_day", "int", min_value=0, max_value=23),
    ],
))

_register(FeatureContract(
    contract_id="churn_prediction_v1",
    model_id="churn_prediction",
    schema_version="1.0",
    source_feature_groups=["identity_features"],
    freshness_sla_seconds=86400,
    features=[
        FeatureSpec("days_since_last_visit", "float", min_value=0.0),
        FeatureSpec("visit_frequency_trend", "float"),
        FeatureSpec("feature_usage_breadth", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("session_duration_trend", "float"),
        FeatureSpec("support_ticket_count", "int", min_value=0),
        FeatureSpec("billing_status", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("engagement_percentile", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("total_sessions", "int", min_value=0),
        FeatureSpec("avg_session_duration", "float", min_value=0.0),
        FeatureSpec("conversion_rate", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("days_since_first_visit", "float", min_value=0.0),
    ],
))

_register(FeatureContract(
    contract_id="ltv_prediction_v1",
    model_id="ltv_prediction",
    schema_version="1.0",
    source_feature_groups=["identity_features", "web3_features"],
    freshness_sla_seconds=86400,
    features=[
        FeatureSpec("purchase_frequency", "float", min_value=0.0),
        FeatureSpec("recency_days", "float", min_value=0.0),
        FeatureSpec("monetary_mean", "float", min_value=0.0),
        FeatureSpec("monetary_total", "float", min_value=0.0),
        FeatureSpec("avg_session_duration", "float", min_value=0.0),
        FeatureSpec("total_sessions", "int", min_value=0),
        FeatureSpec("conversion_rate", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("acquisition_channel_score", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("engagement_percentile", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("web3_tx_count", "int", min_value=0, required=False, default=0),
        FeatureSpec("web3_total_value", "float", min_value=0.0, required=False, default=0.0),
    ],
))

_register(FeatureContract(
    contract_id="anomaly_detection_v1",
    model_id="anomaly_detection",
    schema_version="1.0",
    source_feature_groups=["anomaly_features"],
    freshness_sla_seconds=300,
    features=[
        FeatureSpec("traffic_volume", "float", min_value=0.0),
        FeatureSpec("conversion_rate", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("avg_session_duration", "float", min_value=0.0),
        FeatureSpec("bounce_rate", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("error_rate", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("api_latency_p99", "float", min_value=0.0),
        FeatureSpec("bot_traffic_ratio", "float", min_value=0.0, max_value=1.0),
        FeatureSpec("unique_visitors", "float", min_value=0.0),
        FeatureSpec("revenue", "float", min_value=0.0),
    ],
))

_register(FeatureContract(
    contract_id="campaign_attribution_v1",
    model_id="campaign_attribution",
    schema_version="1.0",
    source_feature_groups=["attribution_features"],
    freshness_sla_seconds=3600,
    features=[
        FeatureSpec("touchpoint_count", "int", min_value=0,
                    aliases=["touchpoint_sequence"]),
        FeatureSpec("channel_diversity", "float", min_value=0.0,
                    aliases=["channel_ids"]),
        FeatureSpec("avg_time_delta", "float", min_value=0.0,
                    aliases=["time_deltas"]),
        FeatureSpec("conversion_value", "float", min_value=0.0),
        FeatureSpec("device_type_count", "int", min_value=0,
                    aliases=["device_types"]),
    ],
))

# Non-trainable contracts (minimal — required for registry completeness)
_register(FeatureContract(
    contract_id="bytecode_risk_v1",
    model_id="bytecode_risk",
    schema_version="1.0",
    source_feature_groups=["security_features"],
    freshness_sla_seconds=0,
    features=[
        FeatureSpec("bytecode_hash", "str"),
        FeatureSpec("opcode_count", "int", min_value=0),
        FeatureSpec("external_call_count", "int", min_value=0),
        FeatureSpec("self_destruct_present", "bool"),
        FeatureSpec("delegatecall_present", "bool"),
    ],
))

_register(FeatureContract(
    contract_id="trust_score_v1",
    model_id="trust_score",
    schema_version="1.0",
    source_feature_groups=["composite_inputs"],
    freshness_sla_seconds=300,
    features=[
        FeatureSpec("churn_probability", "float", min_value=0.0, max_value=1.0,
                    required=False, default=0.5),
        FeatureSpec("bot_confidence", "float", min_value=0.0, max_value=1.0,
                    required=False, default=0.0),
        FeatureSpec("anomaly_score", "float",
                    required=False, default=0.0),
        FeatureSpec("intent_confidence", "float", min_value=0.0, max_value=1.0,
                    required=False, default=0.5),
    ],
))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_feature_contract(model_id: str) -> FeatureContract:
    """
    Return the feature contract for a model.

    Raises KeyError if no contract is registered for model_id.
    """
    if model_id not in _CONTRACTS:
        known = sorted(_CONTRACTS.keys())
        raise KeyError(
            f"No feature contract for model '{model_id}'. Known: {known}"
        )
    return _CONTRACTS[model_id]


def validate_features(
    model_id: str,
    features: dict[str, Any],
    allow_defaults: bool = True,
) -> None:
    """
    Validate a feature dict against the model's contract.

    Args:
        model_id: Canonical model ID.
        features: Input feature dict (may include aliases).
        allow_defaults: If True, missing optional features are not errors.

    Raises:
        FeatureValidationError: On missing required features or type errors.
    """
    contract = get_feature_contract(model_id)

    # Build normalised key set (alias → canonical)
    normalised_keys: set[str] = set()
    for k in features:
        canonical_k = contract._alias_map.get(k, k)
        normalised_keys.add(canonical_k)

    missing: list[str] = []
    type_errors: list[str] = []

    for spec in contract.features:
        # Check presence (consider aliases)
        present = spec.name in normalised_keys
        if not present:
            for alias in spec.aliases:
                if alias in features:
                    present = True
                    break

        if not present:
            if spec.required and not allow_defaults:
                missing.append(spec.name)
            elif spec.required and spec.default is None and not spec.nullable:
                missing.append(spec.name)
            continue

        # Type check for the actual value
        value = features.get(spec.name)
        if value is None:
            for alias in spec.aliases:
                value = features.get(alias)
                if value is not None:
                    break

        if value is None:
            if spec.required and not spec.nullable:
                missing.append(spec.name)
            continue

        if spec.dtype == "float":
            _float_types = (int, float) + ((np.floating, np.integer) if _HAS_NUMPY else ())  # type: ignore[misc]
            if not isinstance(value, _float_types):
                type_errors.append(f"{spec.name}: expected float, got {type(value).__name__}")
        elif spec.dtype == "int":
            _int_types = (int,) + ((np.integer,) if _HAS_NUMPY else ())  # type: ignore[misc]
            if not isinstance(value, _int_types):
                type_errors.append(f"{spec.name}: expected int, got {type(value).__name__}")
        elif spec.dtype == "bool":
            _bool_types = (bool,) + ((np.bool_,) if _HAS_NUMPY else ())  # type: ignore[misc]
            if not isinstance(value, _bool_types):
                type_errors.append(f"{spec.name}: expected bool, got {type(value).__name__}")
        elif spec.dtype == "str":
            if not isinstance(value, str):
                type_errors.append(f"{spec.name}: expected str, got {type(value).__name__}")

    if missing or type_errors:
        parts = []
        if missing:
            parts.append(f"Missing required features: {missing}")
        if type_errors:
            parts.append(f"Type errors: {type_errors}")
        raise FeatureValidationError(
            model_id=model_id,
            message="; ".join(parts),
            missing=missing,
            type_errors=type_errors,
        )


def normalize_features(
    model_id: str,
    features: dict[str, Any],
    apply_defaults: bool = True,
) -> dict[str, Any]:
    """
    Normalise a feature dict: apply aliases, fill defaults.

    Returns a new dict with canonical feature names and defaults applied.
    """
    contract = get_feature_contract(model_id)
    result: dict[str, Any] = {}

    for spec in contract.features:
        # Try canonical name first, then aliases
        value = features.get(spec.name)
        if value is None:
            for alias in spec.aliases:
                value = features.get(alias)
                if value is not None:
                    break

        if value is not None:
            result[spec.name] = value
        elif apply_defaults and spec.default is not None:
            result[spec.name] = spec.default

    return result


def compute_schema_hash(model_id: str) -> str:
    """Return the stable schema hash for a model's feature contract."""
    return get_feature_contract(model_id).schema_hash


def explain_missing_features(
    model_id: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    """
    Return a human-readable explanation of what features are missing/extra.
    """
    contract = get_feature_contract(model_id)

    normalised_keys: set[str] = set()
    for k in features:
        canonical_k = contract._alias_map.get(k, k)
        normalised_keys.add(canonical_k)

    missing_required = [
        f.name for f in contract.features
        if f.required and f.name not in normalised_keys
    ]
    missing_optional = [
        f.name for f in contract.features
        if not f.required and f.name not in normalised_keys
    ]
    unknown = [
        k for k in normalised_keys
        if k not in contract._spec_map
    ]

    return {
        "model_id": model_id,
        "contract_id": contract.contract_id,
        "schema_version": contract.schema_version,
        "schema_hash": contract.schema_hash,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "unknown_features": unknown,
        "feature_count_provided": len(features),
        "feature_count_required": len(contract.required_features),
    }


def generate_example_features(model_id: str) -> dict[str, Any]:
    """
    Generate a valid example feature dict for a model (for testing/docs).
    """
    contract = get_feature_contract(model_id)
    example: dict[str, Any] = {}

    for spec in contract.features:
        if spec.dtype == "float":
            if spec.min_value is not None and spec.max_value is not None:
                example[spec.name] = round((spec.min_value + spec.max_value) / 2, 4)
            elif spec.min_value is not None:
                example[spec.name] = round(spec.min_value + 1.0, 4)
            else:
                example[spec.name] = 0.5
        elif spec.dtype == "int":
            if spec.min_value is not None:
                example[spec.name] = int(spec.min_value) + 1
            else:
                example[spec.name] = 1
        elif spec.dtype == "bool":
            example[spec.name] = False
        elif spec.dtype == "str":
            example[spec.name] = "example"
        else:
            example[spec.name] = spec.default if spec.default is not None else None

    return example
