"""AI Efficiency ↔ Suggestion adapter.

Maps deterministic AI efficiency detector findings (services/economic/
ai_efficiency.py) to OODA suggestions. Findings are governed proposals —
the suggestion recommends review, never an automatic change.

Reuses existing enum values (source=RULE, class=AGENT_OPERATIONS) so no
suggestion contract change is required.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.ai_efficiency")

_SEVERITY_TO_CONFIDENCE = {
    "high":   0.90,
    "medium": 0.75,
    "low":    0.60,
}

_SEVERITY_TO_URGENCY = {
    "high":   0.8,
    "medium": 0.5,
    "low":    0.3,
}

_MAX_EVIDENCE_ITEMS = 10


def _finding_ref(finding: dict[str, Any]) -> str:
    """Stable idempotency reference for a finding."""
    detector = finding.get("detector", "unknown")
    refs = ",".join(sorted(finding.get("evidence_refs") or []))
    digest = hashlib.sha256(f"{detector}|{refs}".encode("utf-8")).hexdigest()[:16]
    return f"ai_eff:{detector}:{digest}"


def _format_waste(waste: Optional[dict[str, float]]) -> str:
    if not waste:
        return "unquantified"
    return ", ".join(f"{amount:.4f} {currency}" for currency, amount in sorted(waste.items()))


def create_suggestion_from_ai_efficiency_finding(
    finding: dict[str, Any],
) -> Optional[SuggestionCreate]:
    """Map one AI efficiency detector finding to a SuggestionCreate.

    Returns None for malformed findings (missing tenant or detector).
    """
    tenant_id = finding.get("tenant_id") or ""
    detector = finding.get("detector") or ""
    if not tenant_id or not detector:
        return None

    severity = str(finding.get("severity", "low")).lower()
    confidence = _SEVERITY_TO_CONFIDENCE.get(severity, 0.60)
    urgency = _SEVERITY_TO_URGENCY.get(severity, 0.3)
    waste = finding.get("estimated_monthly_waste")
    evidence_refs = list(finding.get("evidence_refs") or [])
    observed_at = utc_now().isoformat()

    title = str(finding.get("title") or f"AI efficiency: {detector}")[:200]
    description = str(finding.get("description") or title)
    candidate_action = str(
        finding.get("candidate_action")
        or "Review the flagged invocations and decide on a governed follow-up."
    )

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(
            kind="tenant", id=tenant_id, display_name=f"AI spend — {detector}"
        ),
        source=SuggestionSource.RULE,
        source_ref={"service": "ai_efficiency", "id": _finding_ref(finding)},
        suggestion_class=SuggestionClass.AGENT_OPERATIONS,
        title=title,
        summary=(
            f"{detector} finding with estimated monthly waste {_format_waste(waste)}."
        )[:500],
        what=description[:2000],
        why=(
            "Deterministic AI efficiency detectors flagged this pattern from AI "
            "execution facts (usage, cost, latency, quality) — no prompt or "
            "completion content is inspected."
        ),
        impact=(
            f"Estimated monthly waste: {_format_waste(waste)}. "
            "Cost efficiency degrades AI outcome economics until addressed."
        )[:2000],
        recommended_action=candidate_action[:2000],
        confidence_score=confidence,
        urgency_score=urgency,
        risk_score=0.2,  # proposal-only; acting on it still requires approval
        reversible=True,
        evidence=[
            {
                "id": f"ai_invocation:{ref}",
                "type": "event",
                "source": "ai_execution_facts",
                "observedAt": observed_at,
                "confidence": confidence,
                "uri": f"aether://economic/ai/invocations/{ref}",
            }
            for ref in evidence_refs[:_MAX_EVIDENCE_ITEMS]
        ],
        lineage_event_ids=[],
    )


def create_suggestions_from_findings(
    findings: list[dict[str, Any]],
) -> list[SuggestionCreate]:
    """Map a batch of detector findings, dropping malformed entries."""
    suggestions: list[SuggestionCreate] = []
    for finding in findings:
        try:
            suggestion = create_suggestion_from_ai_efficiency_finding(finding)
        except Exception as exc:  # noqa: BLE001 — one bad finding never drops the batch
            logger.warning("ai_efficiency suggestion mapping failed: %s", exc)
            continue
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions
