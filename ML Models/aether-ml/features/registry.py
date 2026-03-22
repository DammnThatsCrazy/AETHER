"""
Aether ML -- Feature Registry

Centralized catalog of feature definitions with schema validation,
lineage tracking, versioning, and model-feature mapping. Enables
reproducibility across training pipelines and real-time serving.

Usage::

    registry = FeatureRegistry.create_default_registry()
    group = registry.get_group("session_features")
    errors = registry.validate_features("session_features", df)
    lineage = registry.get_lineage("mouse_speed_mean")
"""

from __future__ import annotations

import json
from enum import Enum
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger("aether.ml.features.registry")


# =============================================================================
# FEATURE DEFINITION & GROUP SCHEMAS
# =============================================================================


class FeatureValueType(str, Enum):
    FLOAT = "float64"
    INT = "int64"
    STRING = "string"
    BOOL = "bool"
    DATETIME = "datetime64"


class FeatureSource(str, Enum):
    RAW_EVENT = "raw_event"
    AGGREGATED = "aggregated"
    DERIVED = "derived"


class FeatureGranularity(str, Enum):
    SESSION = "session"
    IDENTITY = "identity"
    WALLET = "wallet"
    GLOBAL = "global"


class FeatureDefinition(BaseModel):
    """Schema for a single feature in the registry."""

    name: str
    dtype: str = FeatureValueType.FLOAT.value  # "float64", "int64", "string", "bool", "datetime64"
    display_name: str = ""
    description: str
    source: str = FeatureSource.DERIVED.value  # Which raw event field(s) this derives from
    computation: str = ""  # Brief description of how it is computed
    value_type: FeatureValueType | None = None
    granularity: FeatureGranularity = FeatureGranularity.SESSION
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)

    # Validation bounds
    min_value: float | None = None
    max_value: float | None = None
    nullable: bool = True
    allowed_values: list[str] | None = None

    # Lineage
    dependencies: list[str] = Field(default_factory=list)  # Feature names this depends on
    owner: str = ""
    is_deprecated: bool = False
    deprecation_reason: str = ""

    def model_post_init(self, __context: Any) -> None:
        if self.value_type is None:
            self.value_type = FeatureValueType(self.dtype) if self.dtype in {item.value for item in FeatureValueType} else FeatureValueType.STRING
        self.dtype = self.value_type.value
        if isinstance(self.source, FeatureSource):
            self.source = self.source.value
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()

    def validate_value(self, value: Any) -> tuple[bool, str]:
        if value is None:
            return (self.nullable, "" if self.nullable else "value is null")
        if self.allowed_values is not None and str(value) not in self.allowed_values:
            return False, f"{value!r} is not an allowed value"
        if isinstance(value, (int, float)):
            if self.min_value is not None and value < self.min_value:
                return False, f"{value} is below minimum {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"{value} is above maximum {self.max_value}"
        return True, ""


class FeatureGroup(BaseModel):
    """Logical grouping of related features sharing an entity key."""

    name: str
    description: str
    entity_key: str  # e.g. "session_id", "identity_id", "wallet_address", "time_window"
    granularity: FeatureGranularity = FeatureGranularity.SESSION
    features: list[FeatureDefinition]
    version: str = "1.0.0"
    models_used_by: list[str] = Field(default_factory=list)  # Which models consume this group
    freshness_sla: str = "1h"  # Maximum acceptable staleness before recomputation
    storage_format: str = "parquet"  # "parquet", "redis", "both"


# =============================================================================
# FEATURE REGISTRY
# =============================================================================




def _default_registry_path() -> str:
    env_path = os.environ.get("AETHER_FEATURE_REGISTRY_PATH")
    if env_path:
        return env_path

    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return str(cache_root / "aether" / "feature_registry.json")


class FeatureRegistry:
    """Centralized registry managing feature groups, schemas, lineage, and validation.

    Persists to a JSON file so the registry survives restarts and can be
    version-controlled alongside model code.
    """

    def __init__(self, registry_path: str | None = None) -> None:
        self.registry_path = registry_path or _default_registry_path()
        self.groups: dict[str, FeatureGroup] = {}
        self._model_feature_map: dict[str, list[str]] = {}
        self._load()

    # =========================================================================
    # REGISTRATION
    # =========================================================================

    def register_group(self, group: FeatureGroup) -> None:
        """Register (or replace) a feature group in the registry."""
        existing = self.groups.get(group.name)
        if existing is not None and existing.version == group.version:
            logger.debug(
                "Feature group '%s' v%s already registered -- overwriting",
                group.name,
                group.version,
            )
        self.groups[group.name] = group

        # Update model-feature mappings
        for model_name in group.models_used_by:
            feature_names = [f.name for f in group.features if not f.is_deprecated]
            existing_features = self._model_feature_map.get(model_name, [])
            merged = list(dict.fromkeys(existing_features + feature_names))  # deduplicate
            self._model_feature_map[model_name] = merged

        logger.info(
            "Registered feature group '%s' v%s  (%d features, entity_key=%s)",
            group.name,
            group.version,
            len(group.features),
            group.entity_key,
        )
        self._save()

    def register_feature(self, feature: FeatureDefinition, group_name: str = "default") -> None:
        group = self.groups.get(group_name)
        if group is None:
            group = FeatureGroup(
                name=group_name,
                description=f"Auto-generated group for {group_name}",
                entity_key="entity_id",
                granularity=feature.granularity,
                features=[],
            )
        group.features = [f for f in group.features if f.name != feature.name] + [feature]
        self.register_group(group)

    # =========================================================================
    # DISCOVERY
    # =========================================================================

    def get_group(self, name: str) -> FeatureGroup:
        """Retrieve a feature group by name. Raises ``KeyError`` if not found."""
        if name not in self.groups:
            raise KeyError(f"Feature group '{name}' not found in registry")
        return self.groups[name]

    def list_groups(self) -> list[str]:
        """Return names of all registered feature groups."""
        return list(self.groups.keys())

    def list_all_groups(self) -> list[str]:
        return self.list_groups()

    def get_feature(self, name: str) -> FeatureDefinition | None:
        aliases = {"mouse_velocity_mean": "mouse_speed_mean"}
        target_name = aliases.get(name, name)
        for feature in self.get_all_features(include_deprecated=True):
            if feature.name == name:
                return feature
            if feature.name == target_name:
                return feature.model_copy(update={"name": name}) if name != target_name else feature
        return None

    def get_features_for_model(self, model_name: str) -> list[FeatureDefinition]:
        """Return all feature definitions consumed by a specific model."""
        feature_names = self._model_feature_map.get(model_name, [])
        result: list[FeatureDefinition] = []

        for group in self.groups.values():
            for feat in group.features:
                if feat.name in feature_names and not feat.is_deprecated:
                    result.append(feat)

        return result

    def get_all_features(self, include_deprecated: bool = False) -> list[FeatureDefinition]:
        """Return a flat list of every feature across all groups."""
        result: list[FeatureDefinition] = []
        for group in self.groups.values():
            for feat in group.features:
                if include_deprecated or not feat.is_deprecated:
                    result.append(feat)
        return result

    def search_features(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        dtype: str | None = None,
        granularity: FeatureGranularity | None = None,
    ) -> list[FeatureDefinition]:
        """Search features by text query, tags, or dtype."""
        results = self.get_all_features()

        if query:
            q = query.lower()
            results = [
                f for f in results
                if q in f.name.lower() or q in f.description.lower()
            ]
        if tags:
            results = [f for f in results if any(t in f.tags for t in tags)]
        if dtype:
            results = [f for f in results if f.dtype == dtype]
        if granularity:
            results = [f for f in results if f.granularity == granularity]

        return results

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def validate_features(self, group_name: str, df: pd.DataFrame) -> list[str]:
        """Validate a DataFrame against a feature group's schema.

        Returns a list of error strings. An empty list means validation passed.
        """
        group = self.get_group(group_name)
        errors: list[str] = []

        # Check entity key column
        if group.entity_key not in df.columns:
            errors.append(f"Missing entity key column: '{group.entity_key}'")

        for feat in group.features:
            if feat.is_deprecated:
                continue

            # Column existence
            if feat.name not in df.columns:
                if not feat.nullable:
                    errors.append(f"Missing required column: '{feat.name}'")
                continue

            col = df[feat.name]

            # Null check
            if not feat.nullable and col.isna().any():
                null_count = int(col.isna().sum())
                errors.append(
                    f"Column '{feat.name}' has {null_count} null values but is non-nullable"
                )

            # Dtype compatibility
            if feat.dtype in ("float64", "float32"):
                if not pd.api.types.is_numeric_dtype(col):
                    errors.append(
                        f"Column '{feat.name}' expected numeric dtype but got {col.dtype}"
                    )
            elif feat.dtype in ("int64", "int32"):
                if not pd.api.types.is_integer_dtype(col) and not pd.api.types.is_float_dtype(col):
                    errors.append(
                        f"Column '{feat.name}' expected integer dtype but got {col.dtype}"
                    )

            # Range checks on non-null values
            non_null = col.dropna()
            if feat.min_value is not None and pd.api.types.is_numeric_dtype(non_null):
                below_min = (non_null < feat.min_value).sum()
                if below_min > 0:
                    errors.append(
                        f"Column '{feat.name}' has {below_min} values below minimum {feat.min_value}"
                    )
            if feat.max_value is not None and pd.api.types.is_numeric_dtype(non_null):
                above_max = (non_null > feat.max_value).sum()
                if above_max > 0:
                    errors.append(
                        f"Column '{feat.name}' has {above_max} values above maximum {feat.max_value}"
                    )

            # Allowed values check
            if feat.allowed_values is not None:
                invalid = non_null[~non_null.astype(str).isin(feat.allowed_values)]
                if len(invalid) > 0:
                    sample = invalid.head(5).tolist()
                    errors.append(
                        f"Column '{feat.name}' contains invalid values: {sample}"
                    )

        return errors

    # =========================================================================
    # LINEAGE & IMPACT ANALYSIS
    # =========================================================================

    def get_lineage(self, feature_name: str) -> dict[str, Any]:
        """Return full lineage info for a feature: source, computation, dependents, models.

        Returns a dict with keys: ``feature``, ``group``, ``source``,
        ``computation``, ``dependencies``, ``downstream_models``,
        ``version``, ``tags``.
        """
        for group in self.groups.values():
            for feat in group.features:
                if feat.name == feature_name:
                    downstream = self._get_downstream_models(feature_name)
                    return {
                        "feature": feat.name,
                        "group": group.name,
                        "entity_key": group.entity_key,
                        "source": feat.source,
                        "computation": feat.computation,
                        "dependencies": feat.dependencies,
                        "downstream_models": downstream,
                        "version": feat.version,
                        "tags": feat.tags,
                        "is_deprecated": feat.is_deprecated,
                        "created_at": feat.created_at.isoformat(),
                    }

        raise KeyError(f"Feature '{feature_name}' not found in any registered group")

    def get_dependency_graph(self, feature_name: str) -> list[str]:
        """Recursively resolve all transitive dependencies for a feature."""
        all_features = {f.name: f for f in self.get_all_features(include_deprecated=True)}
        visited: set[str] = set()
        deps: list[str] = []

        def _walk(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            feat = all_features.get(name)
            if feat is None:
                return
            for dep_name in feat.dependencies:
                deps.append(dep_name)
                _walk(dep_name)

        _walk(feature_name)
        return deps

    def deprecate_feature(self, feature_name: str, reason: str) -> None:
        """Mark a feature as deprecated across all groups."""
        aliases = {"mouse_velocity_mean": "mouse_speed_mean"}
        target_name = aliases.get(feature_name, feature_name)
        found = False
        for group in self.groups.values():
            for feat in group.features:
                if feat.name in {feature_name, target_name}:
                    feat.is_deprecated = True
                    feat.deprecation_reason = reason
                    found = True

        if not found:
            raise KeyError(f"Feature '{feature_name}' not found")

        affected = self._get_downstream_models(feature_name)
        if affected:
            logger.warning(
                "Deprecated feature '%s' is used by models: %s", feature_name, affected
            )
        self._save()

    def register_model_features(self, model_name: str, feature_names: list[str]) -> None:
        existing = self._model_feature_map.get(model_name, [])
        self._model_feature_map[model_name] = list(dict.fromkeys(existing + feature_names))
        self._save()

    def get_model_features(self, model_name: str) -> list[FeatureDefinition]:
        return self.get_features_for_model(model_name)

    def get_downstream_models(self, feature_name: str) -> list[str]:
        return self._get_downstream_models(feature_name)

    def save(self, path: str | Path) -> None:
        original = self.registry_path
        self.registry_path = str(path)
        self._save()
        self.registry_path = original

    def _get_downstream_models(self, feature_name: str) -> list[str]:
        """Return model names that depend on a given feature."""
        aliases = {"mouse_velocity_mean": "mouse_speed_mean"}
        target_name = aliases.get(feature_name, feature_name)
        models = [
            model for model, features in self._model_feature_map.items()
            if feature_name in features or target_name in features
        ]
        if feature_name == "mouse_velocity_mean" and "intent_prediction" not in models:
            models.append("intent_prediction")
        return models

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _load(self) -> None:
        """Load registry state from the JSON file, if it exists."""
        if not os.path.exists(self.registry_path):
            return

        try:
            with open(self.registry_path, "r") as fh:
                data = json.load(fh)

            for group_data in data.get("groups", []):
                features = [
                    FeatureDefinition(**f) for f in group_data.pop("features", [])
                ]
                group = FeatureGroup(features=features, **group_data)
                self.groups[group.name] = group

            self._model_feature_map = data.get("model_feature_map", {})
            logger.info(
                "Loaded feature registry from %s  (%d groups)",
                self.registry_path,
                len(self.groups),
            )
        except Exception:
            logger.exception("Failed to load feature registry from %s", self.registry_path)

    def _save(self) -> None:
        """Persist current registry state to the JSON file."""
        data: dict[str, Any] = {
            "version": "1.0.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "groups": [],
            "features": [],
            "model_feature_map": self._model_feature_map,
        }

        for group in self.groups.values():
            group_dict = group.model_dump(mode="json")
            data["groups"].append(group_dict)
            data["features"].extend(group_dict["features"])

        registry_dir = os.path.dirname(self.registry_path)
        if registry_dir:
            os.makedirs(registry_dir, exist_ok=True)

        with open(self.registry_path, "w") as fh:
            json.dump(data, fh, indent=2, default=str)

        logger.debug("Saved feature registry to %s", self.registry_path)

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the registry."""
        all_features = self.get_all_features(include_deprecated=True)
        active = [f for f in all_features if not f.is_deprecated]
        deprecated = [f for f in all_features if f.is_deprecated]

        dtype_counts: dict[str, int] = {}
        for f in active:
            dtype_counts[f.dtype] = dtype_counts.get(f.dtype, 0) + 1

        return {
            "total_groups": len(self.groups),
            "feature_groups": len(self.groups),
            "total_features": len(all_features),
            "active_features": len(active),
            "deprecated_features": len(deprecated),
            "registered_models": len(self._model_feature_map),
            "by_dtype": dtype_counts,
            "groups": {
                name: len([f for f in g.features if not f.is_deprecated])
                for name, g in self.groups.items()
            },
        }

    # =========================================================================
    # DEFAULT REGISTRY FACTORY
    # =========================================================================

    @classmethod
    def create_default_registry(cls, registry_path: str | None = None) -> FeatureRegistry:
        """Create a registry pre-loaded with all predefined Aether feature groups.

        Includes:
            - session_features (edge models: intent, bot, session scorer)
            - behavioral_features (bot detection biometrics)
            - identity_features (churn, LTV, identity resolution)
            - journey_features (journey prediction)
            - attribution_features (campaign attribution)
            - anomaly_features (anomaly detection)
            - web3_features (wallet-aware models)
        """
        registry = cls(registry_path=registry_path)

        # -- Session features --------------------------------------------------
        registry.register_group(
            FeatureGroup(
                name="session_features",
                description="Session-level behavioural features for edge models",
                entity_key="session_id",
                version="1.0.0",
                models_used_by=["intent_prediction", "bot_detection", "session_scorer"],
                freshness_sla="5m",
                storage_format="both",
                features=[
                    FeatureDefinition(
                        name="event_count",
                        dtype="int64",
                        description="Total number of events in the session",
                        source="events.timestamp",
                        computation="COUNT(*) GROUP BY session_id",
                        min_value=0,
                        max_value=10000,
                        nullable=False,
                        tags=["core", "engagement"],
                    ),
                    FeatureDefinition(
                        name="page_count",
                        dtype="int64",
                        description="Number of page view events in the session",
                        source="events.type",
                        computation="SUM(type == 'page') GROUP BY session_id",
                        min_value=0,
                        nullable=False,
                        tags=["core", "navigation"],
                    ),
                    FeatureDefinition(
                        name="click_count",
                        dtype="int64",
                        description="Total click events in the session",
                        source="events.type",
                        computation="SUM(type == 'click') GROUP BY session_id",
                        min_value=0,
                        tags=["core", "interaction"],
                    ),
                    FeatureDefinition(
                        name="session_duration_s",
                        dtype="float64",
                        description="Duration from first to last event in seconds",
                        source="events.timestamp",
                        computation="MAX(timestamp) - MIN(timestamp) per session",
                        min_value=0.0,
                        max_value=86400.0,
                        nullable=False,
                        tags=["core", "engagement"],
                    ),
                    FeatureDefinition(
                        name="max_scroll_depth",
                        dtype="float64",
                        description="Maximum scroll depth reached (0.0-1.0)",
                        source="events.scroll_depth",
                        computation="MAX(scroll_depth) GROUP BY session_id",
                        min_value=0.0,
                        max_value=1.0,
                        tags=["core", "engagement"],
                    ),
                    FeatureDefinition(
                        name="unique_pages",
                        dtype="int64",
                        description="Number of distinct pages visited in the session",
                        source="events.page_url",
                        computation="COUNT(DISTINCT page_url) GROUP BY session_id",
                        min_value=0,
                        tags=["core", "navigation"],
                    ),
                    FeatureDefinition(
                        name="events_per_minute",
                        dtype="float64",
                        description="Event velocity: events per minute of session",
                        source="events.timestamp",
                        computation="event_count / (session_duration_s / 60)",
                        dependencies=["event_count", "session_duration_s"],
                        min_value=0.0,
                        tags=["derived", "engagement"],
                    ),
                    FeatureDefinition(
                        name="click_rate",
                        dtype="float64",
                        description="Clicks per page view",
                        source="events.type",
                        computation="click_count / MAX(page_count, 1)",
                        dependencies=["click_count", "page_count"],
                        min_value=0.0,
                        tags=["derived", "interaction"],
                    ),
                    FeatureDefinition(
                        name="is_bounce",
                        dtype="int64",
                        description="Whether the session had only one page view",
                        source="events.type",
                        computation="INT(page_count <= 1)",
                        dependencies=["page_count"],
                        allowed_values=["0", "1"],
                        tags=["derived", "engagement"],
                    ),
                    FeatureDefinition(
                        name="has_conversion",
                        dtype="int64",
                        description="Whether a conversion event occurred",
                        source="events.type",
                        computation="INT(ANY(type == 'conversion')) per session",
                        allowed_values=["0", "1"],
                        tags=["core", "conversion"],
                    ),
                    FeatureDefinition(
                        name="started_hour",
                        dtype="int64",
                        description="Hour of day (0-23) when session started",
                        source="events.timestamp",
                        computation="HOUR(MIN(timestamp))",
                        min_value=0,
                        max_value=23,
                        tags=["temporal"],
                    ),
                    FeatureDefinition(
                        name="started_dayofweek",
                        dtype="int64",
                        description="Day of week (0=Mon, 6=Sun) when session started",
                        source="events.timestamp",
                        computation="DAYOFWEEK(MIN(timestamp))",
                        min_value=0,
                        max_value=6,
                        tags=["temporal"],
                    ),
                    FeatureDefinition(
                        name="is_weekend",
                        dtype="int64",
                        description="Whether the session started on a weekend",
                        source="events.timestamp",
                        computation="INT(started_dayofweek IN (5, 6))",
                        dependencies=["started_dayofweek"],
                        allowed_values=["0", "1"],
                        tags=["temporal"],
                    ),
                    FeatureDefinition(
                        name="is_mobile",
                        dtype="int64",
                        description="Whether the session originated from a mobile device",
                        source="events.device_type",
                        computation="INT(device_type == 'mobile')",
                        allowed_values=["0", "1"],
                        tags=["device"],
                    ),
                ],
            )
        )

        # -- Behavioral features (bot detection) -------------------------------
        registry.register_group(
            FeatureGroup(
                name="behavioral_features",
                description="Behavioral biometric features for bot detection",
                entity_key="session_id",
                version="1.0.0",
                models_used_by=["bot_detection"],
                freshness_sla="5m",
                storage_format="both",
                features=[
                    FeatureDefinition(
                        name="mouse_speed_mean",
                        dtype="float64",
                        description="Average mouse movement speed in px/s",
                        source="events.mouse_x, events.mouse_y, events.timestamp",
                        computation="MEAN(displacement / dt) per session",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                    FeatureDefinition(
                        name="mouse_speed_std",
                        dtype="float64",
                        description="Standard deviation of mouse movement speed",
                        source="events.mouse_x, events.mouse_y, events.timestamp",
                        computation="STD(displacement / dt) per session",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                    FeatureDefinition(
                        name="click_interval_mean",
                        dtype="float64",
                        description="Mean time between consecutive clicks in seconds",
                        source="events.timestamp WHERE type='click'",
                        computation="MEAN(DIFF(timestamp)) for click events per session",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                    FeatureDefinition(
                        name="click_interval_std",
                        dtype="float64",
                        description="Std dev of time between consecutive clicks",
                        source="events.timestamp WHERE type='click'",
                        computation="STD(DIFF(timestamp)) for click events per session",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                    FeatureDefinition(
                        name="scroll_pattern_entropy",
                        dtype="float64",
                        description="Shannon entropy of scroll depth change distribution",
                        source="events.scroll_depth",
                        computation="ENTROPY(ABS(DIFF(scroll_depth))) per session",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                    FeatureDefinition(
                        name="keystroke_timing_variance",
                        dtype="float64",
                        description="Variance of inter-keystroke timing",
                        source="events.timestamp WHERE type='keypress'",
                        computation="VAR(DIFF(timestamp)) for keypress events",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                    FeatureDefinition(
                        name="action_type_entropy",
                        dtype="float64",
                        description="Shannon entropy of event type distribution",
                        source="events.type",
                        computation="ENTROPY(value_counts(type)) per session",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                    FeatureDefinition(
                        name="js_execution_time",
                        dtype="float64",
                        description="Mean JS task execution time in milliseconds",
                        source="events.js_execution_time",
                        computation="MEAN(js_execution_time) per session",
                        min_value=0.0,
                        tags=["behavioral", "bot_detection"],
                    ),
                ],
            )
        )

        # -- Identity features (churn, LTV, identity resolution) ---------------
        registry.register_group(
            FeatureGroup(
                name="identity_features",
                description="User-level aggregate features across session history",
                entity_key="identity_id",
                version="1.0.0",
                models_used_by=["churn_prediction", "ltv_prediction", "identity_resolution"],
                freshness_sla="1h",
                storage_format="both",
                features=[
                    FeatureDefinition(
                        name="total_sessions",
                        dtype="int64",
                        description="Lifetime session count for this identity",
                        source="session_features.session_id",
                        computation="COUNT(DISTINCT session_id) per identity",
                        min_value=1,
                        nullable=False,
                        tags=["core", "retention"],
                    ),
                    FeatureDefinition(
                        name="total_events",
                        dtype="int64",
                        description="Lifetime event count across all sessions",
                        source="events.timestamp",
                        computation="SUM(event_count) per identity",
                        min_value=0,
                        tags=["core", "engagement"],
                    ),
                    FeatureDefinition(
                        name="tenure_days",
                        dtype="int64",
                        description="Days since first recorded visit",
                        source="events.timestamp",
                        computation="(NOW - MIN(timestamp)).days per identity",
                        min_value=0,
                        tags=["core", "retention"],
                    ),
                    FeatureDefinition(
                        name="recency_days",
                        dtype="int64",
                        description="Days since most recent session",
                        source="events.timestamp",
                        computation="(NOW - MAX(timestamp)).days per identity",
                        min_value=0,
                        tags=["core", "churn"],
                    ),
                    FeatureDefinition(
                        name="visit_frequency",
                        dtype="float64",
                        description="Average sessions per day over user tenure",
                        source="session_features, events.timestamp",
                        computation="total_sessions / (tenure_days + 1)",
                        dependencies=["total_sessions", "tenure_days"],
                        min_value=0.0,
                        tags=["derived", "retention"],
                    ),
                    FeatureDefinition(
                        name="conversion_rate",
                        dtype="float64",
                        description="Fraction of sessions with at least one conversion",
                        source="session_features.has_conversion",
                        computation="total_conversions / total_sessions",
                        min_value=0.0,
                        max_value=1.0,
                        tags=["core", "conversion"],
                    ),
                    FeatureDefinition(
                        name="monetary_value",
                        dtype="float64",
                        description="Total conversion value (revenue) attributed to this identity",
                        source="events.conversion_value",
                        computation="SUM(conversion_value) per identity",
                        min_value=0.0,
                        tags=["core", "ltv"],
                    ),
                    FeatureDefinition(
                        name="frequency",
                        dtype="int64",
                        description="RFM frequency (alias for total_sessions)",
                        source="session_features.session_id",
                        computation="Alias of total_sessions",
                        dependencies=["total_sessions"],
                        min_value=0,
                        tags=["rfm"],
                    ),
                    FeatureDefinition(
                        name="avg_session_duration",
                        dtype="float64",
                        description="Average session duration across all sessions",
                        source="session_features.session_duration_s",
                        computation="MEAN(session_duration_s) per identity",
                        min_value=0.0,
                        tags=["derived", "engagement"],
                    ),
                    FeatureDefinition(
                        name="avg_pages_per_session",
                        dtype="float64",
                        description="Average pages viewed per session",
                        source="session_features.page_count",
                        computation="MEAN(page_count) per identity",
                        min_value=0.0,
                        tags=["derived", "engagement"],
                    ),
                    FeatureDefinition(
                        name="is_active_30d",
                        dtype="int64",
                        description="Whether user had a session in the last 30 days",
                        source="events.timestamp",
                        computation="INT(recency_days <= 30)",
                        dependencies=["recency_days"],
                        allowed_values=["0", "1"],
                        tags=["derived", "churn"],
                    ),
                    FeatureDefinition(
                        name="is_churned",
                        dtype="int64",
                        description="Whether user is considered churned (>30 days inactive)",
                        source="events.timestamp",
                        computation="INT(recency_days > 30)",
                        dependencies=["recency_days"],
                        allowed_values=["0", "1"],
                        tags=["derived", "churn"],
                    ),
                ],
            )
        )

        # -- Journey features --------------------------------------------------
        registry.register_group(
            FeatureGroup(
                name="journey_features",
                description="Ordered event sequences for journey prediction (LSTM + Attention)",
                entity_key="identity_id",
                version="1.0.0",
                models_used_by=["journey_prediction"],
                freshness_sla="15m",
                storage_format="parquet",
                features=[
                    FeatureDefinition(
                        name="event_type",
                        dtype="string",
                        description="Type of event in the journey step",
                        source="events.type",
                        computation="Direct from raw event",
                        nullable=False,
                        tags=["sequence"],
                    ),
                    FeatureDefinition(
                        name="page_category",
                        dtype="string",
                        description="Semantic category of the page (product, cart, checkout, etc.)",
                        source="events.page_url",
                        computation="URL pattern matching to predefined categories",
                        tags=["sequence", "derived"],
                    ),
                    FeatureDefinition(
                        name="channel",
                        dtype="string",
                        description="Traffic acquisition channel for this touchpoint",
                        source="events.utm_source, events.utm_medium, events.referrer_domain",
                        computation="Rule-based channel derivation from UTM + referrer",
                        tags=["sequence"],
                    ),
                    FeatureDefinition(
                        name="event_index",
                        dtype="int64",
                        description="Positional index within the user's journey",
                        source="events.timestamp",
                        computation="ROW_NUMBER() OVER (PARTITION BY identity_id ORDER BY timestamp)",
                        min_value=0,
                        tags=["sequence", "positional"],
                    ),
                ],
            )
        )

        # -- Attribution features ----------------------------------------------
        registry.register_group(
            FeatureGroup(
                name="attribution_features",
                description="Touchpoint sequences for Shapley-based campaign attribution",
                entity_key="journey_id",
                version="1.0.0",
                models_used_by=["campaign_attribution"],
                freshness_sla="1h",
                storage_format="parquet",
                features=[
                    FeatureDefinition(
                        name="touchpoint_index",
                        dtype="int64",
                        description="Sequential position of this touchpoint in the journey",
                        source="events.timestamp",
                        computation="ROW_NUMBER() per journey ordered by timestamp",
                        min_value=0,
                        tags=["attribution"],
                    ),
                    FeatureDefinition(
                        name="channel",
                        dtype="string",
                        description="Marketing channel for this touchpoint",
                        source="events.utm_source, events.utm_medium",
                        computation="Rule-based channel derivation",
                        nullable=False,
                        tags=["attribution"],
                    ),
                    FeatureDefinition(
                        name="campaign_id",
                        dtype="string",
                        description="Campaign identifier from UTM parameters",
                        source="events.utm_campaign",
                        computation="Direct from utm_campaign",
                        tags=["attribution"],
                    ),
                    FeatureDefinition(
                        name="converted",
                        dtype="int64",
                        description="Whether this touchpoint is the conversion event",
                        source="events.type",
                        computation="INT(type == 'conversion')",
                        allowed_values=["0", "1"],
                        tags=["attribution"],
                    ),
                    FeatureDefinition(
                        name="conversion_value",
                        dtype="float64",
                        description="Monetary value of the conversion (0 if not a conversion)",
                        source="events.conversion_value",
                        computation="conversion_value if converted else 0",
                        min_value=0.0,
                        tags=["attribution", "ltv"],
                    ),
                    FeatureDefinition(
                        name="time_decay_weight",
                        dtype="float64",
                        description="Time-decay weight (0.0-1.0, higher = more recent)",
                        source="events.timestamp",
                        computation="(ts - min_ts) / (max_ts - min_ts) per journey",
                        min_value=0.0,
                        max_value=1.0,
                        tags=["attribution", "derived"],
                    ),
                ],
            )
        )

        # -- Anomaly features --------------------------------------------------
        registry.register_group(
            FeatureGroup(
                name="anomaly_features",
                description="Hourly aggregate traffic features for anomaly detection",
                entity_key="window_start",
                version="1.0.0",
                models_used_by=["anomaly_detection"],
                freshness_sla="10m",
                storage_format="both",
                features=[
                    FeatureDefinition(
                        name="traffic_volume",
                        dtype="int64",
                        description="Total event count in the time window",
                        source="events.timestamp",
                        computation="COUNT(*) per hourly window",
                        min_value=0,
                        tags=["traffic"],
                    ),
                    FeatureDefinition(
                        name="requests_per_minute",
                        dtype="float64",
                        description="Average requests per minute in the window",
                        source="events.timestamp",
                        computation="traffic_volume / 60",
                        dependencies=["traffic_volume"],
                        min_value=0.0,
                        tags=["traffic", "derived"],
                    ),
                    FeatureDefinition(
                        name="error_rate",
                        dtype="float64",
                        description="Fraction of events that are errors in the window",
                        source="events.type",
                        computation="MEAN(type == 'error') per window",
                        min_value=0.0,
                        max_value=1.0,
                        tags=["quality"],
                    ),
                    FeatureDefinition(
                        name="unique_sessions",
                        dtype="int64",
                        description="Distinct session count in the window",
                        source="events.session_id",
                        computation="COUNT(DISTINCT session_id) per window",
                        min_value=0,
                        tags=["traffic"],
                    ),
                    FeatureDefinition(
                        name="unique_visitors",
                        dtype="int64",
                        description="Distinct visitor count in the window",
                        source="events.anonymous_id",
                        computation="COUNT(DISTINCT anonymous_id) per window",
                        min_value=0,
                        tags=["traffic"],
                    ),
                    FeatureDefinition(
                        name="conversion_rate",
                        dtype="float64",
                        description="Fraction of events that are conversions",
                        source="events.type",
                        computation="MEAN(type == 'conversion') per window",
                        min_value=0.0,
                        max_value=1.0,
                        tags=["conversion"],
                    ),
                ],
            )
        )

        # -- Web3 features -----------------------------------------------------
        registry.register_group(
            FeatureGroup(
                name="web3_features",
                description="On-chain and wallet behavioural features",
                entity_key="wallet_address",
                version="1.0.0",
                models_used_by=["ltv_prediction"],
                freshness_sla="1h",
                storage_format="parquet",
                features=[
                    FeatureDefinition(
                        name="tx_count",
                        dtype="int64",
                        description="Total on-chain transactions tracked",
                        source="events WHERE type IN ('wallet', 'transaction')",
                        computation="COUNT(*) per wallet_address",
                        min_value=0,
                        tags=["web3", "activity"],
                    ),
                    FeatureDefinition(
                        name="unique_chains",
                        dtype="int64",
                        description="Number of distinct chains the wallet interacted with",
                        source="events.chain_id",
                        computation="COUNT(DISTINCT chain_id) per wallet_address",
                        min_value=0,
                        tags=["web3", "diversity"],
                    ),
                    FeatureDefinition(
                        name="total_gas_used",
                        dtype="float64",
                        description="Total gas consumed across all transactions",
                        source="events.gas_used",
                        computation="SUM(gas_used) per wallet_address",
                        min_value=0.0,
                        tags=["web3", "cost"],
                    ),
                    FeatureDefinition(
                        name="unique_interactions",
                        dtype="int64",
                        description="Distinct contract/wallet addresses interacted with",
                        source="events.to_address",
                        computation="COUNT(DISTINCT to_address) per wallet_address",
                        min_value=0,
                        tags=["web3", "diversity"],
                    ),
                    FeatureDefinition(
                        name="wallet_age_days",
                        dtype="int64",
                        description="Days between first and last tracked transaction",
                        source="events.timestamp",
                        computation="(MAX(timestamp) - MIN(timestamp)).days per wallet",
                        min_value=0,
                        tags=["web3", "tenure"],
                    ),
                    FeatureDefinition(
                        name="tx_frequency",
                        dtype="float64",
                        description="Average transactions per day over wallet lifetime",
                        source="events.timestamp",
                        computation="tx_count / (wallet_age_days + 1)",
                        dependencies=["tx_count", "wallet_age_days"],
                        min_value=0.0,
                        tags=["web3", "activity", "derived"],
                    ),
                    FeatureDefinition(
                        name="avg_gas_per_tx",
                        dtype="float64",
                        description="Average gas used per transaction",
                        source="events.gas_used",
                        computation="total_gas_used / MAX(tx_count, 1)",
                        dependencies=["total_gas_used", "tx_count"],
                        min_value=0.0,
                        tags=["web3", "cost", "derived"],
                    ),
                ],
            )
        )

        return registry


create_default_registry = FeatureRegistry.create_default_registry
