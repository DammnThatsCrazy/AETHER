"""Import Engine storage adapter — the object-store seam.

The Import Engine holds uploaded bytes behind an ``ImportStorageAdapter`` so the
default Postgres-BYTEA implementation can be swapped for S3 without touching the
service. Today the only shared durable medium in the stack is Postgres (no
object store exists; ECS tasks have no shared filesystem), so
``PostgresImportStorage`` delegates to ``repositories/import_files.py``.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from repositories.import_files import get_import_file_repository


@runtime_checkable
class ImportStorageAdapter(Protocol):
    """The byte-storage contract the Import Engine depends on (S3 seam)."""

    async def put(
        self,
        tenant_id: str,
        *,
        import_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict: ...

    async def get_meta(self, tenant_id: str, file_id: str) -> dict: ...

    async def get_content(self, tenant_id: str, file_id: str) -> tuple[dict, bytes]: ...

    async def list_for_import(self, tenant_id: str, import_id: str) -> list[dict]: ...


class PostgresImportStorage:
    """Default adapter — tenant-scoped Postgres BYTEA (in-memory in local mode)."""

    def __init__(self) -> None:
        self._repo = get_import_file_repository()

    async def put(
        self,
        tenant_id: str,
        *,
        import_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict:
        return await self._repo.put(
            tenant_id,
            import_id=import_id,
            filename=filename,
            content=content,
            content_type=content_type,
        )

    async def get_meta(self, tenant_id: str, file_id: str) -> dict:
        return await self._repo.get_meta(tenant_id, file_id)

    async def get_content(self, tenant_id: str, file_id: str) -> tuple[dict, bytes]:
        return await self._repo.get_content(tenant_id, file_id)

    async def list_for_import(self, tenant_id: str, import_id: str) -> list[dict]:
        return await self._repo.list_for_import(tenant_id, import_id)


_adapter: Optional[ImportStorageAdapter] = None


def get_import_storage() -> ImportStorageAdapter:
    global _adapter
    if _adapter is None:
        _adapter = PostgresImportStorage()
    return _adapter
