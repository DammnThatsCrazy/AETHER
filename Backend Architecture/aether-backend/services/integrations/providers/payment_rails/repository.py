"""Payment rail observability — durable, tenant-scoped repositories.

Six stores over the shared durable-store abstraction (all keys tenant-prefixed
so cross-tenant reads cannot resolve another tenant's records):

- ``payment_funding_sessions``          unique (tenant_id, idempotency_key)
- ``payment_provider_events``           unique (tenant_id, provider, provider_event_id)
- ``payment_provider_accounts``         one per (tenant_id, provider)
- ``payment_deposit_addresses``
- ``payment_virtual_accounts``
- ``payment_reconciliation_records``    one per (tenant_id, funding_session_id)

plus ``payment_rails_audit`` for signature rejections, hash conflicts,
downgrade attempts, and sync runs.

STATUS ORDERING: canonical rank initiated < submitted < pending < finals
(completed/failed/refunded/cancelled hold the highest ranks). A final state
NEVER regresses on duplicate or out-of-order provider events — downgrade
attempts are recorded in session metadata and the audit trail, not applied.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.common.common import NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

from services.integrations.providers.payment_rails.base import (
    ParsedProviderEvent,
    sanitize_payload,
)
from services.integrations.providers.payment_rails.models import (
    CANONICAL_STATUS_ORDERING,
    FINAL_STATUSES,
    FundingSession,
    new_id,
    utc_now_iso,
)

logger = get_logger("aether.payment_rails.repository")

# Fields that may be enriched on later events (fill-if-missing / overwrite
# with fresher non-null provider truth on an applied forward transition).
_ENRICHABLE_FIELDS = (
    "provider_detail", "provider_status", "status_reason",
    "user_id", "agent_id", "org_id", "session_id", "device_id",
    "journey_id", "campaign_id",
    "source_asset", "source_chain", "source_amount", "fiat_currency",
    "destination_asset", "destination_chain", "destination_amount",
    "destination_address", "fee_amount", "fee_currency",
    "provider_session_id", "provider_transaction_id", "provider_customer_ref",
    "deposit_address_id", "virtual_account_id", "tx_hash",
)


def status_rank(status: str) -> int:
    return CANONICAL_STATUS_ORDERING.get(status, 0)


class FundingSessionRepository:
    """Funding sessions, idempotent on (tenant_id, idempotency_key)."""

    def __init__(self) -> None:
        self._store = get_store("payment_funding_sessions")

    @staticmethod
    def _key(tenant_id: str, session_id: str) -> str:
        return f"{tenant_id}:{session_id}"

    async def find_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> Optional[dict]:
        records = await self._store.find(tenant_id=tenant_id, idempotency_key=idempotency_key)
        return records[0] if records else None

    async def find_by_provider_session(
        self, tenant_id: str, provider: str, provider_session_id: str
    ) -> Optional[dict]:
        records = await self._store.find(
            tenant_id=tenant_id, provider=provider, provider_session_id=provider_session_id
        )
        return records[0] if records else None

    async def get_record(self, tenant_id: str, session_id: str) -> Optional[dict]:
        if not session_id:
            return None
        return await self._store.get(self._key(tenant_id, session_id))

    async def get(self, tenant_id: str, session_id: str) -> dict:
        record = await self.get_record(tenant_id, session_id)
        if record is None:
            raise NotFoundError("Funding session")
        return record

    async def save(self, tenant_id: str, record: dict) -> dict:
        record["updated_at"] = utc_now_iso()
        await self._store.set(self._key(tenant_id, record["id"]), record)
        return record

    async def upsert_from_event(
        self, tenant_id: str, candidate: FundingSession, *, source: str = "webhook"
    ) -> tuple[dict, str]:
        """Persist a normalized funding session with status-ordering rules.

        Returns (record, disposition) where disposition is one of
        ``created`` | ``updated`` | ``duplicate`` | ``downgrade_blocked``.
        """
        existing = await self.find_by_idempotency_key(tenant_id, candidate.idempotency_key)
        if existing is None:
            candidate.metadata, _stripped = sanitize_payload(candidate.metadata)
            record = candidate.model_dump(mode="json")
            await self._store.set(self._key(tenant_id, candidate.id), record)
            metrics.increment("payment_rail_sessions_upserted_total",
                              labels={"provider": candidate.provider, "disposition": "created"})
            return record, "created"

        current_status = existing.get("status", "initiated")
        new_status = candidate.status
        current_rank = status_rank(current_status)
        new_rank = status_rank(new_status)

        if new_status == current_status:
            # Same status — enrich missing fields only; never a state change.
            changed = self._enrich(existing, candidate, overwrite=False)
            if changed:
                await self.save(tenant_id, existing)
            return existing, "duplicate"

        if new_rank <= current_rank or (
            current_status in FINAL_STATUSES and new_status not in FINAL_STATUSES
        ):
            # Downgrade / out-of-order — never applied. Recorded in metadata
            # for reconciliation and audited by the service layer.
            attempts = existing.setdefault("metadata", {}).setdefault("downgrade_attempts", [])
            attempts.append({
                "attempted_status": new_status,
                "attempted_provider_status": candidate.provider_status,
                "current_status": current_status,
                "source": source,
                "occurred_at": candidate.occurred_at,
                "recorded_at": utc_now_iso(),
            })
            await self.save(tenant_id, existing)
            metrics.increment("payment_rail_status_downgrade_blocked_total",
                              labels={"provider": candidate.provider})
            return existing, "downgrade_blocked"

        # Forward transition — apply status and refresh provider truth.
        existing["status"] = new_status
        existing["provider_status"] = candidate.provider_status or existing.get("provider_status")
        existing["status_reason"] = candidate.status_reason or existing.get("status_reason")
        existing["occurred_at"] = candidate.occurred_at or existing.get("occurred_at")
        self._enrich(existing, candidate, overwrite=True)
        await self.save(tenant_id, existing)
        metrics.increment("payment_rail_sessions_upserted_total",
                          labels={"provider": candidate.provider, "disposition": "updated"})
        return existing, "updated"

    @staticmethod
    def _enrich(existing: dict, candidate: FundingSession, *, overwrite: bool) -> bool:
        changed = False
        for field in _ENRICHABLE_FIELDS:
            value = getattr(candidate, field, None)
            if value is None:
                continue
            if overwrite or existing.get(field) in (None, ""):
                if existing.get(field) != value:
                    existing[field] = value
                    changed = True
        candidate_meta, _ = sanitize_payload(candidate.metadata or {})
        if candidate_meta:
            merged = {**candidate_meta, **(existing.get("metadata") or {})}
            if merged != existing.get("metadata"):
                existing["metadata"] = merged
                changed = True
        return changed

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        provider: Optional[str] = None,
        status: Optional[str] = None,
        flow_type: Optional[str] = None,
        rail: Optional[str] = None,
        reconciliation_state: Optional[str] = None,
        campaign_id: Optional[str] = None,
        journey_id: Optional[str] = None,
        occurred_from: Optional[str] = None,
        occurred_to: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        if status:
            filters["status"] = status
        if flow_type:
            filters["flow_type"] = flow_type
        if rail:
            filters["rail"] = rail
        if reconciliation_state:
            filters["reconciliation_state"] = reconciliation_state
        if campaign_id:
            filters["campaign_id"] = campaign_id
        if journey_id:
            filters["journey_id"] = journey_id
        records = await self._store.find(**filters)
        if occurred_from:
            records = [r for r in records if (r.get("occurred_at") or "") >= occurred_from]
        if occurred_to:
            records = [r for r in records if (r.get("occurred_at") or "") <= occurred_to]
        records.sort(key=lambda r: r.get("occurred_at") or "", reverse=True)
        return records[: max(1, min(limit, 500))]

    async def list_all(self) -> list[dict]:
        """Cross-tenant listing — Kyber operator aggregates only."""
        return await self._store.find()


class ProviderEventRepository:
    """Sanitized provider event records, unique on
    (tenant_id, provider, provider_event_id) with raw-hash dedupe."""

    def __init__(self) -> None:
        self._store = get_store("payment_provider_events")

    @staticmethod
    def _key(tenant_id: str, provider: str, provider_event_id: str) -> str:
        return f"{tenant_id}:{provider}:{provider_event_id}"

    async def record_event(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> tuple[dict, str]:
        """Store a sanitized provider event.

        Returns (record, disposition):
        - ``accepted``          first delivery — stored.
        - ``ignored_duplicate`` same event id, same raw hash (exact redelivery).
        - ``rejected``          same event id, different raw hash (mutated
                                payload reusing an id) — not stored; audited by
                                the caller.
        """
        key = self._key(tenant_id, event.provider, event.provider_event_id)
        existing = await self._store.get(key)
        if existing is not None:
            if existing.get("raw_hash") == event.raw_hash:
                metrics.increment("payment_rail_event_duplicate_total",
                                  labels={"provider": event.provider})
                return existing, "ignored_duplicate"
            metrics.increment("payment_rail_event_rejected_total",
                              labels={"provider": event.provider})
            return existing, "rejected"
        record = {
            "id": event.id,
            "tenant_id": tenant_id,
            "provider": event.provider,
            "provider_event_id": event.provider_event_id,
            "event_type": event.event_type,
            "occurred_at": event.occurred_at,
            "payload": event.payload,  # sanitized by the adapter
            "raw_hash": event.raw_hash,
            "source": event.source,
            "stripped_key_count": len(event.stripped_keys),
            "received_at": utc_now_iso(),
        }
        await self._store.set(key, record)
        return record, "accepted"

    async def list_for_tenant(
        self, tenant_id: str, provider: Optional[str] = None
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        return await self._store.find(**filters)


class ProviderAccountRepository:
    """One connection-metadata record per (tenant_id, provider)."""

    def __init__(self) -> None:
        self._store = get_store("payment_provider_accounts")

    @staticmethod
    def _key(tenant_id: str, provider: str) -> str:
        return f"{tenant_id}:{provider}"

    async def get(self, tenant_id: str, provider: str) -> Optional[dict]:
        return await self._store.get(self._key(tenant_id, provider))

    async def upsert(self, tenant_id: str, provider: str, changes: dict[str, Any]) -> dict:
        existing = await self.get(tenant_id, provider) or {
            "id": new_id(),
            "tenant_id": tenant_id,
            "provider": provider,
            "environment": "production",
            "status": "not_configured",
            "webhook_configured": False,
            "polling_configured": False,
            "created_at": utc_now_iso(),
        }
        sanitized, _ = sanitize_payload(changes)
        existing.update(sanitized)
        existing["updated_at"] = utc_now_iso()
        await self._store.set(self._key(tenant_id, provider), existing)
        return existing


class DepositAddressRepository:
    """Provider-issued crypto deposit address references."""

    def __init__(self) -> None:
        self._store = get_store("payment_deposit_addresses")

    @staticmethod
    def _key(tenant_id: str, provider: str, ref: str) -> str:
        return f"{tenant_id}:{provider}:{ref}"

    async def upsert(self, tenant_id: str, record: dict[str, Any]) -> dict:
        provider = record.get("provider", "")
        ref = record.get("provider_address_id") or record.get("address") or new_id()
        key = self._key(tenant_id, provider, str(ref))
        existing = await self._store.get(key)
        sanitized, _ = sanitize_payload(record)
        if existing is None:
            sanitized.setdefault("id", new_id())
            sanitized["tenant_id"] = tenant_id
            sanitized.setdefault("created_at", utc_now_iso())
            sanitized["updated_at"] = utc_now_iso()
            await self._store.set(key, sanitized)
            return sanitized
        existing.update({k: v for k, v in sanitized.items() if v is not None})
        existing["updated_at"] = utc_now_iso()
        await self._store.set(key, existing)
        return existing

    async def list_for_tenant(self, tenant_id: str, provider: Optional[str] = None) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        return await self._store.find(**filters)


class VirtualAccountRepository:
    """Provider-issued virtual bank account references (masked refs only)."""

    def __init__(self) -> None:
        self._store = get_store("payment_virtual_accounts")

    @staticmethod
    def _key(tenant_id: str, provider: str, provider_virtual_account_id: str) -> str:
        return f"{tenant_id}:{provider}:{provider_virtual_account_id}"

    async def upsert(self, tenant_id: str, record: dict[str, Any]) -> dict:
        provider = record.get("provider", "")
        va_id = str(record.get("provider_virtual_account_id") or new_id())
        key = self._key(tenant_id, provider, va_id)
        existing = await self._store.get(key)
        sanitized, _ = sanitize_payload(record)
        if existing is None:
            sanitized.setdefault("id", new_id())
            sanitized["tenant_id"] = tenant_id
            sanitized.setdefault("created_at", utc_now_iso())
            sanitized["updated_at"] = utc_now_iso()
            await self._store.set(key, sanitized)
            return sanitized
        existing.update({k: v for k, v in sanitized.items() if v is not None})
        existing["updated_at"] = utc_now_iso()
        await self._store.set(key, existing)
        return existing

    async def list_for_tenant(self, tenant_id: str, provider: Optional[str] = None) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        return await self._store.find(**filters)


class ReconciliationRepository:
    """One reconciliation record per (tenant_id, funding_session_id)."""

    def __init__(self) -> None:
        self._store = get_store("payment_reconciliation_records")

    @staticmethod
    def _key(tenant_id: str, funding_session_id: str) -> str:
        return f"{tenant_id}:{funding_session_id}"

    async def get_for_session(self, tenant_id: str, funding_session_id: str) -> Optional[dict]:
        return await self._store.get(self._key(tenant_id, funding_session_id))

    async def upsert(self, tenant_id: str, record: dict[str, Any]) -> dict:
        key = self._key(tenant_id, record["funding_session_id"])
        existing = await self._store.get(key)
        if existing is not None:
            record["id"] = existing["id"]
            record["created_at"] = existing.get("created_at", record.get("created_at"))
            record["first_observed_at"] = existing.get(
                "first_observed_at", record.get("first_observed_at")
            )
        record["updated_at"] = utc_now_iso()
        await self._store.set(key, record)
        return record

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        state: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if state:
            filters["state"] = state
        if provider:
            filters["provider"] = provider
        return await self._store.find(**filters)

    async def list_all(self) -> list[dict]:
        return await self._store.find()


class PaymentRailsAuditRepository:
    """Audit trail for adapter/service occurrences (sanitized detail only)."""

    def __init__(self) -> None:
        self._store = get_store("payment_rails_audit")

    async def record(self, tenant_id: str, entry: dict[str, Any]) -> dict:
        entry.setdefault("id", new_id())
        entry["tenant_id"] = tenant_id
        entry.setdefault("occurred_at", utc_now_iso())
        await self._store.set(f"{tenant_id}:{entry['id']}", entry)
        return entry

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        provider: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        if action:
            filters["action"] = action
        records = await self._store.find(**filters)
        records.sort(key=lambda r: r.get("occurred_at") or "", reverse=True)
        return records[:limit]


class PaymentRailsRepositories:
    """Bundle of the payment-rail stores used by the service layer."""

    def __init__(self) -> None:
        self.sessions = FundingSessionRepository()
        self.events = ProviderEventRepository()
        self.accounts = ProviderAccountRepository()
        self.deposit_addresses = DepositAddressRepository()
        self.virtual_accounts = VirtualAccountRepository()
        self.reconciliation = ReconciliationRepository()
        self.audit = PaymentRailsAuditRepository()


_repositories: Optional[PaymentRailsRepositories] = None


def get_payment_rails_repositories() -> PaymentRailsRepositories:
    global _repositories
    if _repositories is None:
        _repositories = PaymentRailsRepositories()
    return _repositories
