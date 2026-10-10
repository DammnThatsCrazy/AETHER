"""
Expectation Engine data models — signals, baselines, and evidence.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now


class SignalType(str, Enum):
    """Types of expectation signals (ranked by business priority)."""
    IDENTITY_CONTRADICTION = "identity_contradiction"
    RELATIONSHIP_CONTRADICTION = "relationship_contradiction"
    BROKEN_SEQUENCE = "broken_sequence"
    MISSING_EXPECTED_ACTION = "missing_expected_action"
    MISSING_EXPECTED_EDGE = "missing_expected_edge"
    PEER_DEVIATION = "peer_deviation"
    SELF_DEVIATION = "self_deviation"
    COHORT_ANOMALY = "cohort_anomaly"
    SOURCE_SILENCE = "source_silence"
    TEMPORAL_CONTRADICTION = "temporal_contradiction"
    MODEL_CONTRADICTION = "model_contradiction"
    GRAPH_CONTRADICTION = "graph_contradiction"


class SignalSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class BaselineSource(str, Enum):
    SELF_HISTORY = "self_history"
    PEER_GROUP = "peer_group"
    GRAPH_NEIGHBOR = "graph_neighbor"
    TENANT_NORM = "tenant_norm"
    SOURCE_NORM = "source_norm"
    CADENCE_NORM = "cadence_norm"
    PROTOCOL_NORM = "protocol_norm"


class SignalCreate(BaseModel):
    entity_id: str
    entity_type: str = "user"
    signal_type: SignalType
    severity: SignalSeverity = SignalSeverity.MEDIUM
    expected: Any = None
    observed: Any = None
    baseline_source: BaselineSource = BaselineSource.SELF_HISTORY
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    explanation: str = ""
    is_source_silence: bool = False
    source_tag: str = ""
    window_start: str = ""
    window_end: str = ""
    metadata: dict = Field(default_factory=dict)


def make_signal_record(
    entity_id: str,
    entity_type: str,
    signal_type: SignalType,
    severity: SignalSeverity = SignalSeverity.MEDIUM,
    expected: Any = None,
    observed: Any = None,
    baseline_source: BaselineSource = BaselineSource.SELF_HISTORY,
    confidence: float = 0.5,
    explanation: str = "",
    is_source_silence: bool = False,
    source_tag: str = "",
    tenant_id: str = "",
    window_start: str = "",
    window_end: str = "",
    metadata: Optional[dict] = None,
    population_id: str = "",
) -> dict:
    """Create a canonical expectation signal record."""
    now = utc_now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "entity_id": entity_id,
        "entity_type": entity_type,
        "signal_type": signal_type.value,
        "severity": severity.value,
        "expected": expected,
        "observed": observed,
        "baseline_source": baseline_source.value,
        "confidence": confidence,
        "explanation": explanation,
        "is_source_silence": is_source_silence,
        "source_tag": source_tag,
        "tenant_id": tenant_id,
        "population_id": population_id,
        "window_start": window_start,
        "window_end": window_end,
        "metadata": metadata or {},
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
