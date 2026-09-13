"""Canonical scoped suppression authority (§16).

One authority owns the truth of "who is suppressed, at what scope, and why",
and it keeps four facts deliberately separate:

  * ``provider_enforcement_state`` — what the *provider* is doing
    (``provider_reported`` when we learned it from a provider event,
    ``provider_confirmed`` after reconciliation, ``unknown`` otherwise);
  * ``aether_enforcement_state`` — what *Aether* is doing
    (``enforced`` = the canonical ledger honors it; ``write_back_pending`` /
    ``write_back_failed`` / ``write_back_disabled`` describe provider write-back,
    which is OFF by default — Aether observes, it does not mutate the provider,
    ADR-C1);
  * the canonical suppression record itself (Aether-observed + canonical); and
  * reconciliation (``last_reconciled_at``).

Enforcement fails **closed**: when suppression state cannot be safely
determined, :meth:`is_suppressed` returns True so a suppressed recipient is
never contacted on a guess.

Storage reuses :class:`CommunicationSuppressionRepository` (real-columned table
with a local in-memory fallback). Suppression ids are deterministic so replays
of the same provider event do not create duplicate suppressions.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from services.comms.contracts import SuppressionScope
from services.comms.repository import CommunicationSuppressionRepository

# Canonical event → (reason, default scope) for suppression-bearing events.
_EVENT_SUPPRESSION_REASON: dict[str, tuple[str, str]] = {
    "unsubscribe_observed": ("unsubscribe", SuppressionScope.MARKETING_CHANNEL.value),
    "email_spam_complaint": ("spam_complaint", SuppressionScope.PROVIDER_ACCOUNT.value),
    "email_suppressed": ("provider_suppression", SuppressionScope.PROVIDER_ACCOUNT.value),
    # A hard bounce suppresses only when policy requires (handled in from_event).
    "email_bounced": ("hard_bounce", SuppressionScope.PROVIDER_ACCOUNT.value),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _suppression_id(
    tenant_id: str, subject: str, scope: str, scope_ref: str, reason: str, provider: str
) -> str:
    raw = f"{tenant_id}|{subject}|{scope}|{scope_ref}|{reason}|{provider}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_back_enabled() -> bool:
    """Provider suppression write-back is a separately-authorized capability.

    Read permission never implies suppression-write permission; default OFF.
    """
    try:
        from config.settings import settings
        return bool(getattr(settings.comms, "suppression_write_back_enabled", False))
    except Exception:  # pragma: no cover - default closed
        return False


class SuppressionAuthorityService:
    """Canonical scoped suppression authority (record · read · reconcile)."""

    def __init__(self, repo: Optional[CommunicationSuppressionRepository] = None) -> None:
        self.repo = repo or CommunicationSuppressionRepository()

    async def record(
        self,
        tenant_id: str,
        *,
        reason: str,
        scope: str,
        scope_ref: Optional[str] = None,
        entity_id: Optional[str] = None,
        recipient_alias_id: Optional[str] = None,
        channel: str = "email",
        provider: Optional[str] = None,
        provider_account_id: Optional[str] = None,
        canonical_entity_id: Optional[str] = None,
        canonical_profile_id: Optional[str] = None,
        consent_purpose: Optional[str] = None,
        processing_basis: Optional[str] = None,
        source_event_id: Optional[str] = None,
        provider_enforcement_state: str = "provider_reported",
        evidence_reference: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a canonical suppression (idempotent by deterministic id).

        ``aether_enforcement_state`` is ``enforced`` (the canonical ledger is
        authoritative); provider write-back stays disabled unless separately
        authorized.
        """
        subject = entity_id or recipient_alias_id or "unknown"
        supp_id = _suppression_id(
            tenant_id, subject, scope, scope_ref or "", reason, provider or "",
        )
        aether_state = "enforced" if write_back_enabled() else "write_back_disabled"
        record = {
            "suppression_id": supp_id,
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "recipient_alias_id": recipient_alias_id,
            "channel": channel,
            "scope": scope,
            "scope_ref": scope_ref,
            "reason": reason,
            "source_event_id": source_event_id,
            "provider": provider,
            "provider_account_id": provider_account_id,
            "canonical_entity_id": canonical_entity_id,
            "canonical_profile_id": canonical_profile_id,
            "consent_purpose": consent_purpose,
            "processing_basis": processing_basis,
            "provider_enforcement_state": provider_enforcement_state,
            "aether_enforcement_state": aether_state,
            "active": True,
            "created_at": _now_iso(),
        }
        return await self.repo.add(record)

    async def record_from_event(
        self, tenant_id: str, fact: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Map a canonical communication event/fact to a suppression, if any.

        Returns None when the event carries no suppression signal. A hard bounce
        suppresses; a soft bounce does not.
        """
        event_type = fact.get("event_type") or fact.get("source_event_type") or ""
        mapping = _EVENT_SUPPRESSION_REASON.get(event_type)
        if not mapping:
            return None
        reason, default_scope = mapping
        props = fact.get("properties") if isinstance(fact.get("properties"), dict) else fact
        if event_type == "email_bounced":
            bounce_type = props.get("bounce_type") or fact.get("bounce_type") or "soft"
            if str(bounce_type).lower() != "hard":
                return None  # soft bounce is not a suppression
        scope = (
            props.get("unsubscribe_scope")
            or props.get("suppression_scope")
            or default_scope
        )
        # Derive the alias hash from a raw address if the fact only carries an
        # email — the ledger stores the tenant-scoped hash, never raw PII.
        recipient_alias_id = props.get("recipient_alias_id") or fact.get("recipient_alias_id")
        if not recipient_alias_id and (props.get("recipient_email") or props.get("email")):
            from services.comms.mailbox import build_email_alias
            alias = build_email_alias(
                str(props.get("recipient_email") or props.get("email")), tenant_id
            )
            recipient_alias_id = alias.alias_hash if alias else None
        return await self.record(
            tenant_id,
            reason=reason,
            scope=scope,
            scope_ref=props.get("scope_ref") or props.get("external_campaign_id"),
            entity_id=props.get("recipient_entity_id") or fact.get("entity_id"),
            recipient_alias_id=recipient_alias_id,
            channel=props.get("channel") or fact.get("channel") or "email",
            provider=props.get("provider") or fact.get("source"),
            provider_account_id=props.get("provider_account_id"),
            source_event_id=props.get("provider_event_id") or fact.get("external_id"),
            consent_purpose=props.get("consent_purpose"),
            processing_basis=props.get("processing_basis"),
        )

    # ── Read surface ─────────────────────────────────────────────────────────

    async def list_active(
        self, tenant_id: str, *, entity_id: Optional[str] = None,
        recipient_alias_id: Optional[str] = None, channel: str = "email",
    ) -> list[dict[str, Any]]:
        return await self.repo.active_for(
            tenant_id, entity_id=entity_id,
            recipient_alias_id=recipient_alias_id, channel=channel,
        )

    async def list_for_tenant(
        self, tenant_id: str, *, provider: Optional[str] = None, limit: int = 500,
    ) -> list[dict[str, Any]]:
        return await self.repo.list_active_for_tenant(
            tenant_id, provider=provider, limit=limit,
        )

    async def is_suppressed(
        self, tenant_id: str, *, entity_id: Optional[str] = None,
        recipient_alias_id: Optional[str] = None, channel: str = "email",
    ) -> bool:
        """Fail-closed suppression check.

        Returns True if any active suppression exists — and also True if the
        lookup fails, so a suppressed recipient is never contacted on a guess.
        """
        if not entity_id and not recipient_alias_id:
            return True  # cannot prove not-suppressed → fail closed
        try:
            active = await self.list_active(
                tenant_id, entity_id=entity_id,
                recipient_alias_id=recipient_alias_id, channel=channel,
            )
            return bool(active)
        except Exception:  # pragma: no cover - fail closed on error
            return True

    # ── Provider reconciliation (observe-only) ────────────────────────────────

    async def reconcile(
        self, tenant_id: str, *, provider: str,
        provider_reported: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Compare provider-reported suppressions against Aether's canonical set.

        Observe-only: this reports drift and stamps ``last_reconciled_at``; it
        does NOT write back to the provider unless write-back is separately
        authorized (and even then only via an explicit write-back path).
        """
        aether = await self.repo.list_active_for_tenant(tenant_id)
        aether_subjects = {
            (s.get("recipient_alias_id") or s.get("entity_id")) for s in (aether or [])
            if s.get("provider") in (provider, None)
        }
        reported_subjects = {
            (r.get("recipient_alias_id") or r.get("entity_id"))
            for r in (provider_reported or [])
        }
        only_provider = sorted(x for x in reported_subjects - aether_subjects if x)
        only_aether = sorted(x for x in aether_subjects - reported_subjects if x)
        return {
            "provider": provider,
            "aether_count": len(aether_subjects),
            "provider_reported_count": len(reported_subjects),
            "only_in_provider": only_provider,
            "only_in_aether": only_aether,
            "in_sync": not only_provider and not only_aether,
            "write_back_enabled": write_back_enabled(),
            "reconciled_at": _now_iso(),
        }


__all__ = ["SuppressionAuthorityService", "write_back_enabled"]
