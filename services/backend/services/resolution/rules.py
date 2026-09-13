"""
Aether Backend — Identity Resolution Rules Engine

Applies configurable thresholds to signal results and produces merge /
review / reject decisions.  Deterministic matches always auto-merge;
probabilistic matches use weighted composite scoring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ResolutionConfig:
    """Tenant-level thresholds for the resolution pipeline."""

    auto_merge_threshold: float = 0.95
    review_threshold: float = 0.70
    max_cluster_size: int = 50
    cooldown_hours: int = 24
    require_deterministic_for_auto: bool = True
    allow_probabilistic_auto_merge: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# DECISION OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ResolutionDecision:
    """Immutable record of a resolution evaluation."""

    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    profile_a_id: str = ""
    profile_b_id: str = ""
    action: str = ""             # auto_merge | flag_for_review | reject
    composite_confidence: float = 0.0
    deterministic_match: bool = False
    signals: list[Any] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# RULES ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class ResolutionRulesEngine:
    """Stateless decision-maker — pure function of config + signals."""

    def __init__(self, config: ResolutionConfig) -> None:
        self.config = config

    # ── public API ────────────────────────────────────────────────────

    def decide(
        self,
        profile_a_id: str,
        profile_b_id: str,
        signals: list[Any],
    ) -> ResolutionDecision:
        """Evaluate signal results and return a merge / review / reject decision."""

        has_deterministic = any(
            s.match_type == "deterministic" and s.is_match for s in signals
        )

        # ── Deterministic fast-path ──────────────────────────────────
        if has_deterministic:
            matched_name = next(
                s.name for s in signals
                if s.match_type == "deterministic" and s.is_match
            )
            return ResolutionDecision(
                profile_a_id=profile_a_id,
                profile_b_id=profile_b_id,
                action="auto_merge",
                composite_confidence=1.0,
                deterministic_match=True,
                signals=signals,
                reason=f"Deterministic match: {matched_name}",
            )

        # ── Probabilistic scoring ────────────────────────────────────
        prob_signals = [
            s for s in signals if s.match_type == "probabilistic"
        ]
        if not prob_signals:
            return ResolutionDecision(
                profile_a_id=profile_a_id,
                profile_b_id=profile_b_id,
                action="reject",
                composite_confidence=0.0,
                signals=signals,
                reason="No matching signals",
            )

        total_weight = sum(
            s.details.get("weight", 1.0 / len(prob_signals))
            for s in prob_signals
        )
        if total_weight == 0:
            total_weight = 1.0

        composite = sum(
            s.confidence * s.details.get("weight", 1.0 / len(prob_signals))
            for s in prob_signals
        ) / total_weight

        # ── Threshold evaluation ─────────────────────────────────────
        if (
            composite >= self.config.auto_merge_threshold
            and self.config.allow_probabilistic_auto_merge
        ):
            action = "auto_merge"
            reason = f"Probabilistic auto-merge (confidence={composite:.3f})"
        elif composite >= self.config.review_threshold:
            action = "flag_for_review"
            reason = f"Review needed (confidence={composite:.3f})"
        else:
            action = "reject"
            reason = f"Below threshold (confidence={composite:.3f})"

        return ResolutionDecision(
            profile_a_id=profile_a_id,
            profile_b_id=profile_b_id,
            action=action,
            composite_confidence=composite,
            deterministic_match=False,
            signals=signals,
            reason=reason,
        )
