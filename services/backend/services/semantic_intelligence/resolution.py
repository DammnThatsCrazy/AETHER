"""Subject and actor resolution for semantic observations.

Backend-owned resolution: SDKs never assign canonical entity identity. The
resolver walks a fixed precedence order, validates cross-tenant references
FAIL-CLOSED (a subject/campaign belonging to another tenant is rejected, never
classified against), and routes low-confidence / ambiguous / cross-tenant cases
to the durable review queue. The model never invents canonical identity — an
unresolved subject stays ``unknown_subject``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from repositories.repos import CampaignRepository, EntityRepository

from .models import SubjectType

# Below this confidence a resolution enters the review queue instead of asserting
# a canonical subject. Mirrors settings.semantic.subject_confidence_threshold.
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# Event properties that carry the subject, in precedence order, with their type.
_SUBJECT_PROPERTY_TYPES: tuple[tuple[str, SubjectType], ...] = (
    ("product_id", SubjectType.PRODUCT),
    ("cart_id", SubjectType.TRANSACTION),
    ("content_id", SubjectType.CREATIVE),
    ("offer_id", SubjectType.OFFER),
    ("agent_id", SubjectType.AGENT),
    ("wallet_id", SubjectType.WALLET),
    ("campaign_id", SubjectType.CAMPAIGN),
)


@dataclass(frozen=True)
class ResolvedRef:
    ref: str
    type: SubjectType
    confidence: float
    method: str
    needs_review: bool = False
    review_queue: Optional[str] = None


class SemanticSubjectResolver:
    """Resolve the primary semantic subject with cross-tenant safety."""

    def __init__(self, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> None:
        self._threshold = threshold
        self._entities = EntityRepository()
        self._campaigns = CampaignRepository()

    async def resolve(self, payload: dict[str, Any], tenant_id: str) -> ResolvedRef:
        props = payload.get("properties") or {}
        explicit = (
            payload.get("primary_subject_ref")
            or payload.get("subject_ref")
            or payload.get("target_ref")
        )

        # Any candidate that resolves to a DIFFERENT tenant is rejected outright.
        candidates = [explicit, payload.get("campaign_id"), props.get("campaign_id")]
        for candidate in candidates:
            if candidate and await self._belongs_to_other_tenant(str(candidate), tenant_id):
                return ResolvedRef(
                    "unknown_subject",
                    SubjectType.OTHER,
                    0.0,
                    "cross_tenant_rejected",
                    needs_review=True,
                    review_queue="cross_tenant_reference",
                )

        if explicit and str(explicit) != "unknown_subject":
            return ResolvedRef(str(explicit), _infer_type(payload), 0.95, "explicit_ref")

        for key, subject_type in _SUBJECT_PROPERTY_TYPES:
            value = payload.get(key) or props.get(key)
            if value:
                confidence = 0.6
                return ResolvedRef(
                    str(value),
                    subject_type,
                    confidence,
                    f"property:{key}",
                    needs_review=confidence < self._threshold,
                    review_queue="ambiguous_subject" if confidence < self._threshold else None,
                )

        return ResolvedRef(
            "unknown_subject",
            SubjectType.OTHER,
            0.0,
            "unresolved",
            needs_review=True,
            review_queue="ambiguous_subject",
        )

    async def _belongs_to_other_tenant(self, ref: str, tenant_id: str) -> bool:
        for repo in (self._entities, self._campaigns):
            try:
                record = await repo.find_by_id(ref)
            except Exception:
                record = None
            if record:
                owner = record.get("tenant_id")
                if owner not in (None, "", tenant_id):
                    return True
        return False


class SemanticActorResolver:
    """Resolve the actor, preserving the original reference and identity signals."""

    async def resolve(self, payload: dict[str, Any], tenant_id: str) -> ResolvedRef:
        user_id = payload.get("user_id")
        if user_id:
            return ResolvedRef(str(user_id), SubjectType.PROFILE, 0.9, "user_id")
        anon = payload.get("anonymous_id")
        if anon:
            return ResolvedRef(str(anon), SubjectType.PROFILE, 0.5, "anonymous_id")
        agent_id = payload.get("agent_id") or (payload.get("properties") or {}).get("agent_id")
        if agent_id:
            return ResolvedRef(str(agent_id), SubjectType.AGENT, 0.8, "agent_id")
        return ResolvedRef("anonymous", SubjectType.PROFILE, 0.2, "unresolved_actor")


def _infer_type(payload: dict[str, Any]) -> SubjectType:
    raw = payload.get("target_type") or payload.get("subject_type")
    if raw and raw in SubjectType._value2member_map_:
        return SubjectType(raw)
    return SubjectType.OTHER
