"""Tenant-scoped repositories for the capability catalog (PR 2, Phase A).

Both subclass the governance ``_ScopedRepo`` (JSONB-backed in production, in-memory for
local/dev/tests via ``_IN_MEMORY_STORES``). Store names match the alembic tables
(``20260805_capability_catalog``) and their ``storage_policies.yaml`` ``resource_type``
entries exactly — the storage-policy gate derives its inventory from those table names.

Single-record reads are fail-closed at the service layer (tenant compared, NotFound on
mismatch) so a capability/installation id cannot leak the existence of another tenant's row.
"""

from __future__ import annotations

from typing import Any, Optional

from services.security.repositories import _ScopedRepo

CAPABILITY_CATALOG_TABLE = "capability_catalog"
CAPABILITY_INSTALLATIONS_TABLE = "capability_installations"


class CapabilityCatalogRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__(CAPABILITY_CATALOG_TABLE)

    async def list_capabilities(
        self,
        tenant_id: str,
        *,
        provider: Optional[str] = None,
        server_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        extra: dict[str, Any] = {}
        if provider:
            extra["provider"] = provider
        if server_name:
            extra["server_name"] = server_name
        if tool_name:
            extra["tool_name"] = tool_name
        return await self.list_for_tenant(tenant_id, limit=limit, offset=offset, extra=extra or None)


class CapabilityInstallationRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__(CAPABILITY_INSTALLATIONS_TABLE)

    async def list_installations(
        self,
        tenant_id: str,
        *,
        agent_id: Optional[str] = None,
        provider: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        extra: dict[str, Any] = {}
        if agent_id:
            extra["agent_id"] = agent_id
        if provider:
            extra["provider"] = provider
        return await self.list_for_tenant(tenant_id, limit=limit, offset=offset, extra=extra or None)
