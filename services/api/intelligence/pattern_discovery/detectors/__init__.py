"""Unknown-pattern detectors. Each takes a :class:`DiscoveryFrame` and returns a
:class:`DetectorOutput`. All are deterministic, bounded and dependency-free."""
from __future__ import annotations

from typing import Callable

from ..contracts import (
    KIND_BEHAVIORAL_COHORT, KIND_LOCKSTEP, KIND_NOVEL_MOTIF, KIND_OUTLIER, KIND_SCHEMA_DRIFT,
    KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE, KIND_TEMPORAL_BURST,
)
from .attributes import detect_shared_attributes
from .base import DetectorOutput
from .cohorts import detect_behavioral_cohorts
from .cross_domain import correlate
from .frame import DetectorConfig, DiscoveryFrame
from .motifs import detect_motifs, known_motif_signatures
from .outliers import detect_outliers
from .schema_drift import detect_schema_drift
from .sequences import detect_sequences
from .temporal import detect_temporal

#: detector name -> (function, kinds it can emit)
DETECTORS: dict[str, tuple[Callable[[DiscoveryFrame], DetectorOutput], frozenset[str]]] = {
    "schema_drift": (detect_schema_drift, frozenset({KIND_SCHEMA_DRIFT})),
    "sequences": (detect_sequences, frozenset({KIND_SEQUENCE})),
    "shared_attributes": (detect_shared_attributes, frozenset({KIND_SHARED_ATTRIBUTE})),
    "behavioral_cohorts": (detect_behavioral_cohorts, frozenset({KIND_BEHAVIORAL_COHORT})),
    "temporal": (detect_temporal, frozenset({KIND_TEMPORAL_BURST, KIND_LOCKSTEP})),
    "outliers": (detect_outliers, frozenset({KIND_OUTLIER})),
    "motifs": (detect_motifs, frozenset({KIND_NOVEL_MOTIF})),
}

__all__ = [
    "DETECTORS", "DetectorConfig", "DetectorOutput", "DiscoveryFrame", "correlate",
    "known_motif_signatures",
]
