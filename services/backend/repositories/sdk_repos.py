"""Durable repositories for the customer SDK fleet and remote configuration."""

from __future__ import annotations

from typing import Optional

from repositories.repos import BaseRepository


class SDKInstallationRepository(BaseRepository):
    """Authoritative installation registry; heartbeat caches are not inventory."""

    def __init__(self) -> None:
        super().__init__("sdk_installations")

    @staticmethod
    def record_id(tenant_id: str, installation_id: str) -> str:
        return f"{tenant_id}:{installation_id}"

    async def get(self, tenant_id: str, installation_id: str) -> Optional[dict]:
        return await self.find_by_id(self.record_id(tenant_id, installation_id))

    async def upsert(self, record: dict) -> dict:
        record_id = self.record_id(record["tenant_id"], record["installation_id"])
        existing = await self.find_by_id(record_id)
        if existing:
            return await self.update(record_id, record)
        return await self.insert(record_id, record)

    async def list_for_tenant(self, tenant_id: str, limit: int = 1000) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)


class SDKManifestVersionRepository(BaseRepository):
    """Immutable, signed manifest versions."""

    def __init__(self) -> None:
        super().__init__("sdk_manifest_versions")

    @staticmethod
    def record_id(tenant_id: str, version: str) -> str:
        return f"{tenant_id}:{version}"

    async def create_version(self, record: dict) -> dict:
        return await self.insert(
            self.record_id(record["tenant_id"], record["manifest_version"]), record
        )

    async def get_version(self, tenant_id: str, version: str) -> Optional[dict]:
        return await self.find_by_id(self.record_id(tenant_id, version))

    async def list_versions(self, tenant_id: str, limit: int = 1000) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)


class SDKManifestStateRepository(BaseRepository):
    """Per-tenant active/previous manifest pointers."""

    def __init__(self) -> None:
        super().__init__("sdk_manifest_states")

    async def get(self, tenant_id: str) -> Optional[dict]:
        return await self.find_by_id(tenant_id)

    async def upsert(self, tenant_id: str, record: dict) -> dict:
        existing = await self.find_by_id(tenant_id)
        record = {**record, "tenant_id": tenant_id}
        if existing:
            return await self.update(tenant_id, record)
        return await self.insert(tenant_id, record)
