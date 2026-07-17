"""Product Catalog repositories — BaseRepository JSONB pattern.

Tables are auto-created JSONB tables (see repositories/repos.py); in the local
environment the store is in-memory. Record IDs are tenant-qualified
(``{tenant_id}:{stable_id}``) so identical stable_ids never collide across
tenants, and every read path re-checks the tenant before returning a row.
NO alembic migrations — BaseRepository owns the schema.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository

from services.product_catalog.models import CatalogNode, MappingProposal, MappingRule

# Persistence-envelope keys added by BaseRepository that are not part of the
# pydantic contracts (which are extra="forbid").
_ENVELOPE_KEYS = ("id", "created_at", "updated_at")


def _strip_envelope(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _ENVELOPE_KEYS}


class _TenantScopedRepository(BaseRepository):
    """Tenant-qualified IDs + tenant-checked reads over the JSONB base."""

    @staticmethod
    def _record_id(tenant_id: str, natural_id: str) -> str:
        return f"{tenant_id}:{natural_id}"

    async def get_scoped(self, tenant_id: str, natural_id: str) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(self._record_id(tenant_id, natural_id))
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return _strip_envelope(record)

    async def list_scoped(
        self,
        tenant_id: str,
        extra_filters: Optional[dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id, **(extra_filters or {})}
        rows = await self.find_many(filters=filters, limit=limit, offset=offset)
        return [_strip_envelope(r) for r in rows]

    async def upsert_scoped(self, tenant_id: str, natural_id: str, data: dict[str, Any]) -> dict[str, Any]:
        data = {**data, "tenant_id": tenant_id}
        stored = await self.insert(self._record_id(tenant_id, natural_id), data)
        return _strip_envelope(stored)

    async def delete_scoped(self, tenant_id: str, natural_id: str) -> bool:
        # Guard: never delete another tenant's row via a crafted natural_id.
        if await self.get_scoped(tenant_id, natural_id) is None:
            return False
        return await self.delete(self._record_id(tenant_id, natural_id))


class ProductCatalogNodeRepository(_TenantScopedRepository):
    def __init__(self) -> None:
        super().__init__("product_catalog_nodes")

    async def upsert_node(self, tenant_id: str, node: CatalogNode) -> CatalogNode:
        stored = await self.upsert_scoped(tenant_id, node.stable_id, node.model_dump())
        return CatalogNode(**stored)

    async def get_node(self, tenant_id: str, stable_id: str) -> Optional[CatalogNode]:
        record = await self.get_scoped(tenant_id, stable_id)
        return CatalogNode(**record) if record else None

    async def list_nodes(
        self,
        tenant_id: str,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CatalogNode]:
        extra: dict[str, Any] = {}
        if kind:
            extra["kind"] = kind
        if status:
            extra["status"] = status
        rows = await self.list_scoped(tenant_id, extra, limit=limit, offset=offset)
        return [CatalogNode(**r) for r in rows]


class ProductMappingRuleRepository(_TenantScopedRepository):
    def __init__(self) -> None:
        super().__init__("product_mapping_rules")

    async def upsert_rule(self, tenant_id: str, rule: MappingRule) -> MappingRule:
        stored = await self.upsert_scoped(tenant_id, rule.rule_id, rule.model_dump())
        return MappingRule(**stored)

    async def list_rules(
        self,
        tenant_id: str,
        match_kind: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MappingRule]:
        extra: dict[str, Any] = {"match_kind": match_kind} if match_kind else {}
        rows = await self.list_scoped(tenant_id, extra, limit=limit, offset=offset)
        return [MappingRule(**r) for r in rows]


class ProductMappingProposalRepository(_TenantScopedRepository):
    def __init__(self) -> None:
        super().__init__("product_mapping_proposals")

    async def upsert_proposal(self, tenant_id: str, proposal: MappingProposal) -> MappingProposal:
        stored = await self.upsert_scoped(tenant_id, proposal.rule_id, proposal.model_dump())
        return MappingProposal(**stored)

    async def list_proposals(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MappingProposal]:
        extra: dict[str, Any] = {"status": status} if status else {}
        rows = await self.list_scoped(tenant_id, extra, limit=limit, offset=offset)
        return [MappingProposal(**r) for r in rows]
