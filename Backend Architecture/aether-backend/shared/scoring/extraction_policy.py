"""
Aether Shared — Extraction Policy Engine

Maps extraction risk assessments to concrete enforcement actions.
Acts through access control and disclosure minimization — NOT through
user-visible perturbation or noisy responses.

Policy Matrix:
    GREEN  → normal prediction, rounded confidence, suppress auxiliary
    YELLOW → tighter budgets, bucketed confidence, no multi-score
    ORANGE → heavily reduced disclosure, no batch, narrower model access
    RED    → deny, quarantine actor/cluster, escalate alert
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.scoring.extraction_models import (
    ConfidenceMode,
    ExtractionIdentity,
    ExtractionRiskAssessment,
    ExtractionRiskBand,
    ModelSensitivityTier,
    OutputDisclosurePolicy,
    get_model_tier,
)

logger = get_logger("aether.scoring.extraction_policy")


# ═══════════════════════════════════════════════════════════════════════════
# POLICY DECISION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PolicyDecision:
    """Concrete actions to enforce based on extraction risk."""
    action: str                          # "allow", "reduce_disclosure", "restrict", "deny"
    disclosure: OutputDisclosurePolicy
    should_alert: bool = False
    should_quarantine: bool = False
    analyst_review: bool = False
    reasons: list[str] = None

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "should_alert": self.should_alert,
            "should_quarantine": self.should_quarantine,
            "analyst_review": self.analyst_review,
            "disclosure": {
                "confidence_mode": self.disclosure.confidence_mode.value,
                "allow_exact_scores": self.disclosure.allow_exact_scores,
                "include_secondary_scores": self.disclosure.include_secondary_scores,
                "include_probabilities": self.disclosure.include_probabilities,
                "batch_allowed": self.disclosure.batch_allowed,
                "max_batch_rows": self.disclosure.max_batch_rows,
            },
            "reasons": self.reasons,
        }


# ═══════════════════════════════════════════════════════════════════════════
# DISCLOSURE POLICIES PER BAND
# ═══════════════════════════════════════════════════════════════════════════

# Green — normal, but still minimize extractable signal
GREEN_DISCLOSURE = OutputDisclosurePolicy(
    allow_exact_scores=False,
    confidence_mode=ConfidenceMode.ROUNDED,
    output_precision=2,
    include_secondary_scores=True,
    include_probabilities=True,
    batch_allowed=False,        # Batch is always internal-only
    max_batch_rows=0,
    suppress_feature_importance=False,
)

# Yellow — tighter disclosure
YELLOW_DISCLOSURE = OutputDisclosurePolicy(
    allow_exact_scores=False,
    confidence_mode=ConfidenceMode.BUCKETED,
    output_precision=1,
    include_secondary_scores=False,
    include_probabilities=True,
    batch_allowed=False,
    max_batch_rows=0,
    suppress_feature_importance=True,
)

# Orange — heavily restricted
ORANGE_DISCLOSURE = OutputDisclosurePolicy(
    allow_exact_scores=False,
    confidence_mode=ConfidenceMode.BUCKETED,
    output_precision=1,
    include_secondary_scores=False,
    include_probabilities=False,
    batch_allowed=False,
    max_batch_rows=0,
    suppress_feature_importance=True,
)

# Red — deny (disclosure policy is moot, request is blocked)
RED_DISCLOSURE = OutputDisclosurePolicy(
    allow_exact_scores=False,
    confidence_mode=ConfidenceMode.HIDDEN,
    output_precision=0,
    include_secondary_scores=False,
    include_probabilities=False,
    batch_allowed=False,
    max_batch_rows=0,
    suppress_feature_importance=True,
)

# Privileged — internal/service callers get exact scores
PRIVILEGED_DISCLOSURE = OutputDisclosurePolicy(
    allow_exact_scores=True,
    confidence_mode=ConfidenceMode.EXACT,
    output_precision=4,
    include_secondary_scores=True,
    include_probabilities=True,
    batch_allowed=True,
    max_batch_rows=10000,
    suppress_feature_importance=False,
)


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION POLICY ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionPolicyEngine:
    """
    Maps extraction risk to enforcement actions.

    No user-visible perturbation. Actions are:
    - Disclosure minimization (rounding, bucketing, suppression)
    - Access control (budget tightening, batch denial)
    - Operational (alerts, analyst review, quarantine)
    """

    def __init__(
        self,
        privileged_tenants: Optional[set[str]] = None,
        privileged_api_keys: Optional[set[str]] = None,
    ) -> None:
        self._privileged_tenants = privileged_tenants or set()
        self._privileged_api_keys = privileged_api_keys or set()

    def evaluate(
        self,
        assessment: ExtractionRiskAssessment,
        model_name: str = "",
        is_batch: bool = False,
        caller_is_service: bool = False,
    ) -> PolicyDecision:
        """
        Evaluate extraction risk and return a policy decision.

        Args:
            assessment: The extraction risk assessment.
            model_name: Target model name.
            is_batch: Whether this is a batch prediction request.
            caller_is_service: Whether the caller is an internal service.

        Returns:
            PolicyDecision with concrete enforcement actions.
        """
        identity = assessment.identity
        tier = get_model_tier(model_name)
        band = assessment.band

        # ── Privileged callers bypass disclosure restrictions ─────────
        if caller_is_service or self._is_privileged(identity):
            return PolicyDecision(
                action="allow",
                disclosure=PRIVILEGED_DISCLOSURE,
                reasons=["privileged_caller"],
            )

        # ── Batch is always internal-only for non-privileged ─────────
        if is_batch:
            return PolicyDecision(
                action="deny",
                disclosure=RED_DISCLOSURE,
                reasons=["batch_internal_only"],
            )

        # ── Apply band-based policy ──────────────────────────────────
        if band == ExtractionRiskBand.RED:
            decision = PolicyDecision(
                action="deny",
                disclosure=RED_DISCLOSURE,
                should_alert=True,
                should_quarantine=True,
                analyst_review=True,
                reasons=assessment.reasons,
            )

        elif band == ExtractionRiskBand.ORANGE:
            if tier == ModelSensitivityTier.TIER_1_CRITICAL:
                decision = PolicyDecision(
                    action="deny",
                    disclosure=RED_DISCLOSURE,
                    should_alert=True,
                    analyst_review=True,
                    reasons=assessment.reasons + ["tier_1_orange_escalation"],
                )
            else:
                decision = PolicyDecision(
                    action="restrict",
                    disclosure=ORANGE_DISCLOSURE,
                    should_alert=True,
                    analyst_review=True,
                    reasons=assessment.reasons,
                )

        elif band == ExtractionRiskBand.YELLOW:
            if tier == ModelSensitivityTier.TIER_1_CRITICAL:
                decision = PolicyDecision(
                    action="reduce_disclosure",
                    disclosure=ORANGE_DISCLOSURE,
                    should_alert=False,
                    analyst_review=True,
                    reasons=assessment.reasons + ["tier_1_yellow_tightened"],
                )
            else:
                decision = PolicyDecision(
                    action="reduce_disclosure",
                    disclosure=YELLOW_DISCLOSURE,
                    reasons=assessment.reasons,
                )

        else:  # GREEN
            decision = PolicyDecision(
                action="allow",
                disclosure=GREEN_DISCLOSURE,
            )

        metrics.increment(
            "extraction_policy_applied",
            labels={"action": decision.action, "band": band.value, "tier": tier.value},
        )

        if decision.should_alert:
            logger.warning(
                "Extraction policy: action=%s band=%s tier=%s model=%s",
                decision.action, band.value, tier.value, model_name,
            )

        return decision

    def _is_privileged(self, identity: Optional[ExtractionIdentity]) -> bool:
        """Check if the caller is on the privileged allowlist."""
        if identity is None:
            return False
        if identity.tenant_id and identity.tenant_id in self._privileged_tenants:
            return True
        if identity.api_key_id and identity.api_key_id in self._privileged_api_keys:
            return True
        return False
