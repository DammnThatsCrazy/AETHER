"""
Aether ML -- Feature Engineering Layer

Re-exports the key classes for batch and streaming feature computation,
the centralized feature registry, and real-time streaming processors.
"""

from features.pipeline import FeaturePipeline, FeaturePipelineConfig
from features.registry import (
    FeatureDefinition,
    FeatureGroup,
    FeatureRegistry,
)
from features.streaming import (
    StreamingFeatureProcessor,
    StreamingWindow,
)

__all__ = [
    "FeaturePipeline",
    "FeaturePipelineConfig",
    "FeatureDefinition",
    "FeatureGroup",
    "FeatureRegistry",
    "StreamingFeatureProcessor",
    "StreamingWindow",
]
