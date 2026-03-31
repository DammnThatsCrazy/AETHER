"""
Extraction Baseline Builder — internal-only infrastructure.

Constructs self-history, peer-cohort, and graph-neighbor baselines
for the extraction expectation engine. Uses existing analytics,
graph, and identity subsystems.

No public API — consumed only by ExtractionExpectationEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.expectations.baseline_builder")


@dataclass
class ActorBaseline:
    """Baseline behavior profile for an actor."""
    usual_models: list[str] = field(default_factory=list)
    usual_rpm: float = 0.0
    usual_batch_size: float = 1.0
    usual_feature_locality: float = 0.0    # how concentrated feature space is
    usual_endpoint_mix: dict[str, float] = field(default_factory=dict)
    usual_device_count: int = 1
    usual_ip_count: int = 1
    sample_size: int = 0
    quality: float = 0.0                   # 0–1 confidence in baseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "usual_models": self.usual_models,
            "usual_rpm": round(self.usual_rpm, 2),
            "usual_batch_size": round(self.usual_batch_size, 1),
            "usual_feature_locality": round(self.usual_feature_locality, 3),
            "usual_device_count": self.usual_device_count,
            "usual_ip_count": self.usual_ip_count,
            "sample_size": self.sample_size,
            "quality": round(self.quality, 2),
        }


@dataclass
class PeerBaseline:
    """Peer cohort baseline for comparison."""
    cohort_id: str = ""
    cohort_size: int = 0
    avg_rpm: float = 0.0
    avg_models_per_day: float = 1.0
    avg_batch_size: float = 1.0
    p95_rpm: float = 0.0
    quality: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "cohort_size": self.cohort_size,
            "avg_rpm": round(self.avg_rpm, 2),
            "avg_models_per_day": round(self.avg_models_per_day, 1),
            "p95_rpm": round(self.p95_rpm, 2),
            "quality": round(self.quality, 2),
        }


class BaselineBuilder:
    """
    Builds behavioral baselines from existing subsystem data.

    Currently builds baselines from in-request history maintained by the
    ExtractionExpectationEngine. Future versions can pull from the
    AnalyticsRepository and GraphClient for richer baselines.
    """

    @staticmethod
    def build_self_baseline(history: list[dict]) -> ActorBaseline:
        """Build a self-history baseline from actor request records."""
        if not history:
            return ActorBaseline(quality=0.0)

        models = list(set(r.get("model", "") for r in history if r.get("model")))
        batch_sizes = [r.get("batch_size", 1) for r in history]
        ips = set(r.get("ip", "") for r in history if r.get("ip"))
        devices = set(r.get("device", "") for r in history if r.get("device"))

        # Compute average RPM from timestamps
        if len(history) >= 2:
            span = max(history[-1].get("ts", 0) - history[0].get("ts", 0), 60)
            avg_rpm = len(history) / (span / 60)
        else:
            avg_rpm = 0.0

        quality = min(len(history) / 50.0, 1.0)

        return ActorBaseline(
            usual_models=models[:10],
            usual_rpm=avg_rpm,
            usual_batch_size=sum(batch_sizes) / max(len(batch_sizes), 1),
            usual_device_count=len(devices),
            usual_ip_count=len(ips),
            sample_size=len(history),
            quality=quality,
        )

    @staticmethod
    def build_peer_baseline(
        tenant_id: str = "",
        tier: str = "",
    ) -> PeerBaseline:
        """
        Build a peer cohort baseline.

        Currently returns sensible defaults. In production, this would
        query aggregate statistics from the analytics system.
        """
        return PeerBaseline(
            cohort_id=f"{tenant_id}:{tier}" if tenant_id else "default",
            cohort_size=100,
            avg_rpm=5.0,
            avg_models_per_day=2.0,
            avg_batch_size=1.0,
            p95_rpm=30.0,
            quality=0.3,  # Low quality until backed by real analytics
        )
