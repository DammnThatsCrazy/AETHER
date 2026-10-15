"""Durable webhook endpoint registry.

A public provider webhook URL is ``/…/{family}/{connector}/{endpoint_id}`` where
``family`` is ``payment-rails`` or ``comms``. The ``endpoint_id`` is high-entropy,
non-sequential, durable, revocable and bound to exactly one
(tenant, provider, environment, domain). Resolution happens server-side — no
tenant id is ever accepted from a request header or body. The id alone is not
authentication; the provider signature is still verified downstream.

One registry and one table back every domain ("extend, do not rebuild"): the
``domain`` discriminator (stored in the JSONB data, default ``payment``) keeps
endpoints of different families from resolving through each other's routes.
"""

from __future__ import annotations

import secrets
from typing import Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.payment_rails.webhook_endpoints")

# Historical table name — now backs webhook endpoints for any domain.
ENDPOINT_TABLE = "payment_webhook_endpoints"
_ID_PREFIX = "whe_"

# Domain discriminator: each domain maps to its own public webhook URL family.
DOMAIN_PAYMENT = "payment"
DOMAIN_COMMS = "comms"

# Public URL family per domain (routes must mirror these prefixes).
_FAMILY_BY_DOMAIN = {
    DOMAIN_PAYMENT: "payment-rails",
    DOMAIN_COMMS: "comms",
}


class EndpointState:
    ACTIVE = "active"
    REVOKED = "revoked"


def _domain_of(row: dict) -> str:
    """Backward-compatible domain read: pre-domain rows are payment endpoints."""
    return row.get("domain") or DOMAIN_PAYMENT


class _WebhookEndpointRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__(ENDPOINT_TABLE)


def _new_endpoint_id() -> str:
    # 32 random bytes → 64 hex chars; non-sequential, unguessable.
    return _ID_PREFIX + secrets.token_hex(32)


_SAFE_FIELDS = (
    "provider",
    "environment",
    "domain",
    "state",
    "created_at",
    "created_by",
    "revoked_at",
    "revoked_by",
)


class WebhookEndpointRegistry:
    """Create / resolve / rotate / revoke public webhook endpoints.

    ``domain`` discriminates families that share this registry (``payment`` and
    ``comms``). Endpoint ids are globally unique, so cross-domain resolution is
    prevented by the domain check rather than by separate id namespaces.
    """

    def __init__(self, repo: Optional[_WebhookEndpointRepo] = None) -> None:
        self._repo = repo or _WebhookEndpointRepo()

    async def create(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        *,
        created_by: str,
        domain: str = DOMAIN_PAYMENT,
    ) -> dict:
        endpoint_id = _new_endpoint_id()
        data = {
            "tenant_id": tenant_id,
            "provider": provider,
            "environment": environment,
            "domain": domain,
            "state": EndpointState.ACTIVE,
            "created_by": created_by,
            "revoked_at": None,
            "revoked_by": None,
        }
        await self._repo.insert(endpoint_id, data)
        logger.info(
            "webhook endpoint created tenant=%s provider=%s env=%s domain=%s",
            tenant_id, provider, environment, domain,
        )
        return self._public(endpoint_id, data)

    async def resolve(
        self,
        endpoint_id: str,
        provider: str,
        domain: Optional[str] = None,
    ) -> Optional[dict]:
        """Return ``{tenant_id, provider, environment, domain}`` for an ACTIVE
        endpoint whose provider (and, when given, domain) matches the route, else
        ``None`` (uniform — never leaks whether the id, tenant, provider, or
        domain exists)."""
        if not endpoint_id or not endpoint_id.startswith(_ID_PREFIX):
            return None
        row = await self._repo.find_by_id(endpoint_id)
        if row is None:
            return None
        if row.get("state") != EndpointState.ACTIVE:
            return None
        if row.get("provider") != provider:
            return None
        if domain is not None and _domain_of(row) != domain:
            return None
        return {
            "tenant_id": row["tenant_id"],
            "provider": row["provider"],
            "environment": row["environment"],
            "domain": _domain_of(row),
            "endpoint_id": endpoint_id,
        }

    async def revoke(self, tenant_id: str, endpoint_id: str, *, actor: str) -> bool:
        row = await self._repo.find_by_id(endpoint_id)
        if row is None or row.get("tenant_id") != tenant_id:
            return False
        if row.get("state") == EndpointState.REVOKED:
            return True
        await self._repo.update(
            endpoint_id,
            {"state": EndpointState.REVOKED, "revoked_at": utc_now().isoformat(), "revoked_by": actor},
        )
        logger.info("webhook endpoint revoked tenant=%s", tenant_id)
        return True

    async def rotate(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        *,
        actor: str,
        domain: Optional[str] = None,
    ) -> dict:
        """Revoke any active endpoints for the slot and mint a fresh one."""
        for row in await self._active_for(
            tenant_id, provider, environment, domain=domain
        ):
            await self.revoke(tenant_id, row["id"], actor=actor)
        return await self.create(
            tenant_id, provider, environment, created_by=actor,
            domain=domain or DOMAIN_PAYMENT,
        )

    async def list_for(
        self,
        tenant_id: str,
        provider: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        rows = await self._repo.find_many(filters=filters, limit=200)
        out = []
        for r in rows:
            if domain is not None and _domain_of(r) != domain:
                continue
            out.append(self._public(r["id"], r))
        return out

    async def _active_for(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        domain: Optional[str] = None,
    ) -> list[dict]:
        rows = await self._repo.find_many(
            filters={
                "tenant_id": tenant_id,
                "provider": provider,
                "environment": environment,
                "state": EndpointState.ACTIVE,
            },
            limit=50,
        )
        if domain is None:
            return rows
        return [r for r in rows if _domain_of(r) == domain]

    @staticmethod
    def _public(endpoint_id: str, row: dict) -> dict:
        view = {"endpoint_id": endpoint_id}
        view.update({f: row.get(f) for f in _SAFE_FIELDS if f in row})
        # Safe public webhook path suffix (never includes a secret).
        family = _FAMILY_BY_DOMAIN.get(_domain_of(row), _FAMILY_BY_DOMAIN[DOMAIN_PAYMENT])
        view["webhook_path"] = (
            f"/v1/integrations/webhooks/{family}/{row.get('provider')}/{endpoint_id}"
        )
        return view


# Module singleton — durable state lives in the DB.
webhook_endpoint_registry = WebhookEndpointRegistry()


__all__ = [
    "WebhookEndpointRegistry",
    "webhook_endpoint_registry",
    "EndpointState",
    "ENDPOINT_TABLE",
    "DOMAIN_PAYMENT",
    "DOMAIN_COMMS",
]
