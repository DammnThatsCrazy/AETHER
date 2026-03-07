"""
Aether Shared — Trust Score Composite
NOT a new ML model. A weighted composite of existing model outputs:
  - Transaction Trust (40%): Fraud Engine + Anomaly Detection
  - Identity Trust (35%):    Identity Resolution + Bot Detection
  - Behavioral Trust (25%):  Session Scorer + Churn Prediction

Used by: Agent service, Commerce service, Analytics dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.scoring.trust")


# ═══════════════════════════════════════════════════════════════════════════
# TRUST SCORE RESULT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TrustScore:
    entity_id: str
    entity_type: str  # "human" | "agent" | "contract"
    transaction_trust: float   # 0.0 – 1.0
    identity_trust: float      # 0.0 – 1.0
    behavioral_trust: float    # 0.0 – 1.0
    composite: float           # Weighted average
    components: dict           # Raw model outputs used

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "transaction_trust": round(self.transaction_trust, 4),
            "identity_trust": round(self.identity_trust, 4),
            "behavioral_trust": round(self.behavioral_trust, 4),
            "composite": round(self.composite, 4),
            "components": self.components,
        }


# ═══════════════════════════════════════════════════════════════════════════
# WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════

TRANSACTION_WEIGHT = 0.40
IDENTITY_WEIGHT = 0.35
BEHAVIORAL_WEIGHT = 0.25


# ═══════════════════════════════════════════════════════════════════════════
# COMPOSITE SCORER
# ═══════════════════════════════════════════════════════════════════════════

class TrustScoreComposite:
    """
    3-component trust score using existing model outputs. No new training.
    Each component calls existing ML serving or fraud engine endpoints.
    """

    def __init__(
        self,
        ml_serving: Optional[object] = None,
        fraud_engine: Optional[object] = None,
        resolution_engine: Optional[object] = None,
    ):
        """
        Args:
            ml_serving: ML serving client (production DI).
            fraud_engine: Fraud engine client (production DI).
            resolution_engine: Identity resolution engine (production DI).
        """
        self._ml = ml_serving
        self._fraud = fraud_engine
        self._resolution = resolution_engine

    async def compute(
        self,
        entity_id: str,
        entity_type: str = "human",
        features: Optional[dict] = None,
    ) -> TrustScore:
        """
        Compute composite trust score from existing model outputs.

        In production, each component calls the relevant ML serving endpoint.
        Stub implementation returns neutral scores.
        """
        features = features or {}
        components: dict = {}

        # Component 1: Transaction Trust (40%)
        # Uses: Fraud Engine (8 signals) + Anomaly Detection model
        fraud_score = features.get("fraud_composite_score", 0.0)
        anomaly_score = features.get("anomaly_score", 0.0)
        transaction_trust = max(0.0, 1.0 - (fraud_score / 100.0)) * (1.0 - anomaly_score)
        components["fraud_score"] = fraud_score
        components["anomaly_score"] = anomaly_score

        # Component 2: Identity Trust (35%)
        # Uses: Identity Resolution confidence + Bot Detection model
        # Default 0.1: unknown identity = low trust
        identity_confidence = features.get("identity_confidence", 0.1)
        bot_score = features.get("bot_score", 0.0)
        identity_trust = identity_confidence * (1.0 - bot_score)
        components["identity_confidence"] = identity_confidence
        components["bot_score"] = bot_score

        # Component 3: Behavioral Trust (25%)
        # Uses: Session Scorer + Churn Prediction model
        # Default 0.1: no behavioral data = low trust
        session_score = features.get("session_score", 0.1)
        churn_risk = features.get("churn_risk", 0.0)
        behavioral_trust = session_score * (1.0 - churn_risk)
        components["session_score"] = session_score
        components["churn_risk"] = churn_risk

        # Weighted composite (clamped to [0.0, 1.0])
        composite = (
            TRANSACTION_WEIGHT * transaction_trust
            + IDENTITY_WEIGHT * identity_trust
            + BEHAVIORAL_WEIGHT * behavioral_trust
        )
        composite = max(0.0, min(1.0, composite))

        score = TrustScore(
            entity_id=entity_id,
            entity_type=entity_type,
            transaction_trust=transaction_trust,
            identity_trust=identity_trust,
            behavioral_trust=behavioral_trust,
            composite=composite,
            components=components,
        )

        metrics.increment("trust_score_computed", labels={"entity_type": entity_type})
        logger.info(f"Trust score computed for {entity_type}:{entity_id} = {composite:.4f}")
        return score
