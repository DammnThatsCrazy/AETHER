"""
Aether ML -- common layer re-exports.

Import the public API from submodules so downstream code can do::

    from common.src import AetherModel, FeatureStore, PreprocessingPipeline
"""

from common.src.base import (
    AetherModel,
    DeploymentTarget,
    FeatureEngineer,
    FeatureStore,
    ModelMetadata,
    ModelRegistry,
    ModelStage,
)
from common.src.metrics import MetricsCollector
from common.src.preprocessing import PreprocessingPipeline
from common.src.validation import (
    DataValidator,
    FeatureSchema,
    ValidationResult,
)

__all__ = [
    # base.py
    "AetherModel",
    "DeploymentTarget",
    "FeatureEngineer",
    "FeatureStore",
    "ModelMetadata",
    "ModelRegistry",
    "ModelStage",
    # preprocessing.py
    "PreprocessingPipeline",
    # validation.py
    "DataValidator",
    "FeatureSchema",
    "ValidationResult",
    # metrics.py
    "MetricsCollector",
]
