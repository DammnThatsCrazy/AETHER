"""Consent gate for suggestion delivery.

A suggestion that targets an end user (``audience == "end_user"``) may be
delivered only when the consent owner (``shared.privacy.consent_enforcement``)
reports a grant for that user and purpose. Suggestions for the tenant's own
staff (the default) need no end-user consent. Any lookup failure is a denial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from shared.logger.logger import get_logger

from .models import SuggestionClass

logger = get_logger("aether.suggestions.consent")

# Purpose from the canonical consent registry that each end-user-facing class
# needs. Classes not listed fall back to the strictest common purpose.
CLASS_CONSENT_PURPOSE: dict[str, str] = {
    SuggestionClass.CAMPAIGN.value: "marketing",
    SuggestionClass.RETARGETING.value: "marketing",
    SuggestionClass.NOTIFICATION.value: "marketing",
    SuggestionClass.IDENTITY.value: "personalization",
}
DEFAULT_CONSENT_PURPOSE = "marketing"


@dataclass(frozen=True)
class ConsentVerdict:
    allowed: bool
    reason: str


def consent_purpose_for(suggestion_class: Optional[str]) -> str:
    return CLASS_CONSENT_PURPOSE.get(suggestion_class or "", DEFAULT_CONSENT_PURPOSE)


async def delivery_consent_verdict(record: dict, consent_repo: Any = None) -> ConsentVerdict:
    """Decide whether this suggestion may be delivered, per the consent owner."""
    if record.get("audience", "tenant_staff") != "end_user":
        return ConsentVerdict(True, "tenant_staff_audience")

    subject = record.get("consent_subject_id")
    tenant_id = record.get("tenant_id")
    if not subject or not tenant_id:
        return ConsentVerdict(False, "consent_subject_missing")

    purpose = consent_purpose_for(record.get("suggestion_class"))
    try:
        from shared.privacy.consent_enforcement import check_consent

        if consent_repo is None:
            from repositories.repos import ConsentRepository

            consent_repo = ConsentRepository()
        granted = await check_consent(consent_repo, tenant_id, subject, purpose)
    except Exception as exc:  # noqa: BLE001 - consent store unavailable -> fail closed
        logger.warning(f"consent lookup failed (fail-closed): {exc}")
        return ConsentVerdict(False, "consent_lookup_failed")
    return ConsentVerdict(granted, f"consent_{purpose}_granted" if granted else f"consent_{purpose}_not_granted")
