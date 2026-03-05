"""
Aether ML — Model Optimization Suite

Post-training optimization for freshness and razor-edge accuracy:
  - Quantization: Reduce model size via INT8/FP16 weight compression
  - Distillation: Transfer knowledge from large server models to small edge models
  - Pruning: Remove redundant weights/neurons for faster inference

All optimizers implement the same `optimize()` → `OptimizationResult` interface.
"""

from optimization.quantization import ModelQuantizer, QuantizationConfig
from optimization.distillation import ModelDistiller, DistillationConfig
from optimization.pruning import ModelPruner, PruningConfig
from optimization.pipeline import OptimizationPipeline, OptimizationResult

__all__ = [
    "ModelQuantizer", "QuantizationConfig",
    "ModelDistiller", "DistillationConfig",
    "ModelPruner", "PruningConfig",
    "OptimizationPipeline", "OptimizationResult",
]
