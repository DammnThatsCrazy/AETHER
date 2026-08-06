"""
Aether Shared — Trust Score Composite
NOT a new ML model. A weighted composite of existing model outputs:
  - Transaction Trust (40%): Fraud Engine + Anomaly Detection
  - Identity Trust (35%):    Identity Resolution + Bot Detection
  - Behavioral Trust (25%):  Session Scorer + Churn Prediction

Used by: Agent service, Commerce service, Analytics dashboard.

When an ML serving client (httpx) is provided, the scorer calls the ML
serving API for real predictions. Otherwise it uses the feature dict
passed directly (or defaults for local dev).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.scoring.trust")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HTTPX_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════
# TRUST SCORE RESULT
# ═══════════════════════════════════════════════════════════════════════════

# The prior used when a component has NO observed evidence. Absent risk
# evidence is NOT benign — trust is not inferred from silence, so the component
# defaults to a conservative LOW prior (matching the identity/behavioral absent
# defaults) and the gap is disclosed via ``evidence_coverage``.
ABSENT_EVIDENCE_PRIOR = 0.1


@dataclass
class TrustScore:
    entity_id: str
    entity_type: str  # "human" | "agent" | "contract"
    transaction_trust: float   # 0.0 – 1.0
    identity_trust: float      # 0.0 – 1.0
    behavioral_trust: float    # 0.0 – 1.0
    composite: float           # Weighted average
    components: dict           # Raw model outputs used
    # Which components had real evidence vs a low prior from absence. This is a
    # HeuristicScore composite, not a calibrated probability.
    evidence_coverage: Optional[dict] = None
    score_kind: str = "heuristic"

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "transaction_trust": round(self.transaction_trust, 4),
            "identity_trust": round(self.identity_trust, 4),
            "behavioral_trust": round(self.behavioral_trust, 4),
            "composite": round(self.composite, 4),
            "components": self.components,
            "evidence_coverage": self.evidence_coverage or {},
            "score_kind": self.score_kind,
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

    When ml_serving_url is configured (or ML_SERVING_URL env var),
    the scorer calls the ML serving API for bot detection, anomaly,
    session scoring, and churn predictions. Otherwise it uses
    the feature dict passed directly (for local development or
    when features are pre-computed by the caller).
    """

    def __init__(
        self,
        ml_serving_url: Optional[str] = None,
        fraud_engine: Optional[object] = None,
        resolution_engine: Optional[object] = None,
    ):
        self._ml_url = ml_serving_url or os.getenv("ML_SERVING_URL", "")
        self._fraud = fraud_engine
        self._resolution = resolution_engine

    async def _fetch_ml_score(self, model_type: str, signals: dict) -> Optional[dict]:
        """Call ML serving API for a prediction. Returns None on failure."""
        if not self._ml_url or not HTTPX_AVAILABLE:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self._ml_url}/v1/predict",
                    json={"type": model_type, "signals": signals},
                )
                if resp.status_code == 200:
                    return resp.json().get("data", {}).get("prediction", {})
        except Exception as e:
            logger.warning(f"ML serving call failed for {model_type}: {e}")
        return None

    async def compute(
        self,
        entity_id: str,
        entity_type: str = "human",
        features: Optional[dict] = None,
    ) -> TrustScore:
        """
        Compute composite trust score.

        If features are provided, uses them directly. Otherwise calls
        ML serving API for real-time predictions. Falls back to safe
        defaults (low trust) if both sources unavailable.
        """
        features = features or {}
        components: dict = {}

        # ── Component 1: Transaction Trust (40%) ──────────────────────
        fraud_score = features.get("fraud_composite_score")
        anomaly_score = features.get("anomaly_score")

        if anomaly_score is None and self._ml_url:
            ml_result = await self._fetch_ml_score("anomaly", {
                "entity_id": entity_id, "entity_type": entity_type,
            })
            if ml_result:
                anomaly_score = ml_result.get("anomaly_score", 0.0)

        fraud_observed = fraud_score is not None
        anomaly_observed = anomaly_score is not None
        fraud_score = fraud_score if fraud_observed else 0.0
        anomaly_score = anomaly_score if anomaly_observed else 0.0
        if not fraud_observed and not anomaly_observed:
            # No risk evidence at all — do NOT read absence as full trust
            # (the prior bug produced transaction_trust = 1.0 from zero evidence).
            transaction_trust = ABSENT_EVIDENCE_PRIOR
            transaction_evidence = "missing"
        else:
            transaction_trust = max(0.0, 1.0 - (fraud_score / 100.0)) * (1.0 - anomaly_score)
            transaction_evidence = "complete" if (fraud_observed and anomaly_observed) else "partial"
        components["fraud_score"] = fraud_score
        components["anomaly_score"] = anomaly_score

        # ── Component 2: Identity Trust (35%) ─────────────────────────
        identity_confidence = features.get("identity_confidence")
        bot_score = features.get("bot_score")

        if bot_score is None and self._ml_url:
            ml_result = await self._fetch_ml_score("bot", {
                "entity_id": entity_id, "entity_type": entity_type,
            })
            if ml_result:
                bot_score = ml_result.get("confidence", 0.0)

        identity_observed = identity_confidence is not None or bot_score is not None
        identity_confidence = identity_confidence if identity_confidence is not None else 0.1
        bot_score = bot_score if bot_score is not None else 0.0
        identity_trust = identity_confidence * (1.0 - bot_score)
        components["identity_confidence"] = identity_confidence
        components["bot_score"] = bot_score

        # ── Component 3: Behavioral Trust (25%) ──────────────────────
        session_score = features.get("session_score")
        churn_risk = features.get("churn_risk")

        if session_score is None and self._ml_url:
            ml_result = await self._fetch_ml_score("session_score", {
                "entity_id": entity_id, "entity_type": entity_type,
            })
            if ml_result:
                session_score = ml_result.get("engagement_score", 0.1)

        if churn_risk is None and self._ml_url:
            ml_result = await self._fetch_ml_score("churn", {
                "entity_id": entity_id, "entity_type": entity_type,
            })
            if ml_result:
                churn_risk = ml_result.get("churn_probability", 0.0)

        behavioral_observed = session_score is not None or churn_risk is not None
        session_score = session_score if session_score is not None else 0.1
        churn_risk = churn_risk if churn_risk is not None else 0.0
        behavioral_trust = session_score * (1.0 - churn_risk)
        components["session_score"] = session_score
        components["churn_risk"] = churn_risk

        # ── Weighted composite ────────────────────────────────────────
        composite = (
            TRANSACTION_WEIGHT * transaction_trust
            + IDENTITY_WEIGHT * identity_trust
            + BEHAVIORAL_WEIGHT * behavioral_trust
        )
        composite = max(0.0, min(1.0, composite))

        evidence_coverage = {
            "transaction": transaction_evidence,
            "identity": "complete" if identity_observed else "missing",
            "behavioral": "complete" if behavioral_observed else "missing",
            "observed_components": int(transaction_evidence != "missing")
            + int(identity_observed)
            + int(behavioral_observed),
            "total_components": 3,
        }
        score = TrustScore(
            entity_id=entity_id,
            entity_type=entity_type,
            transaction_trust=transaction_trust,
            identity_trust=identity_trust,
            behavioral_trust=behavioral_trust,
            composite=composite,
            components=components,
            evidence_coverage=evidence_coverage,
        )

        metrics.increment("trust_score_computed", labels={"entity_type": entity_type})
        logger.info(f"Trust score computed for {entity_type}:{entity_id} = {composite:.4f}")
        return score
