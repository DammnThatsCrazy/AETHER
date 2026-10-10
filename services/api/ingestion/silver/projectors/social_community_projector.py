"""Social Silver projector — social community membership facts.

Projects Bronze events of type ``social_community_membership_observed`` into
``silver_social_community_facts``: a social identity's membership in (or role
within) a community / group / server on a provider platform.

Table (integrator DDL): columns = BaseProjector._base_row columns + provenance
columns + the domain columns below. UNIQUE on ``(tenant_id, idempotency_key)``.

``membership_role`` defaults to the honest ``unknown`` member when the provider
record carries no mappable role; the provider-native role string is preserved in
``provider_membership_role`` so the mapping stays explainable.

Record contract (properties, snake_case; single object or ``records`` list):
    social_identity_ref   the member (required)
    community_ref         the community / group / server (required)
    membership_role       canonical or provider-native (see _MEMBERSHIP_ROLE)
    valid_from / valid_to / observed_at
    provider_record_id / evidence_refs
"""

from __future__ import annotations

from typing import Any

from .social_base import SocialFactProjector
from .social_common import as_list, as_str

SOCIAL_COMMUNITY_TABLE = "silver_social_community_facts"
SOCIAL_COMMUNITY_TYPES = frozenset({"social_community_membership_observed"})

_MEMBERSHIP_ROLE = {
    # canonical passthrough
    "member": "member",
    "subscriber": "subscriber",
    "moderator": "moderator",
    "administrator": "administrator",
    "contributor": "contributor",
    "founder": "founder",
    "unknown": "unknown",
    # provider-native aliases
    "admin": "administrator",
    "mod": "moderator",
    "owner": "founder",
    "creator": "founder",
    "moderating": "moderator",
}

_VALID_ROLES = frozenset(_MEMBERSHIP_ROLE.values())


def _canonical_ref(provider_identity: str | None, value: Any) -> str | None:
    text = as_str(value)
    if not text:
        return None
    if ":" in text:
        return text
    if provider_identity:
        return f"{provider_identity}:{text}"
    return text


class SocialCommunityMembershipProjector(SocialFactProjector):
    """Deterministic community-membership normalization into silver_social_community_facts."""

    handles = SOCIAL_COMMUNITY_TYPES
    table = SOCIAL_COMMUNITY_TABLE
    fact_kind = "social_community_membership"

    def build_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any] | None:
        provider_identity = self._provider_family(event, record)
        social_identity_ref = _canonical_ref(
            provider_identity, record.get("social_identity_ref")
        )
        community_ref = _canonical_ref(
            provider_identity, record.get("community_ref") or record.get("community_id")
        )
        if not social_identity_ref or not community_ref:
            return None

        raw_role = str(record.get("membership_role") or "").lower()
        membership_role = _MEMBERSHIP_ROLE.get(raw_role, "unknown")

        row = self._base_social_row(event, record)
        membership_id = as_str(record.get("membership_id")) or (
            f"{provider_identity}:{social_identity_ref}:{community_ref}"
            if provider_identity
            else f"{social_identity_ref}:{community_ref}"
        )
        observed_at = (
            as_str(record.get("observed_at")) or as_str(event.get("timestamp")) or None
        )

        row.update({
            "membership_id": membership_id,
            "social_identity_ref": social_identity_ref,
            "community_ref": community_ref,
            "membership_role": membership_role,
            # preserved so an unmapped role stays explainable.
            "provider_membership_role": (
                raw_role if raw_role and raw_role not in _VALID_ROLES else None
            ),
            "valid_from": as_str(record.get("valid_from")) or observed_at,
            "valid_to": as_str(record.get("valid_to")),
            "observed_at": observed_at,
            "provider_record_ref": row.get("provider_record_ref")
            or str(row.get("source_event_id") or ""),
            "evidence_refs": as_list(record.get("evidence_refs")),
        })
        return row
