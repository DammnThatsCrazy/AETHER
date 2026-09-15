"""Durable repositories for the customer SDK fleet and remote configuration."""

from __future__ import annotations

from typing import Optional

from repositories.repos import BaseRepository

#: Marks a row in ``sdk_installations`` as a registered site's install
#: handshake rather than an installed SDK. Owned here because this module owns
#: the table's row shapes; ``services/sdk_distribution`` writes it and the
#: fleet reads below exclude it.
SITE_INSTALL_RECORD_TYPE = "site_install"


class SDKInstallationRepository(BaseRepository):
    """Authoritative installation registry; heartbeat caches are not inventory.

    Two kinds of row share this table, because both answer "an SDK is deployed
    somewhere for this tenant":

      * **fleet** rows — an installed SDK, keyed by the installation id the SDK
        generates, carrying heartbeats and health scores;
      * **site install** rows — a registered site's install handshake, keyed by
        the public ``site_id`` (see ``services/sdk_distribution``), carrying
        which loader milestones were observed.

    Only the first kind belongs in fleet health. A site install has no
    heartbeat by design — its signals are one-shot, at install time — so
    counting it would report every correctly installed site as a silent SDK.
    ``list_for_tenant`` is therefore the raw read, and fleet callers use
    ``list_fleet_for_tenant``.
    """

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

    async def list_fleet_for_tenant(self, tenant_id: str, limit: int = 1000) -> list[dict]:
        """Installed SDKs only — site-install rows are not fleet members.

        Filtered here rather than in the query because ``find_many``'s filters
        are JSONB text equality and cannot express "record_type is absent or is
        not site_install" over rows written before the field existed. Rows with
        no ``record_type`` are legacy fleet installations and must stay counted.
        """
        records = await self.list_for_tenant(tenant_id, limit=limit)
        return [
            r
            for r in records
            if r.get("record_type") != SITE_INSTALL_RECORD_TYPE
        ]


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
