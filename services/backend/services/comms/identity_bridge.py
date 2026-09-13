"""Provider → canonical identity bridge for communications (§13).

Every provider identity Aether observes (a Klaviyo ``provider_profile_id``, a
recipient email, a mailbox account) is recorded here as a durable mapping
toward a canonical Aether entity. When resolution is not yet possible the
mapping is preserved as a **provisional** record — never discarded, never a
fabricated user — and surfaced for mapping review.

Design rules honored:
  * shared / role / no-reply mailboxes never auto-collapse into a human
    profile (they stay provisional, org-level confidence);
  * the communication fact is always preserved even when identity is
    unresolved (this module records evidence, it does not gate ingestion);
  * merge/split repoints the bridge and triggers a communications rebuild.

Storage is the generic JSONB row shape via :class:`BaseRepository`, so the
bridge works in local mode without Postgres (like the sync-run ledger).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from repositories.repos import BaseRepository
from services.comms.mailbox import build_email_alias, identity_confidence_for_alias

# resolved: linked to a canonical entity · provisional: preserved, awaiting
# review · unresolved: no evidence to link yet · superseded: repointed by merge
ResolutionStatus = str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity_id(
    tenant_id: str, provider: str, provider_account_id: str, discriminator: str
) -> str:
    raw = f"{tenant_id}|{provider}|{provider_account_id}|{discriminator}"
    return "provid_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class ProviderIdentity(BaseModel):
    """One provider→canonical identity mapping (§13 field set)."""

    identity_id: str
    tenant_id: str
    provider: str
    provider_product: Optional[str] = None
    provider_account_id: str = ""
    provider_profile_id: Optional[str] = None
    provider_recipient_id: Optional[str] = None
    email_alias_hash: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    canonical_profile_id: Optional[str] = None
    identity_cluster_id: Optional[str] = None
    resolution_status: ResolutionStatus = "provisional"
    resolution_method: Optional[str] = None
    confidence: float = 0.0
    is_shared_mailbox: bool = False
    first_seen_at: str = Field(default_factory=_now_iso)
    last_seen_at: str = Field(default_factory=_now_iso)
    verified_at: Optional[str] = None
    superseded_by: Optional[str] = None
    source_evidence: Optional[str] = None


class ProviderIdentityRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("comms_provider_identities")

    async def upsert(self, identity: ProviderIdentity) -> dict[str, Any]:
        existing = await self.find_by_id(identity.identity_id)
        payload = identity.model_dump()
        if existing:
            # Preserve first_seen; advance last_seen; never regress a resolved
            # mapping back to provisional on a later bare observation.
            payload["first_seen_at"] = existing.get("first_seen_at", payload["first_seen_at"])
            if existing.get("resolution_status") == "resolved" and \
                    payload["resolution_status"] == "provisional":
                payload["resolution_status"] = "resolved"
                payload["canonical_entity_id"] = (
                    payload.get("canonical_entity_id") or existing.get("canonical_entity_id")
                )
        payload["updated_at"] = _now_iso()
        return await self.insert(identity.identity_id, payload)

    async def list_provisional(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            {"tenant_id": tenant_id, "resolution_status": "provisional"},
            sort_by="updated_at", sort_order="desc", limit=limit,
        )

    async def list_for_entity(
        self, tenant_id: str, canonical_entity_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            {"tenant_id": tenant_id, "canonical_entity_id": canonical_entity_id},
            sort_by="updated_at", sort_order="desc", limit=limit,
        )


class ProviderIdentityBridge:
    """Records provider identity observations and resolves them when possible."""

    def __init__(self, repo: Optional[ProviderIdentityRepository] = None) -> None:
        self.repo = repo or ProviderIdentityRepository()

    async def _resolve_entity_by_alias(
        self, tenant_id: str, alias_hash: str
    ) -> Optional[str]:
        """Best-effort canonical-entity lookup by email alias (never raises)."""
        try:
            from services.identity.repository import IdentityResolutionRepository
            from services.identity.signals import IdentitySignalType
            repo = IdentityResolutionRepository()
            entity_ids = await repo.find_subjects_by_alias(
                tenant_id, IdentitySignalType.EMAIL_HASH, alias_hash
            )
            return entity_ids[0] if entity_ids else None
        except Exception:  # pragma: no cover - identity backend optional in local
            return None

    async def record_observation(
        self,
        *,
        tenant_id: str,
        provider: str,
        provider_account_id: Optional[str] = None,
        provider_profile_id: Optional[str] = None,
        provider_recipient_id: Optional[str] = None,
        raw_email: Optional[str] = None,
        canonical_entity_id: Optional[str] = None,
        method: str = "provider_profile",
        source_evidence: Optional[str] = None,
    ) -> Optional[ProviderIdentity]:
        """Upsert a provider identity mapping, resolving to a canonical entity
        when evidence allows. Returns None only when there is nothing to key on.
        """
        account = provider_account_id or provider
        alias = build_email_alias(raw_email, tenant_id) if raw_email else None
        alias_hash = alias.alias_hash if alias else None
        is_shared = bool(alias and alias.is_shared_mailbox)

        discriminator = provider_profile_id or alias_hash or provider_recipient_id
        if not discriminator:
            return None

        resolved_entity = canonical_entity_id
        resolution_method = method if canonical_entity_id else None
        # Shared / role / no-reply mailboxes never auto-collapse into a human.
        if not resolved_entity and alias_hash and not is_shared:
            found = await self._resolve_entity_by_alias(tenant_id, alias_hash)
            if found:
                resolved_entity = found
                resolution_method = "email_alias"

        if resolved_entity:
            status: ResolutionStatus = "resolved"
        else:
            status = "provisional"

        confidence = (
            identity_confidence_for_alias(alias, method=method) if alias else
            (0.7 if resolved_entity else 0.0)
        )

        identity = ProviderIdentity(
            identity_id=_identity_id(tenant_id, provider, account, str(discriminator)),
            tenant_id=tenant_id,
            provider=provider,
            provider_product=provider,
            provider_account_id=account,
            provider_profile_id=provider_profile_id,
            provider_recipient_id=provider_recipient_id,
            email_alias_hash=alias_hash,
            canonical_entity_id=resolved_entity,
            resolution_status=status,
            resolution_method=resolution_method,
            confidence=confidence,
            is_shared_mailbox=is_shared,
            verified_at=_now_iso() if status == "resolved" else None,
            source_evidence=source_evidence,
        )
        await self.repo.upsert(identity)
        return identity

    async def mark_resolved(
        self, tenant_id: str, identity_id: str, canonical_entity_id: str,
        *, method: str = "manual_mapping",
    ) -> Optional[dict[str, Any]]:
        """Operator/mapping-review resolution of a provisional identity."""
        row = await self.repo.find_by_id(identity_id)
        if not row or row.get("tenant_id") != tenant_id:
            return None
        row["canonical_entity_id"] = canonical_entity_id
        row["resolution_status"] = "resolved"
        row["resolution_method"] = method
        row["verified_at"] = _now_iso()
        row["updated_at"] = _now_iso()
        await self.repo.insert(identity_id, row)
        await self._trigger_rebuild(tenant_id, canonical_entity_id)
        return row

    async def on_identity_merge(
        self, tenant_id: str, from_entity_id: str, to_entity_id: str
    ) -> int:
        """Repoint provider identities after a canonical merge + rebuild.

        Returns the number of mappings repointed. Triggers a communications
        state rebuild for the surviving entity so Profile360/Campaign360 reflect
        the merged identity.
        """
        rows = await self.repo.list_for_entity(tenant_id, from_entity_id, limit=1000)
        for row in rows:
            row["canonical_entity_id"] = to_entity_id
            row["resolution_method"] = "identity_merge"
            row["updated_at"] = _now_iso()
            await self.repo.insert(row["identity_id"], row)
        if rows:
            await self._trigger_rebuild(tenant_id, to_entity_id)
        return len(rows)

    async def _trigger_rebuild(self, tenant_id: str, entity_id: str) -> None:
        """Best-effort communications state rebuild for one entity."""
        try:
            from services.comms.rebuild_coalescer import get_rebuild_coalescer
            await get_rebuild_coalescer().request_rebuild(
                tenant_id, entity_id, reason="identity_bridge",
            )
        except Exception:  # pragma: no cover - rebuild is best-effort
            try:
                from services.comms.state import CommunicationStateService
                await CommunicationStateService().rebuild_for_entity(tenant_id, entity_id)
            except Exception:
                pass


async def record_identity_from_event(
    tenant_id: str, data: dict[str, Any]
) -> Optional[ProviderIdentity]:
    """Record provider identity evidence carried on a normalized event.

    Accepts both comms events (carry recipient_email + provider_profile_id) and
    ``*.profile`` catalog records. Best-effort — never raises into ingest.
    """
    props = dict(data.get("properties") or {})
    provider = props.get("provider") or data.get("source") or "unknown"
    try:
        return await ProviderIdentityBridge().record_observation(
            tenant_id=tenant_id,
            provider=provider,
            provider_account_id=props.get("provider_account_id"),
            provider_profile_id=props.get("provider_profile_id") or props.get("provider_profile"),
            provider_recipient_id=props.get("provider_recipient_id"),
            raw_email=props.get("recipient_email") or props.get("email"),
            canonical_entity_id=props.get("recipient_entity_id"),
            method="provider_profile",
            source_evidence=str(data.get("event_type") or ""),
        )
    except Exception:  # pragma: no cover - never break ingest
        return None


__all__ = [
    "ProviderIdentity",
    "ProviderIdentityRepository",
    "ProviderIdentityBridge",
    "record_identity_from_event",
]
