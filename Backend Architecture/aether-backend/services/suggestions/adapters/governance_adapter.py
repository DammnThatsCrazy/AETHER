"""Governance ↔ Suggestion adapter."""

from __future__ import annotations

from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.governance")

# Number of consecutive policy denials before raising a P1 suggestion
_DENIAL_THRESHOLD = 3


def create_suggestion_from_policy_denial(
    decision: dict,
    tenant_id: str,
    denial_count: int = 1,
) -> Optional[SuggestionCreate]:
    """Create a security/governance suggestion from a policy denial event.

    Returns None for isolated single denials to reduce noise. Repeated
    denials (denial_count >= _DENIAL_THRESHOLD) produce a P1 suggestion.
    All governance suggestions require approval.
    """
    if denial_count < _DENIAL_THRESHOLD and not decision.get("is_critical", False):
        return None

    decision_id = decision.get("id", "")
    principal = decision.get("principal") or {}
    principal_id = principal.get("id") or decision.get("principal_id", "unknown")
    action = decision.get("action", "unknown")
    resource = decision.get("resource") or {}
    resource_id = resource.get("id") or decision.get("resource_id", "unknown")
    policies = decision.get("policies") or []

    priority_note = "repeated" if denial_count >= _DENIAL_THRESHOLD else "critical"

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(
            kind="entity",
            id=principal_id,
            display_name=principal.get("label"),
        ),
        source=SuggestionSource.GOVERNANCE,
        source_ref={"service": "governance", "id": decision_id},
        suggestion_class=SuggestionClass.SECURITY,
        title=f"Policy denial ({priority_note}): {action[:40]}",
        summary=(
            f"Principal {principal_id[:24]!r} has been denied {denial_count} time(s) "
            f"for action '{action[:40]}' on resource {resource_id[:24]!r}."
        ),
        what=(
            f"Action '{action}' on resource {resource_id!r} was denied "
            f"by policies: {', '.join(policies[:3])}."
        ),
        why=(
            f"{denial_count} policy denials in a short window may indicate "
            "misconfigured permissions, a compromised account, or attempted unauthorized access."
        ),
        impact="Repeated denials may indicate a security threat or a misconfiguration blocking legitimate operations.",
        recommended_action="Review permission policies and audit recent activity for this principal.",
        confidence_score=min(0.95, 0.6 + denial_count * 0.05),
        urgency_score=min(1.0, 0.5 + denial_count * 0.1),
        risk_score=0.75,
        reversible=False,
        evidence=[
            {
                "id": decision_id,
                "type": "event",
                "source": "governance",
                "observedAt": decision.get("evaluated_at") or utc_now().isoformat(),
                "confidence": 0.90,
            }
        ],
        lineage_event_ids=[decision_id] if decision_id else [],
    )
