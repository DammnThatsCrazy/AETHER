"""
Aether Repository — Import Engine (JSONB tables)

Tenant-scoped persistence for the Import Engine's session lifecycle and its
analyze/map/validate artifacts, over BaseRepository-shaped JSONB tables
(``import_sessions``, ``import_schemas``, ``import_mappings``,
``import_templates``, ``import_validations``, ``import_row_errors``). The raw
uploaded bytes live in the direct-SQL BYTEA repo ``import_files.py``.

Every read is tenant-scoped: a lookup by id that resolves to another tenant's
row raises ``NotFoundError`` rather than leaking it — tenant isolation is
absolute, enforced here at the repository boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import NotFoundError

# Cap on per-validation row errors persisted (the validator computes the full
# count; only this many individual error records are stored/returned).
MAX_ROW_ERRORS = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImportsRepository:
    """Facade over the Import Engine's JSONB tables."""

    def __init__(self) -> None:
        self.sessions = BaseRepository("import_sessions")
        self.schemas = BaseRepository("import_schemas")
        self.mappings = BaseRepository("import_mappings")
        self.templates = BaseRepository("import_templates")
        self.validations = BaseRepository("import_validations")
        self.row_errors = BaseRepository("import_row_errors")

    # ── sessions ───────────────────────────────────────────────────────────

    async def create_session(
        self,
        tenant_id: str,
        *,
        created_by: Optional[str] = None,
        source_kind: str = "file_upload",
    ) -> dict:
        import_id = f"imp_{uuid.uuid4().hex}"
        return await self.sessions.insert(
            import_id,
            {
                "tenant_id": tenant_id,
                "status": "created",
                "source_kind": source_kind,
                "file_count": 0,
                "row_count": None,
                "created_by": created_by,
            },
        )

    async def get_session(self, tenant_id: str, import_id: str) -> dict:
        row = await self.sessions.find_by_id(import_id)
        if row is None or row.get("tenant_id") != tenant_id:
            raise NotFoundError("import session")
        return row

    async def update_session(self, tenant_id: str, import_id: str, **patch: Any) -> dict:
        await self.get_session(tenant_id, import_id)  # tenant guard
        return await self.sessions.update(import_id, patch)

    async def set_status(self, tenant_id: str, import_id: str, status: str) -> dict:
        return await self.update_session(tenant_id, import_id, status=status)

    async def list_sessions(
        self, tenant_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        return await self.sessions.find_many(
            filters={"tenant_id": tenant_id}, limit=limit, offset=offset
        )

    # ── schemas ────────────────────────────────────────────────────────────

    async def save_schema(
        self, tenant_id: str, import_id: str, file_id: str, profile: dict
    ) -> dict:
        schema_id = f"imps_{uuid.uuid4().hex}"
        return await self.schemas.insert(
            schema_id,
            {
                "tenant_id": tenant_id,
                "import_id": import_id,
                "file_id": file_id,
                "profile": profile,
            },
        )

    async def list_schemas(self, tenant_id: str, import_id: str) -> list[dict]:
        rows = await self.schemas.find_many(
            filters={"tenant_id": tenant_id, "import_id": import_id}, limit=100
        )
        return rows

    async def get_schema_for_file(
        self, tenant_id: str, import_id: str, file_id: str
    ) -> Optional[dict]:
        rows = await self.schemas.find_many(
            filters={"tenant_id": tenant_id, "import_id": import_id, "file_id": file_id},
            limit=1,
        )
        return rows[0] if rows else None

    # ── mappings (versioned) ────────────────────────────────────────────────

    async def save_mapping(
        self, tenant_id: str, import_id: str, fields: list[dict]
    ) -> dict:
        existing = await self.mappings.find_many(
            filters={"tenant_id": tenant_id, "import_id": import_id}, limit=1000
        )
        version = len(existing) + 1
        mapping_id = f"impm_{uuid.uuid4().hex}"
        return await self.mappings.insert(
            mapping_id,
            {
                "tenant_id": tenant_id,
                "import_id": import_id,
                "version": version,
                "fields": fields,
            },
        )

    async def get_latest_mapping(
        self, tenant_id: str, import_id: str
    ) -> Optional[dict]:
        rows = await self.mappings.find_many(
            filters={"tenant_id": tenant_id, "import_id": import_id}, limit=1000
        )
        if not rows:
            return None
        return max(rows, key=lambda r: r.get("version", 0))

    async def get_mapping(self, tenant_id: str, mapping_id: str) -> dict:
        row = await self.mappings.find_by_id(mapping_id)
        if row is None or row.get("tenant_id") != tenant_id:
            raise NotFoundError("import mapping")
        return row

    # ── templates ────────────────────────────────────────────────────────────

    async def create_template(
        self,
        tenant_id: str,
        *,
        name: str,
        header_signature: str,
        fields: list[dict],
    ) -> dict:
        template_id = f"impt_{uuid.uuid4().hex}"
        return await self.templates.insert(
            template_id,
            {
                "tenant_id": tenant_id,
                "name": name,
                "header_signature": header_signature,
                "fields": fields,
            },
        )

    async def get_template(self, tenant_id: str, template_id: str) -> dict:
        row = await self.templates.find_by_id(template_id)
        if row is None or row.get("tenant_id") != tenant_id:
            raise NotFoundError("import template")
        return row

    async def list_templates(self, tenant_id: str, *, limit: int = 100) -> list[dict]:
        return await self.templates.find_many(
            filters={"tenant_id": tenant_id}, limit=limit
        )

    async def find_template_by_signature(
        self, tenant_id: str, header_signature: str
    ) -> Optional[dict]:
        rows = await self.templates.find_many(
            filters={"tenant_id": tenant_id, "header_signature": header_signature},
            limit=1,
        )
        return rows[0] if rows else None

    async def delete_template(self, tenant_id: str, template_id: str) -> bool:
        await self.get_template(tenant_id, template_id)  # tenant guard
        return await self.templates.delete(template_id)

    # ── validations ──────────────────────────────────────────────────────────

    async def save_validation(
        self, tenant_id: str, import_id: str, result: dict
    ) -> dict:
        validation_id = f"impv_{uuid.uuid4().hex}"
        # Persist the summary sans the (capped) errors list; errors go to their
        # own table so a large error set never bloats the validation row.
        summary = {k: v for k, v in result.items() if k != "errors"}
        stored = await self.validations.insert(
            validation_id,
            {"tenant_id": tenant_id, "import_id": import_id, **summary},
        )
        errors = (result.get("errors") or [])[:MAX_ROW_ERRORS]
        if errors:
            await self.row_errors.insert(
                f"impe_{uuid.uuid4().hex}",
                {
                    "tenant_id": tenant_id,
                    "import_id": import_id,
                    "validation_id": validation_id,
                    "errors": errors,
                },
            )
        return stored

    async def get_latest_validation(
        self, tenant_id: str, import_id: str
    ) -> Optional[dict]:
        rows = await self.validations.find_many(
            filters={"tenant_id": tenant_id, "import_id": import_id},
            limit=1000,
            sort_by="created_at",
            sort_order="desc",
        )
        return rows[0] if rows else None

    async def get_row_errors(
        self, tenant_id: str, validation_id: str
    ) -> list[dict]:
        rows = await self.row_errors.find_many(
            filters={"tenant_id": tenant_id, "validation_id": validation_id}, limit=10
        )
        if not rows:
            return []
        return rows[0].get("errors", [])


_repo: Optional[ImportsRepository] = None


def get_imports_repository() -> ImportsRepository:
    global _repo
    if _repo is None:
        _repo = ImportsRepository()
    return _repo
