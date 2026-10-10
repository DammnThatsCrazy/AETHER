"""Social Silver projector — social identity facts.

Projects Bronze events of type ``social_identity_observed`` into
``silver_social_identity_facts``: the canonical account/profile record of a
social identity as observed on a provider platform.

Table (integrator DDL): columns = BaseProjector._base_row columns + provenance
(``source_scope`` / ``evidence_basis`` / ``rights_ref`` /
``provider_identity`` / ``provider_record_ref``) + the domain columns below.
UNIQUE on ``(tenant_id, idempotency_key)``.

A SocialIdentity is NOT automatically a canonical Human: identity resolution is a
separate domain. ``canonical_entity_ref`` is only recorded when upstream already
supplied a resolved binding — never guessed here.

Record contract (properties, snake_case; single object or ``records`` list):
    provider_account_id      provider account id (required)
    handle, display_name/name, canonical_url
    account_type             provider-native or canonical (see _ACCOUNT_TYPE)
    verification_state       provider-native or canonical (see _VERIFICATION)
    platform_role            free provider role string
    created_at               provider profile-created ISO-8601
    first_observed_at / last_observed_at / valid_from / valid_to
    canonical_entity_ref     resolved canonical entity binding (upstream only)
"""

from __future__ import annotations

from typing import Any

from .base import BaseProjector, ProjectionResult
from .social_base import SocialFactProjector
from .social_common import as_list, as_str

SOCIAL_IDENTITY_TABLE = "silver_social_identity_facts"
SOCIAL_IDENTITY_TYPES = frozenset({"social_identity_observed"})

_ACCOUNT_TYPE = {
    # canonical passthrough
    "human": "human",
    "agent": "agent",
    "organization": "organization",
    "brand": "brand",
    "community": "community",
    "protocol": "protocol",
    "service": "service",
    "unknown": "unknown",
    # common provider-native aliases
    "person": "human",
    "individual": "human",
    "user": "human",
    "bot": "agent",
    "automated": "agent",
    "org": "organization",
    "organisation": "organization",
    "company": "organization",
    "group": "community",
    "channel": "service",
}

_VERIFICATION = {
    "none": "none",
    "self_asserted": "self_asserted",
    "provider_verified": "provider_verified",
    "email_verified": "email_verified",
    "phone_verified": "phone_verified",
    "government_verified": "government_verified",
    "unknown": "unknown",
    # provider-native aliases
    "verified": "provider_verified",
    "blue_verified": "provider_verified",
    "is_verified": "provider_verified",
    "email_confirm": "email_verified",
    "confirmed_email": "email_verified",
}


class SocialIdentityProjector(SocialFactProjector):
    """Deterministic identity normalization into silver_social_identity_facts."""

    handles = SOCIAL_IDENTITY_TYPES
    table = SOCIAL_IDENTITY_TABLE
    fact_kind = "social_identity"

    def build_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any] | None:
        provider_account_id = as_str(
            record.get("provider_account_id") or record.get("account_id")
        )
        if not provider_account_id:
            # No provider account id -> nothing canonical to anchor the fact to.
            return None
        row = self._base_social_row(event, record)
        provider_identity = row["provider_identity"] or as_str(record.get("provider"))
        if not provider_identity:
            return None

        account_type = _ACCOUNT_TYPE.get(
            str(record.get("account_type") or "").lower(), "unknown"
        )
        verification = _VERIFICATION.get(
            str(record.get("verification_state") or "").lower(), "unknown"
        )
        social_identity_id = as_str(
            record.get("social_identity_id")
        ) or f"{provider_identity}:{provider_account_id}"
        observed_at = (
            as_str(record.get("observed_at")) or as_str(event.get("timestamp")) or None
        )

        row.update({
            "social_identity_id": social_identity_id,
            # Identity resolution is a separate domain — only an upstream
            # resolved binding is recorded, never synthesized here.
            "canonical_entity_ref": as_str(
                record.get("canonical_entity_ref")
                or (event.get("context") or {}).get("canonicalEntityRef")
            ),
            "provider_account_id": provider_account_id,
            "handle": as_str(record.get("handle") or record.get("username")),
            "display_name": as_str(record.get("display_name") or record.get("name")),
            "canonical_url": as_str(record.get("canonical_url") or record.get("url")),
            "account_type": account_type,
            "verification_state": verification,
            "platform_role": as_str(record.get("platform_role")),
            "provider_profile_created_at": as_str(record.get("created_at")),
            # first_observed_at is only a provider-supplied historical value; a
            # stateless projector must not claim "first seen now" on a re-read.
            "first_observed_at": as_str(record.get("first_observed_at")),
            "last_observed_at": as_str(record.get("last_observed_at")) or observed_at,
            "valid_from": as_str(record.get("valid_from")),
            "valid_to": as_str(record.get("valid_to")),
            "resolution_state": str(
                record.get("resolution_state") or "unresolved"
            ),
            "resolution_confidence": (
                record.get("resolution_confidence")
                if isinstance(record.get("resolution_confidence"), (int, float))
                and not isinstance(record.get("resolution_confidence"), bool)
                else None
            ),
            "identity_evidence_refs": as_list(record.get("identity_evidence_refs")),
        })
        return row
