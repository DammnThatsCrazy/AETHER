"""
Extraction Signal Builder — internal-only infrastructure.

Constructs extraction-specific signals from expectation engine outputs,
budget state, and fraud cross-signals. No public API.
"""

from __future__ import annotations

from typing import Optional

from shared.scoring.extraction_models import (
    ExtractionSignal,
    SignalSeverity,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.expectations.signal_builder")


class ExtractionSignalBuilder:
    """Builds extraction signals from various subsystem outputs."""

    @staticmethod
    def from_budget_state(
        utilization: float,
        exceeded_axis: Optional[str] = None,
    ) -> ExtractionSignal:
        """Build a signal from budget utilization state."""
        if utilization < 0.5:
            severity = SignalSeverity.INFO
        elif utilization < 0.8:
            severity = SignalSeverity.MEDIUM
        else:
            severity = SignalSeverity.HIGH

        return ExtractionSignal(
            name="budget_pressure",
            value=utilization,
            severity=severity,
            source="budget_engine",
            evidence={
                "utilization": round(utilization, 3),
                "exceeded_axis": exceeded_axis,
            },
        )

    @staticmethod
    def from_fraud_crossover(
        fraud_verdict: str,
        fraud_score: float,
        relevant_signals: list[str],
    ) -> ExtractionSignal:
        """
        Build a cross-signal from the fraud engine.

        Reuses velocity, device churn, and automation indicators
        from fraud without duplicating their logic.
        """
        if fraud_score < 30:
            value = 0.0
        elif fraud_score < 60:
            value = (fraud_score - 30) / 60.0
        else:
            value = min(fraud_score / 100.0, 1.0)

        return ExtractionSignal(
            name="fraud_crossover_signal",
            value=value,
            severity=SignalSeverity.HIGH if value > 0.5 else SignalSeverity.MEDIUM,
            source="fraud_engine",
            evidence={
                "fraud_verdict": fraud_verdict,
                "fraud_score": round(fraud_score, 2),
                "relevant_signals": relevant_signals[:5],
            },
        )

    @staticmethod
    def from_canary_detection(
        canary_id: str,
        match_distance: float,
    ) -> ExtractionSignal:
        """Build a signal from canary input detection."""
        return ExtractionSignal(
            name="canary_hit_signal",
            value=1.0,
            severity=SignalSeverity.CRITICAL,
            source="canary_service",
            evidence={
                "canary_id": canary_id,
                "match_distance": round(match_distance, 4),
            },
        )

    @staticmethod
    def from_graph_cluster(
        cluster_id: str,
        cluster_query_rate: float,
        cluster_model_spread: int,
    ) -> ExtractionSignal:
        """Build a signal from graph cluster behavior analysis."""
        # High cluster-wide query rate with broad model spread
        rate_factor = min(cluster_query_rate / 100.0, 1.0)
        spread_factor = min(cluster_model_spread / 5.0, 1.0)
        value = (rate_factor + spread_factor) / 2.0

        return ExtractionSignal(
            name="cluster_rate_deviation",
            value=min(value, 1.0),
            severity=SignalSeverity.HIGH if value > 0.5 else SignalSeverity.MEDIUM,
            source="graph_baseline",
            evidence={
                "cluster_id": cluster_id,
                "cluster_query_rate": round(cluster_query_rate, 1),
                "cluster_model_spread": cluster_model_spread,
            },
        )
