"""OODA suggestion generation from targeting intelligence findings.

Suggestions are governed proposals with the full evidence chain
(intent → snapshot → observation → outcome) attached. Poor provider mapping
quality BLOCKS generation entirely rather than lowering confidence.
"""

from __future__ import annotations

from typing import Optional

from config.settings import settings
from shared.logger.logger import get_logger, metrics

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)
from services.targeting_intelligence.models import (
    ExclusionLeakageFinding,
    ProviderMappingQuality,
)

logger = get_logger("aether.targeting.suggestions")

# Leakage severities that warrant a suggestion.
_SUGGEST_SEVERITIES = {"medium", "high", "critical"}
_SEVERITY_URGENCY = {"medium": 0.5, "high": 0.75, "critical": 0.95}


def _chain_evidence(finding: ExclusionLeakageFinding) -> list[dict]:
    evidence = [ref.model_dump(mode="json") for ref in finding.evidenceRefs]
    evidence.append({
        "id": finding.findingId, "type": "annotation",
        "source": "exclusion_leakage_finding", "observedAt": finding.computedAt,
    })
    return evidence


def suggestions_enabled() -> bool:
    flags = settings.targeting_intelligence
    return bool(flags.enabled and flags.ooda_suggestions_enabled)


def leakage_suggestion(
    finding: ExclusionLeakageFinding,
    quality: Optional[ProviderMappingQuality] = None,
) -> Optional[SuggestionCreate]:
    """Governed proposal for a leakage finding; None when blocked/ineligible."""
    if not suggestions_enabled():
        return None
    if finding.severity not in _SUGGEST_SEVERITIES:
        return None
    if quality is not None and quality.blocksSuggestions:
        metrics.increment("targeting_suggestion_blocked_quality_total")
        logger.info(
            "Targeting suggestion blocked by mapping quality %.2f (%s)",
            quality.qualityScore, finding.campaignId,
        )
        return None

    causes = ", ".join(finding.likelyCauses)
    return SuggestionCreate(
        tenant_id=finding.tenantId,
        subject=SuggestionSubject(
            kind="campaign", id=finding.campaignId,
            display_name=f"Campaign {finding.campaignId[:16]}",
        ),
        source=SuggestionSource.RULE,
        source_ref={"service": "targeting_intelligence",
                    "id": f"leakage:{finding.findingId}"},
        suggestion_class=SuggestionClass.RETARGETING,
        title=f"Exclusion leakage observed in cluster {finding.clusterId[:24]}",
        summary=(
            f"Cluster {finding.clusterId[:24]} was excluded but "
            f"{finding.reachedEntityCount} reach event(s) were observed "
            f"(leakage rate {finding.leakageRate:.0%}, severity {finding.severity})."
        ),
        what=(
            f"The eligibility snapshot excluded cluster {finding.clusterId} "
            f"({finding.reasonCode}), yet the targeting observation recorded "
            f"{finding.reachedEntityCount} reached entit(ies) against "
            f"{finding.excludedEntityCount} member(s)."
        ),
        why=f"Observed leakage correlates with: {causes}. This is observational — "
            "verify inside your campaign platform before acting.",
        impact="Excluded audiences receiving campaign exposure can violate "
               "tenant policy, waste spend, and contaminate holdout measurement.",
        recommended_action=(
            "Re-apply the exclusion lists in your external campaign platform "
            "(export an implementation package from Aether), then recompute the "
            "eligibility snapshot to confirm the leak is closed."
        ),
        confidence_score=min(0.95, 0.5 + finding.leakageRate / 2),
        urgency_score=_SEVERITY_URGENCY[finding.severity],
        risk_score=0.2,
        reversible=True,
        evidence=_chain_evidence(finding),
    )


def overexposure_suggestion(
    tenant_id: str, campaign_id: str, cluster_id: str, score: float,
    evidence: list[dict],
    quality: Optional[ProviderMappingQuality] = None,
) -> Optional[SuggestionCreate]:
    if not suggestions_enabled():
        return None
    if quality is not None and quality.blocksSuggestions:
        metrics.increment("targeting_suggestion_blocked_quality_total")
        return None
    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="campaign", id=campaign_id,
                                  display_name=f"Campaign {campaign_id[:16]}"),
        source=SuggestionSource.RULE,
        source_ref={"service": "targeting_intelligence",
                    "id": f"overexposure:{campaign_id}:{cluster_id}"},
        suggestion_class=SuggestionClass.RETARGETING,
        title=f"Overexposure observed in cluster {cluster_id[:24]}",
        summary=(
            f"Cluster {cluster_id[:24]} shows an overexposure score of "
            f"{score:.0%} in the observation window."
        ),
        what=f"Entities in cluster {cluster_id} were touched well beyond the "
             "frequency threshold during this campaign window.",
        why="Sustained overexposure correlates with unsubscribes, complaints, "
            "and churn signals.",
        impact="Continued exposure risks negative outcomes in this cluster.",
        recommended_action=(
            "Consider adding this cluster to a frequency-capped or excluded "
            "audience in your external platform; export an implementation "
            "package from Aether if you adopt the change."
        ),
        confidence_score=min(0.9, score),
        urgency_score=score,
        risk_score=0.15,
        reversible=True,
        evidence=evidence,
    )
