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
import os
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.scoring.trust")


def _local_mode() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


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

    async def _call_ml(self, model_name: str, entity_id: str, features: dict) -> Optional[dict]:
        if self._ml is None:
            return None
        if callable(self._ml):
            return await self._ml(model_name=model_name, entity_id=entity_id, features=features)
        if hasattr(self._ml, "predict"):
            return await self._ml.predict(model_name=model_name, entity_id=entity_id, features=features)
        return None

    async def _resolve_fraud_score(self, entity_id: str, features: dict) -> Optional[float]:
        if "fraud_composite_score" in features:
            return float(features["fraud_composite_score"])
        if self._fraud is None:
            return None
        event = {
            "event_type": features.get("event_type", "trust_score"),
            "channel": features.get("channel"),
            "session_id": features.get("session_id", entity_id),
            "properties": features,
        }
        result = await self._fraud.evaluate(event, features)
        return float(result.composite_score)

    async def _resolve_identity_confidence(self, entity_id: str, features: dict) -> Optional[float]:
        if "identity_confidence" in features:
            return float(features["identity_confidence"])
        if self._resolution is None:
            return None
        if hasattr(self._resolution, "get_confidence"):
            return float(await self._resolution.get_confidence(entity_id, features))
        if callable(self._resolution):
            return float(await self._resolution(entity_id=entity_id, features=features))
        return None

    @staticmethod
    def _extract_score(raw: Optional[dict], *keys: str) -> Optional[float]:
        if not raw:
            return None
        for key in keys:
            if key in raw:
                try:
                    return float(raw[key])
                except (TypeError, ValueError):
                    continue
        nested = raw.get("result")
        if isinstance(nested, dict):
            for key in keys:
                if key in nested:
                    try:
                        return float(nested[key])
                    except (TypeError, ValueError):
                        continue
        return None

    async def compute(
        self,
        entity_id: str,
        entity_type: str = "human",
        features: Optional[dict] = None,
    ) -> TrustScore:
        """
        Compute composite trust score from existing model outputs.

        In non-local environments this fails closed unless the required
        upstream model/engine signals are available either in ``features``
        or through injected service adapters.
        """
        features = features or {}
        components: dict = {}

        # Component 1: Transaction Trust (40%)
        # Uses: Fraud Engine (8 signals) + Anomaly Detection model
        fraud_score = await self._resolve_fraud_score(entity_id, features)
        anomaly_result = await self._call_ml("anomaly_detection", entity_id, features)
        anomaly_score = self._extract_score(anomaly_result, "anomaly_score", "score")
        if fraud_score is None:
            fraud_score = 0.0 if _local_mode() else None
        if anomaly_score is None:
            anomaly_score = float(features.get("anomaly_score", 0.0)) if _local_mode() else None
        if fraud_score is None or anomaly_score is None:
            raise RuntimeError("TrustScoreComposite requires live fraud and anomaly signals in non-local environments")
        transaction_trust = max(0.0, 1.0 - (fraud_score / 100.0)) * (1.0 - anomaly_score)
        components["fraud_score"] = fraud_score
        components["anomaly_score"] = anomaly_score

        # Component 2: Identity Trust (35%)
        # Uses: Identity Resolution confidence + Bot Detection model
        # Default 0.1: unknown identity = low trust
        identity_confidence = await self._resolve_identity_confidence(entity_id, features)
        bot_result = await self._call_ml("bot_detection", entity_id, features)
        bot_score = self._extract_score(bot_result, "bot_score", "score", "probability")
        if identity_confidence is None:
            identity_confidence = float(features.get("identity_confidence", 0.1)) if _local_mode() else None
        if bot_score is None:
            bot_score = float(features.get("bot_score", 0.0)) if _local_mode() else None
        if identity_confidence is None or bot_score is None:
            raise RuntimeError("TrustScoreComposite requires live identity and bot signals in non-local environments")
        identity_trust = identity_confidence * (1.0 - bot_score)
        components["identity_confidence"] = identity_confidence
        components["bot_score"] = bot_score

        # Component 3: Behavioral Trust (25%)
        # Uses: Session Scorer + Churn Prediction model
        # Default 0.1: no behavioral data = low trust
        session_result = await self._call_ml("session_scorer", entity_id, features)
        churn_result = await self._call_ml("churn_prediction", entity_id, features)
        session_score = self._extract_score(session_result, "session_score", "score", "confidence")
        churn_risk = self._extract_score(churn_result, "churn_risk", "score", "probability")
        if session_score is None:
            session_score = float(features.get("session_score", 0.1)) if _local_mode() else None
        if churn_risk is None:
            churn_risk = float(features.get("churn_risk", 0.0)) if _local_mode() else None
        if session_score is None or churn_risk is None:
            raise RuntimeError("TrustScoreComposite requires live behavioral signals in non-local environments")
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
