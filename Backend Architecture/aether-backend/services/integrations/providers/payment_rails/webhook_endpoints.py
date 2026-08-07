"""Durable webhook endpoint registry.

A public provider webhook URL is ``/…/payment-rails/{provider}/{endpoint_id}``.
The ``endpoint_id`` is high-entropy, non-sequential, durable, revocable and bound
to exactly one (tenant, provider, environment). Resolution happens server-side —
no tenant id is ever accepted from a request header or body. The id alone is not
authentication; the provider signature is still verified downstream.
"""

from __future__ import annotations

import secrets
from typing import Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.payment_rails.webhook_endpoints")

ENDPOINT_TABLE = "payment_webhook_endpoints"
_ID_PREFIX = "whe_"


class EndpointState:
    ACTIVE = "active"
    REVOKED = "revoked"


_PATH_TEMPLATE = "/v1/integrations/webhooks/payment-rails/{provider}/{endpoint_id}"


class _WebhookEndpointRepo(BaseRepository):
    def __init__(self, table: str = ENDPOINT_TABLE) -> None:
        super().__init__(table)


_SAFE_FIELDS = (
    "provider",
    "environment",
    "state",
    "created_at",
    "created_by",
    "revoked_at",
    "revoked_by",
)


class WebhookEndpointRegistry:
    """Create / resolve / rotate / revoke public webhook endpoints.

    Generic over the webhook surface: the payment-rails instance below uses the
    defaults; other surfaces (e.g. connectors) instantiate with their own
    ``table`` / ``id_prefix`` / ``path_template``. Semantics are identical
    everywhere — server-side tenant resolution, uniform-None misses, revocation.
    """

    def __init__(
        self,
        repo: Optional[_WebhookEndpointRepo] = None,
        *,
        table: str = ENDPOINT_TABLE,
        id_prefix: str = _ID_PREFIX,
        path_template: str = _PATH_TEMPLATE,
    ) -> None:
        self._repo = repo or _WebhookEndpointRepo(table)
        self._id_prefix = id_prefix
        self._path_template = path_template

    def _new_endpoint_id(self) -> str:
        # 32 random bytes → 64 hex chars; non-sequential, unguessable.
        return self._id_prefix + secrets.token_hex(32)

    async def create(
        self, tenant_id: str, provider: str, environment: str, *, created_by: str
    ) -> dict:
        endpoint_id = self._new_endpoint_id()
        data = {
            "tenant_id": tenant_id,
            "provider": provider,
            "environment": environment,
            "state": EndpointState.ACTIVE,
            "created_by": created_by,
            "revoked_at": None,
            "revoked_by": None,
        }
        await self._repo.insert(endpoint_id, data)
        logger.info(
            "webhook endpoint created tenant=%s provider=%s env=%s", tenant_id, provider, environment
        )
        return self._public(endpoint_id, data)

    async def resolve(self, endpoint_id: str, provider: str) -> Optional[dict]:
        """Return ``{tenant_id, provider, environment}`` for an ACTIVE endpoint
        whose provider matches the route, else ``None`` (uniform — never leaks
        whether the id, tenant, or provider exists)."""
        if not endpoint_id or not endpoint_id.startswith(self._id_prefix):
            return None
        row = await self._repo.find_by_id(endpoint_id)
        if row is None:
            return None
        if row.get("state") != EndpointState.ACTIVE:
            return None
        if row.get("provider") != provider:
            return None
        return {
            "tenant_id": row["tenant_id"],
            "provider": row["provider"],
            "environment": row["environment"],
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
        self, tenant_id: str, provider: str, environment: str, *, actor: str
    ) -> dict:
        """Revoke any active endpoints for the slot and mint a fresh one."""
        for row in await self._active_for(tenant_id, provider, environment):
            await self.revoke(tenant_id, row["id"], actor=actor)
        return await self.create(tenant_id, provider, environment, created_by=actor)

    async def list_for(self, tenant_id: str, provider: Optional[str] = None) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        rows = await self._repo.find_many(filters=filters, limit=200)
        return [self._public(r["id"], r) for r in rows]

    async def _active_for(
        self, tenant_id: str, provider: str, environment: str
    ) -> list[dict]:
        return await self._repo.find_many(
            filters={
                "tenant_id": tenant_id,
                "provider": provider,
                "environment": environment,
                "state": EndpointState.ACTIVE,
            },
            limit=50,
        )

    def _public(self, endpoint_id: str, row: dict) -> dict:
        view = {"endpoint_id": endpoint_id}
        view.update({f: row.get(f) for f in _SAFE_FIELDS if f in row})
        # Safe public webhook path suffix (never includes a secret).
        view["webhook_path"] = self._path_template.format(
            provider=row.get("provider"), endpoint_id=endpoint_id
        )
        return view


# Module singleton — durable state lives in the DB.
webhook_endpoint_registry = WebhookEndpointRegistry()


__all__ = ["WebhookEndpointRegistry", "webhook_endpoint_registry", "EndpointState", "ENDPOINT_TABLE"]
