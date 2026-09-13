"""Profile 360 ↔ Suggestion adapter."""

from __future__ import annotations

from typing import List

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.profile360")

# Staleness threshold in days before generating a suggestion
_STALENESS_DAYS_THRESHOLD = 30
_LTV_OPPORTUNITY_THRESHOLD = 0.6
_CHURN_RISK_THRESHOLD = 0.65


def create_suggestion_from_profile_state(
    profile: dict,
    tenant_id: str,
) -> List[SuggestionCreate]:
    """Analyze a Profile 360 snapshot and return 0–N suggestions.

    Generates suggestions for:
    - Stale profiles (last seen > 30d)
    - Churn risk (churn_score >= 0.65)
    - LTV opportunity (ltv_score >= 0.60)
    """
    suggestions: List[SuggestionCreate] = []
    entity_id = profile.get("entity_id") or profile.get("id", "unknown")
    display_name = profile.get("display_name")

    # Check staleness
    last_seen = profile.get("last_seen_at") or profile.get("last_seen")
    if last_seen:
        try:
            from datetime import datetime, timezone
            last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days_silent = (now - last_dt).days
            if days_silent >= _STALENESS_DAYS_THRESHOLD:
                suggestions.append(SuggestionCreate(
                    tenant_id=tenant_id,
                    subject=SuggestionSubject(
                        kind="profile", id=entity_id, display_name=display_name
                    ),
                    source=SuggestionSource.PROFILE360,
                    source_ref={"service": "profile360", "id": f"stale:{entity_id}"},
                    suggestion_class=SuggestionClass.CUSTOMER_SUCCESS,
                    title=f"Stale profile: {days_silent}d inactive",
                    summary=f"Entity {entity_id[:24]!r} has not been seen for {days_silent} days.",
                    what=f"Profile for {entity_id[:24]!r} has no activity for {days_silent} days.",
                    why="Inactive entities may represent churn risk or data quality issues.",
                    impact="Stale profiles reduce intelligence accuracy and may indicate lost customers.",
                    recommended_action="Re-engage via a targeted campaign or verify the entity is still active.",
                    confidence_score=0.75,
                    urgency_score=min(1.0, days_silent / 90.0),
                    risk_score=0.2,
                    reversible=True,
                    evidence=[{
                        "id": f"stale:{entity_id}",
                        "type": "entity",
                        "source": "profile360",
                        "observedAt": utc_now().isoformat(),
                    }],
                ))
        except Exception:
            pass

    # Check churn risk
    churn_score = profile.get("churn_score") or profile.get("churn_risk_score")
    if churn_score is not None and float(churn_score) >= _CHURN_RISK_THRESHOLD:
        suggestions.append(SuggestionCreate(
            tenant_id=tenant_id,
            subject=SuggestionSubject(
                kind="profile", id=entity_id, display_name=display_name
            ),
            source=SuggestionSource.PROFILE360,
            source_ref={"service": "profile360", "id": f"churn:{entity_id}"},
            suggestion_class=SuggestionClass.CUSTOMER_SUCCESS,
            title=f"Churn risk detected: score {float(churn_score):.0%}",
            summary=f"Entity {entity_id[:24]!r} has a churn risk score of {float(churn_score):.0%}.",
            what=f"Profile analysis indicates {float(churn_score):.0%} churn probability.",
            why="Behavioral patterns suggest declining engagement.",
            impact="High-risk churn entities represent revenue loss if not re-engaged.",
            recommended_action="Trigger a retention campaign or customer success outreach.",
            confidence_score=0.80,
            urgency_score=float(churn_score),
            risk_score=0.25,
            reversible=True,
            evidence=[{
                "id": f"churn:{entity_id}",
                "type": "model_output",
                "source": "profile360",
                "observedAt": utc_now().isoformat(),
                "confidence": 0.80,
            }],
        ))

    # Check LTV opportunity
    ltv_score = profile.get("ltv_opportunity_score") or profile.get("ltv_score")
    if ltv_score is not None and float(ltv_score) >= _LTV_OPPORTUNITY_THRESHOLD:
        suggestions.append(SuggestionCreate(
            tenant_id=tenant_id,
            subject=SuggestionSubject(
                kind="profile", id=entity_id, display_name=display_name
            ),
            source=SuggestionSource.PROFILE360,
            source_ref={"service": "profile360", "id": f"ltv:{entity_id}"},
            suggestion_class=SuggestionClass.REVENUE,
            title=f"LTV opportunity: score {float(ltv_score):.0%}",
            summary=f"Entity {entity_id[:24]!r} shows a high LTV opportunity ({float(ltv_score):.0%}).",
            what="Profile analysis indicates this entity has high monetization potential.",
            why="Engagement patterns align with high-value customer profiles.",
            impact="Targeting this entity for premium offerings could increase revenue.",
            recommended_action="Enroll in a premium campaign or personalized upgrade path.",
            confidence_score=0.75,
            urgency_score=0.5,
            risk_score=0.1,
            reversible=True,
            evidence=[{
                "id": f"ltv:{entity_id}",
                "type": "model_output",
                "source": "profile360",
                "observedAt": utc_now().isoformat(),
                "confidence": 0.75,
            }],
        ))

    return suggestions
