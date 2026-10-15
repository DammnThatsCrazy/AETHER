"""
Aether Service — Entitlement Service
Mints, reuses, revokes, and expires entitlements. Entitlements represent
the right to access a protected resource for a bounded time window.

SIWX reuse: a valid SIWX session can reuse an entitlement within its TTL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from .commerce_models import Entitlement, EntitlementStatus, Settlement
from .commerce_store import get_commerce_store
from .resources import get_resource_registry

logger = get_logger("aether.service.x402.entitlements")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class EntitlementService:
    """Manages entitlement lifecycle."""

    def __init__(self, event_producer: Optional[EventProducer] = None):
        self._store = get_commerce_store()
        self._registry = get_resource_registry()
        self._producer = event_producer or EventProducer()

    async def mint(
        self,
        tenant_id: str,
        holder_id: str,
        holder_type: str,
        resource_id: str,
        settlement: Settlement,
        scope: str = "read",
        siwx_binding: Optional[str] = None,
    ) -> Entitlement:
        resource = await self._registry.get(tenant_id, resource_id)
        if not resource:
            raise ValueError(f"Unknown resource: {resource_id}")

        expires = _now() + timedelta(seconds=resource.entitlement_ttl_seconds)
        entitlement = Entitlement(
            tenant_id=tenant_id,
            holder_id=holder_id,
            holder_type=holder_type,
            resource_id=resource_id,
            scope=scope,
            status=EntitlementStatus.ACTIVE,
            settlement_id=settlement.settlement_id,
            expires_at=_iso(expires),
            siwx_binding=siwx_binding,
        )
        await self._store.put_entitlement(entitlement)
        await self._emit(
            Topic.COMMERCE_ENTITLEMENT_GRANTED,
            tenant_id,
            {
                "entitlement_id": entitlement.entitlement_id,
                "holder_id": holder_id,
                "resource_id": resource_id,
                "expires_at": entitlement.expires_at,
            },
        )
        metrics.increment("commerce_entitlements_granted")
        logger.info(
            f"entitlement minted: {entitlement.entitlement_id} "
            f"holder={holder_id} resource={resource_id} expires={entitlement.expires_at}"
        )
        return entitlement

    async def lookup(
        self, tenant_id: str, holder_id: str, resource_id: str
    ) -> Optional[Entitlement]:
        """Find an active, non-expired entitlement for holder on resource."""
        e = await self._store.find_active_entitlement(tenant_id, holder_id, resource_id)
        if e and self._is_expired(e):
            e.status = EntitlementStatus.EXPIRED
            await self._store.put_entitlement(e)
            await self._emit(
                Topic.COMMERCE_ENTITLEMENT_EXPIRED,
                tenant_id,
                {"entitlement_id": e.entitlement_id},
            )
            return None
        return e

    async def reuse(self, tenant_id: str, entitlement_id: str) -> Entitlement:
        e = await self._require(tenant_id, entitlement_id)
        if e.status != EntitlementStatus.ACTIVE or self._is_expired(e):
            raise ValueError("entitlement not active or expired")
        e.reuse_count += 1
        e.last_reused_at = _iso(_now())
        await self._store.put_entitlement(e)
        await self._emit(
            Topic.COMMERCE_ENTITLEMENT_REUSED,
            tenant_id,
            {"entitlement_id": entitlement_id, "reuse_count": e.reuse_count},
        )
        metrics.increment("commerce_entitlement_reuse")
        return e

    async def revoke(
        self, tenant_id: str, entitlement_id: str, revoked_by: str, reason: str
    ) -> Entitlement:
        e = await self._require(tenant_id, entitlement_id)
        if e.status == EntitlementStatus.REVOKED:
            return e
        e.status = EntitlementStatus.REVOKED
        e.revoked_at = _iso(_now())
        e.revoked_by = revoked_by
        e.revoke_reason = reason
        await self._store.put_entitlement(e)
        await self._emit(
            Topic.COMMERCE_ENTITLEMENT_REVOKED,
            tenant_id,
            {"entitlement_id": entitlement_id, "revoked_by": revoked_by, "reason": reason},
        )
        return e

    async def list_for_holder(
        self, tenant_id: str, holder_id: str, active_only: bool = True
    ) -> list[Entitlement]:
        items = await self._store.list_entitlements(tenant_id, holder_id=holder_id)
        if active_only:
            # Expire as we go
            fresh: list[Entitlement] = []
            for e in items:
                if e.status == EntitlementStatus.ACTIVE and self._is_expired(e):
                    e.status = EntitlementStatus.EXPIRED
                    await self._store.put_entitlement(e)
                    continue
                if e.status == EntitlementStatus.ACTIVE:
                    fresh.append(e)
            return fresh
        return items

    async def _require(self, tenant_id: str, entitlement_id: str) -> Entitlement:
        e = await self._store.get_entitlement(tenant_id, entitlement_id)
        if not e:
            raise ValueError(f"Entitlement not found: {entitlement_id}")
        return e

    def _is_expired(self, e: Entitlement) -> bool:
        try:
            return _now() > datetime.fromisoformat(e.expires_at)
        except Exception:
            return False

    async def _emit(self, topic: Topic, tenant_id: str, payload: dict) -> None:
        try:
            await self._producer.publish(
                Event(
                    topic=topic, payload=payload, tenant_id=tenant_id, source_service="x402.entitlements"
                )
            )
        except Exception as e:
            logger.error(f"failed to emit {topic}: {e}")


_service: Optional[EntitlementService] = None


def get_entitlement_service() -> EntitlementService:
    global _service
    if _service is None:
        _service = EntitlementService()
    return _service
