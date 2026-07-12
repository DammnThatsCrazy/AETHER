"""Persistence for model-governance evidence.

Training-data admission decisions (admitted + quarantined) are durable evidence
that a training set was consent-filtered. Inference decisions reuse the consent
PolicyDecision store via ``services.policy`` and are not duplicated here.
"""
from __future__ import annotations

from services.security.repositories import _ScopedRepo


class TrainingDataDecisionRepository(_ScopedRepo):
    """Tenant-scoped store of training-data admission decisions.

    Table: ``model_training_decisions``. Quarantined records are the security-
    relevant rows (a label that was refused admission); admitted rows are kept
    for completeness so a training set's provenance is fully reconstructable.
    """

    def __init__(self) -> None:
        super().__init__("model_training_decisions")
