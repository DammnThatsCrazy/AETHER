"""Model governance — consent-scoped training-data admission and inference gates.

Reuses the canonical consent PolicyDecision engine (``governance.policy``) so model
training and serving decisions are the same explainable, audited evidence records
as every other sensitive action. Purpose semantics come from the canonical
consent registry (``packages/shared/contracts/consent-registry.json``).
"""
from __future__ import annotations

from intelligence.model_governance.contracts import (
    InferenceGateResult,
    TrainingDataDecision,
    TrainingDataGateResult,
)
from intelligence.model_governance.inference_gate import (
    InferencePolicyGate,
    inference_policy_gate,
)
from intelligence.model_governance.training_gate import (
    TrainingDataGate,
    training_data_gate,
)

__all__ = [
    "InferenceGateResult",
    "TrainingDataDecision",
    "TrainingDataGateResult",
    "InferencePolicyGate",
    "inference_policy_gate",
    "TrainingDataGate",
    "training_data_gate",
]
