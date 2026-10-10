"""
Aether Security — Model Extraction Defense

Modular defense layer against model extraction and knowledge distillation
attacks. Integrates as middleware into the ML serving pipeline.

Components:
  - QueryRateLimiter:        Per-key + per-IP sliding window limits
  - QueryPatternDetector:    Sweep, similarity, entropy, timing analysis
  - OutputPerturbationLayer: Logit noise, top-k clipping, entropy smoothing
  - ModelWatermark:          Probabilistic signature embedding in outputs
  - CanaryInputDetector:     Hidden trap inputs to detect scraping
  - ExtractionRiskScorer:    Aggregated risk score driving response degradation

Quick start:
    from governance.model_extraction_defense import ExtractionDefenseLayer

    defense = ExtractionDefenseLayer.from_env()
    pre = defense.pre_request(api_key, ip, features, model_name)
    if not pre.blocked:
        post = defense.post_response(api_key, raw_output, features)
"""

from .canary_detector import CanaryDetection, CanaryInputDetector
from .cleanup import CleanupThread, cleanup_periodic, start_cleanup_thread
from .config import ExtractionDefenseConfig
from .defense_layer import ExtractionDefenseLayer, PostResponseResult, PreRequestResult
from .metrics import DefenseMetrics
from .output_perturbation import OutputPerturbationLayer
from .pattern_detector import PatternAnalysis, QueryPatternDetector
from .rate_limiter import QueryRateLimiter, RateLimitCheck
from .risk_scorer import ExtractionRiskScorer, RiskAssessment
from .watermark import ModelWatermark

__all__ = [
    # Facade
    "ExtractionDefenseLayer",
    "PreRequestResult",
    "PostResponseResult",
    # Config
    "ExtractionDefenseConfig",
    # Components
    "QueryRateLimiter",
    "RateLimitCheck",
    "QueryPatternDetector",
    "PatternAnalysis",
    "OutputPerturbationLayer",
    "ModelWatermark",
    "CanaryInputDetector",
    "CanaryDetection",
    "ExtractionRiskScorer",
    "RiskAssessment",
    # Operational
    "DefenseMetrics",
    "CleanupThread",
    "start_cleanup_thread",
    "cleanup_periodic",
]
