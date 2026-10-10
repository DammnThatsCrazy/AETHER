"""
Aether Intelligence — Extraction Attribution Service

Server-side lineage tracking and canary management for extraction defense.
Focuses on attribution (not response watermarking) per the constraint
against user-visible perturbation.

Functions:
    - Maintain secret canary input families
    - Maintain server-side response lineage
    - Track suspected clone behavior downstream
    - Attach hidden attribution metadata to internal audit records
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.scoring.extraction_models import ExtractionIdentity

logger = get_logger("aether.intelligence.attribution")


# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE LINEAGE RECORD
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ResponseLineage:
    """Server-side record linking a response to its request context."""
    lineage_id: str = field(default_factory=lambda: f"lin_{uuid.uuid4().hex[:16]}")
    request_id: str = ""
    api_key_id: str = ""
    tenant_id: str = ""
    model_name: str = ""
    feature_hash: str = ""
    response_hash: str = ""
    risk_score: float = 0.0
    policy_action: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "request_id": self.request_id,
            "api_key_id": self.api_key_id[:8] + "..." if self.api_key_id else "",
            "tenant_id": self.tenant_id,
            "model_name": self.model_name,
            "feature_hash": self.feature_hash,
            "response_hash": self.response_hash,
            "risk_score": round(self.risk_score, 2),
            "policy_action": self.policy_action,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════════
# CANARY HIT RECORD
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CanaryHitRecord:
    """Record of a canary input detection."""
    hit_id: str = field(default_factory=lambda: f"chit_{uuid.uuid4().hex[:12]}")
    canary_family: str = ""
    canary_index: int = 0
    api_key_id: str = ""
    source_ip: str = ""
    model_name: str = ""
    match_distance: float = 0.0
    timestamp: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION ATTRIBUTION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionAttributionService:
    """
    Server-side attribution and canary management.

    Default: server-side lineage + canary hits. No response watermarking
    (which would be user-visible perturbation).
    """

    def __init__(
        self,
        canary_secret: str = "aether-mesh-canary-seed",
        max_lineage_records: int = 10000,
        max_canary_hits: int = 1000,
    ) -> None:
        self._canary_secret = canary_secret
        self._lineage: list[ResponseLineage] = []
        self._canary_hits: list[CanaryHitRecord] = []
        self._canary_families: dict[str, list[dict]] = {}
        self._max_lineage = max_lineage_records
        self._max_hits = max_canary_hits

    # ── Response Lineage ─────────────────────────────────────────────

    def record_lineage(
        self,
        identity: ExtractionIdentity,
        model_name: str,
        feature_hash: str,
        response_value: Any,
        risk_score: float = 0.0,
        policy_action: str = "",
    ) -> str:
        """Record a response lineage entry. Returns the lineage ID."""
        response_hash = hashlib.sha256(str(response_value).encode()).hexdigest()[:16]

        lineage = ResponseLineage(
            request_id=identity.request_id or "",
            api_key_id=identity.api_key_id or "",
            tenant_id=identity.tenant_id or "",
            model_name=model_name,
            feature_hash=feature_hash,
            response_hash=response_hash,
            risk_score=risk_score,
            policy_action=policy_action,
        )

        self._lineage.append(lineage)
        if len(self._lineage) > self._max_lineage:
            self._lineage = self._lineage[-self._max_lineage:]

        metrics.increment("extraction_lineage_recorded")
        return lineage.lineage_id

    def query_lineage(
        self,
        api_key_id: Optional[str] = None,
        model_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query lineage records for investigation."""
        results = self._lineage
        if api_key_id:
            results = [r for r in results if r.api_key_id == api_key_id]
        if model_name:
            results = [r for r in results if r.model_name == model_name]
        return [r.to_dict() for r in results[-limit:]]

    # ── Canary Management ────────────────────────────────────────────

    def generate_canary_family(
        self,
        family_name: str,
        n_features: int,
        count: int = 20,
    ) -> list[dict[str, float]]:
        """
        Generate a family of canary feature vectors.

        Canaries are deterministic (seeded from secret + family name) so
        they can be recognized on subsequent requests.
        """
        import struct

        canaries = []
        for i in range(count):
            seed = hmac.new(
                self._canary_secret.encode(),
                f"{family_name}:{i}".encode(),
                hashlib.sha256,
            ).digest()

            features = {}
            for j in range(n_features):
                offset = (j * 4) % len(seed)
                raw = struct.unpack_from(">f", seed, offset % (len(seed) - 3))[0]
                # Normalize to [0, 1] range
                features[f"f{j}"] = abs(raw) % 1.0

            canaries.append(features)

        self._canary_families[family_name] = canaries
        logger.info(
            "Generated canary family '%s': %d canaries, %d features",
            family_name, count, n_features,
        )
        return canaries

    def check_canary(
        self,
        features: dict[str, Any],
        tolerance: float = 0.05,
    ) -> Optional[CanaryHitRecord]:
        """
        Check if input features match any canary family member.

        Returns a CanaryHitRecord if matched, None otherwise.
        """
        float_features = {
            k: float(v) for k, v in features.items()
            if isinstance(v, (int, float))
        }
        if not float_features:
            return None

        for family_name, canaries in self._canary_families.items():
            for idx, canary in enumerate(canaries):
                distance = _feature_distance(float_features, canary)
                if distance < tolerance:
                    hit = CanaryHitRecord(
                        canary_family=family_name,
                        canary_index=idx,
                        match_distance=distance,
                    )
                    self._canary_hits.append(hit)
                    if len(self._canary_hits) > self._max_hits:
                        self._canary_hits = self._canary_hits[-self._max_hits:]

                    metrics.increment("extraction_canary_hit")
                    logger.warning(
                        "Canary hit: family=%s index=%d distance=%.4f",
                        family_name, idx, distance,
                    )
                    return hit

        return None

    def get_canary_hits(self, limit: int = 50) -> list[dict]:
        """Return recent canary hit records."""
        return [
            {
                "hit_id": h.hit_id,
                "canary_family": h.canary_family,
                "canary_index": h.canary_index,
                "api_key_id": h.api_key_id[:8] + "..." if h.api_key_id else "",
                "match_distance": round(h.match_distance, 4),
                "timestamp": h.timestamp,
            }
            for h in self._canary_hits[-limit:]
        ]

    # ── Attribution Fingerprint ──────────────────────────────────────

    def compute_attribution_fingerprint(
        self,
        identity: ExtractionIdentity,
        model_name: str,
    ) -> str:
        """
        Compute a deterministic attribution fingerprint for this caller/model.

        Used internally to correlate responses. NOT embedded in output.
        """
        raw = f"{identity.primary_key}:{model_name}:{self._canary_secret}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _feature_distance(features: dict[str, float], canary: dict[str, float]) -> float:
    """L2 distance between feature dict and canary dict."""
    common_keys = set(features.keys()) & set(canary.keys())
    if not common_keys:
        return float("inf")

    sum_sq = sum((features[k] - canary[k]) ** 2 for k in common_keys)
    return (sum_sq / len(common_keys)) ** 0.5
