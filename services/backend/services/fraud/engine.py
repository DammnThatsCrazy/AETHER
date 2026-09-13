"""
Aether Backend — Fraud Detection Engine

Composable, weighted fraud scoring engine.  Evaluates events against multiple
independent signals and produces a composite fraud score (0-100).

Design principles:
    - Each signal is independent and testable.
    - Weights are configurable per-tenant.
    - Scores are deterministic for the same input.
    - Results are fully auditable.

Integration:
    Instantiated by ``services.fraud.routes`` and called from the
    ``/v1/fraud/evaluate`` endpoint.  Also consumed by the reward-eligibility
    pipeline in ``services.rewards``.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from services.fraud.signals import (
    BehavioralSignal,
    BotDetectionSignal,
    DeviceFingerprintSignal,
    FraudSignal,
    GeographicSignal,
    SignalResult,
    SybilDetectionSignal,
    TransactionPatternSignal,
    VelocitySignal,
    WalletAgeSignal,
)

logger = logging.getLogger("aether.fraud.engine")


# ========================================================================
# CONFIGURATION
# ========================================================================

@dataclass
class FraudConfig:
    """Tenant-configurable thresholds and feature flags."""

    block_threshold: float = 70.0
    flag_threshold: float = 40.0
    enable_audit_trail: bool = True
    max_evaluation_ms: int = 500
    custom_weights: dict[str, float] = field(default_factory=dict)


# ========================================================================
# RESULT
# ========================================================================

@dataclass
class FraudResult:
    """Complete output of a fraud evaluation."""

    audit_id: str
    composite_score: float
    verdict: str                          # "pass" | "flag" | "block"
    signals: list[SignalResult]
    evaluation_ms: float
    timestamp: str
    config_snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "composite_score": round(self.composite_score, 4),
            "verdict": self.verdict,
            "signals": [
                {
                    "name": s.name,
                    "score": round(s.score, 4),
                    "weight": s.weight,
                    "triggered": s.triggered,
                    "details": s.details,
                }
                for s in self.signals
            ],
            "evaluation_ms": round(self.evaluation_ms, 2),
            "timestamp": self.timestamp,
        }


# ========================================================================
# DEFAULT SIGNAL SET
# ========================================================================

DEFAULT_SIGNALS: list[FraudSignal] = [
    BotDetectionSignal(),
    SybilDetectionSignal(),
    VelocitySignal(),
    WalletAgeSignal(),
    GeographicSignal(),
    BehavioralSignal(),
    DeviceFingerprintSignal(),
    TransactionPatternSignal(),
]


# ========================================================================
# ENGINE
# ========================================================================

class FraudEngine:
    """
    Runs all registered fraud signals concurrently and computes a
    weighted composite score.

    Usage::

        engine = FraudEngine(FraudConfig(block_threshold=75))
        result = await engine.evaluate(event_dict, context_dict)
        if result.verdict == "block":
            ...
    """

    def __init__(self, config: Optional[FraudConfig] = None) -> None:
        self.config = config or FraudConfig()
        self._signals: list[FraudSignal] = []
        self._register_defaults()

    # -- signal management ------------------------------------------------

    def _register_defaults(self) -> None:
        """Populate with the default signal set, applying any custom weights."""
        for signal in DEFAULT_SIGNALS:
            clone = copy.deepcopy(signal)
            if clone.name in self.config.custom_weights:
                clone.weight = self.config.custom_weights[clone.name]
            self._signals.append(clone)

    def add_signal(self, signal: FraudSignal) -> None:
        """Register a custom signal (appends to existing set)."""
        if signal.name in self.config.custom_weights:
            signal.weight = self.config.custom_weights[signal.name]
        self._signals.append(signal)
        logger.info("Custom signal registered: %s (weight=%.2f)", signal.name, signal.weight)

    def list_signals(self) -> list[str]:
        """Return the names of all registered signals."""
        return [s.name for s in self._signals]

    # -- evaluation -------------------------------------------------------

    async def evaluate(self, event: dict, context: dict) -> FraudResult:
        """
        Evaluate an event against all registered signals concurrently.

        Returns a ``FraudResult`` with the weighted composite score,
        a verdict string, and the full audit trail.
        """
        start = time.monotonic()
        audit_id = f"fra_{uuid4().hex[:16]}"

        # Run all signals concurrently
        results: list[SignalResult] = await asyncio.gather(
            *(signal.evaluate(event, context) for signal in self._signals),
        )

        # Compute weighted composite ----------------------------------------
        total_weight = sum(r.weight for r in results) or 1.0
        composite = sum(r.score * r.weight for r in results) / total_weight

        # Determine verdict --------------------------------------------------
        if composite >= self.config.block_threshold:
            verdict = "block"
        elif composite >= self.config.flag_threshold:
            verdict = "flag"
        else:
            verdict = "pass"

        elapsed_ms = (time.monotonic() - start) * 1000.0

        logger.info(
            "Fraud evaluation complete: audit_id=%s score=%.2f verdict=%s elapsed=%.1fms",
            audit_id, composite, verdict, elapsed_ms,
        )

        return FraudResult(
            audit_id=audit_id,
            composite_score=composite,
            verdict=verdict,
            signals=results,
            evaluation_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            config_snapshot={
                "block_threshold": self.config.block_threshold,
                "flag_threshold": self.config.flag_threshold,
            },
        )
