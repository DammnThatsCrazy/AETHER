"""
Aether Shared — Extraction Defense Mesh Data Models

Core data structures for the extraction defense system. These models are
used across the distributed budget engine, expectation engine, extraction
scorer, policy engine, and telemetry pipeline.

Design:
    - ExtractionIdentity normalizes all available caller dimensions.
    - ExtractionSignal captures a single behavioral indicator.
    - ExtractionRiskAssessment is the sibling score output (NOT merged into TrustScore).
    - OutputDisclosurePolicy controls what callers see in responses.
    - ModelSensitivityTier classifies models by protection priority.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════
# MODEL SENSITIVITY TIERS
# ═══════════════════════════════════════════════════════════════════════════

class ModelSensitivityTier(str, Enum):
    """Protection priority: highest business value > easiest to distill > most privacy-sensitive."""
    TIER_1_CRITICAL = "tier_1_critical"
    TIER_2_HIGH = "tier_2_high"
    TIER_3_STANDARD = "tier_3_standard"


# Default tier assignments for known models
MODEL_TIER_MAP: dict[str, ModelSensitivityTier] = {
    # Tier 1 — highest business value + easiest to distill
    "churn_prediction": ModelSensitivityTier.TIER_1_CRITICAL,
    "ltv_prediction": ModelSensitivityTier.TIER_1_CRITICAL,
    "anomaly_detection": ModelSensitivityTier.TIER_1_CRITICAL,
    # Tier 2 — high value, moderate distillation risk
    "intent_prediction": ModelSensitivityTier.TIER_2_HIGH,
    "bot_detection": ModelSensitivityTier.TIER_2_HIGH,
    "campaign_attribution": ModelSensitivityTier.TIER_2_HIGH,
    # Tier 3 — standard protection
    "session_scorer": ModelSensitivityTier.TIER_3_STANDARD,
    "journey_prediction": ModelSensitivityTier.TIER_3_STANDARD,
    "identity_resolution": ModelSensitivityTier.TIER_3_STANDARD,
}


def get_model_tier(model_name: str) -> ModelSensitivityTier:
    """Look up sensitivity tier for a model. Defaults to TIER_2_HIGH for unknown models."""
    return MODEL_TIER_MAP.get(model_name, ModelSensitivityTier.TIER_2_HIGH)


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION IDENTITY
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractionIdentity:
    """
    Normalized identity record assembled for every ML inference request.

    Not all fields will be populated on every request — the system scores
    with whatever is available and improves automatically when richer
    client signals exist.
    """
    api_key_id: Optional[str] = None
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    source_ip: Optional[str] = None
    ip_prefix: Optional[str] = None       # /24 prefix for IP clustering
    asn: Optional[str] = None
    user_agent_hash: Optional[str] = None
    device_fingerprint: Optional[str] = None
    tls_fingerprint: Optional[str] = None
    wallet_id: Optional[str] = None
    identity_cluster_id: Optional[str] = None
    graph_cluster_id: Optional[str] = None

    @property
    def primary_key(self) -> str:
        """Best available identifier for this caller."""
        return self.api_key_id or self.user_id or self.source_ip or "anonymous"

    @property
    def available_dimensions(self) -> list[str]:
        """List of non-None identity dimensions."""
        return [
            name for name in [
                "api_key_id", "tenant_id", "user_id", "session_id",
                "source_ip", "ip_prefix", "asn", "device_fingerprint",
                "tls_fingerprint", "wallet_id", "identity_cluster_id",
                "graph_cluster_id",
            ]
            if getattr(self, name) is not None
        ]

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION SIGNAL
# ═══════════════════════════════════════════════════════════════════════════

class SignalSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ExtractionSignal:
    """A single extraction behavior indicator."""
    name: str
    value: float                          # 0.0 – 1.0 normalized
    severity: SignalSeverity = SignalSeverity.INFO
    evidence: dict[str, Any] = field(default_factory=dict)
    source: str = ""                      # e.g. "self_baseline", "peer_baseline"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "severity": self.severity.value,
            "evidence": self.evidence,
            "source": self.source,
        }


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION RISK BAND
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionRiskBand(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION RISK ASSESSMENT (SIBLING SCORE)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractionRiskAssessment:
    """
    Extraction risk assessment — independent from TrustScore.

    This is a sibling score with its own policy engine. It is NOT merged
    into the composite trust score.
    """
    score: float                          # 0 – 100
    band: ExtractionRiskBand = ExtractionRiskBand.GREEN
    reasons: list[str] = field(default_factory=list)
    signals: list[ExtractionSignal] = field(default_factory=list)
    policy_recommendation: str = "allow"
    attribution_fingerprint_id: Optional[str] = None
    identity: Optional[ExtractionIdentity] = None
    assessed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "band": self.band.value,
            "reasons": self.reasons,
            "signals": [s.to_dict() for s in self.signals],
            "policy_recommendation": self.policy_recommendation,
            "assessed_at": self.assessed_at,
        }

    @staticmethod
    def band_from_score(score: float) -> ExtractionRiskBand:
        if score >= 80:
            return ExtractionRiskBand.RED
        elif score >= 55:
            return ExtractionRiskBand.ORANGE
        elif score >= 30:
            return ExtractionRiskBand.YELLOW
        return ExtractionRiskBand.GREEN


# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT DISCLOSURE POLICY
# ═══════════════════════════════════════════════════════════════════════════

class ConfidenceMode(str, Enum):
    EXACT = "exact"
    ROUNDED = "rounded"
    BUCKETED = "bucketed"
    HIDDEN = "hidden"


@dataclass
class OutputDisclosurePolicy:
    """
    Controls what information is disclosed in ML prediction responses.

    No user-visible perturbation — only disclosure minimization:
    rounding, bucketing, suppression of secondary scores, and
    privileged-only exact paths.
    """
    allow_exact_scores: bool = False
    confidence_mode: ConfidenceMode = ConfidenceMode.ROUNDED
    output_precision: int = 2             # decimal places when rounded
    include_secondary_scores: bool = True
    include_probabilities: bool = True
    batch_allowed: bool = True
    max_batch_rows: int = 1000
    suppress_feature_importance: bool = False

    def apply_confidence(self, value: float) -> float:
        """Apply disclosure policy to a confidence/probability value."""
        if self.confidence_mode == ConfidenceMode.EXACT:
            return value
        elif self.confidence_mode == ConfidenceMode.ROUNDED:
            return round(value, self.output_precision)
        elif self.confidence_mode == ConfidenceMode.BUCKETED:
            return _bucket_confidence(value)
        elif self.confidence_mode == ConfidenceMode.HIDDEN:
            return -1.0  # sentinel: caller should omit this field
        return round(value, self.output_precision)


def _bucket_confidence(value: float) -> float:
    """Map a probability to a coarse bucket (0.1 increments)."""
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return round(round(value * 10) / 10, 1)


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION EVENT RECORD
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractionEventRecord:
    """Canonical extraction telemetry record for persistence and analysis."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    identity: Optional[ExtractionIdentity] = None
    risk_assessment: Optional[ExtractionRiskAssessment] = None
    policy_applied: Optional[OutputDisclosurePolicy] = None
    model_name: str = ""
    model_tier: str = ""
    endpoint: str = ""
    batch_size: int = 1
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "model_name": self.model_name,
            "model_tier": self.model_tier,
            "endpoint": self.endpoint,
            "batch_size": self.batch_size,
            "timestamp": self.timestamp,
        }
        if self.identity:
            result["identity"] = self.identity.to_dict()
        if self.risk_assessment:
            result["risk_assessment"] = self.risk_assessment.to_dict()
        if self.metadata:
            result["metadata"] = self.metadata
        return result
