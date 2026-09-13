"""Import graph-preview provenance and rights-boundary regressions."""

from __future__ import annotations

import pytest

import services.imports.commit as commit_module
from services.imports.contracts import FieldMapping


class _Imports:
    async def get_session(self, tenant_id: str, import_id: str) -> dict:
        assert tenant_id == "tenant-a"
        assert import_id == "imp-1"
        return {
            "id": import_id,
            "tenant_id": tenant_id,
            "source_kind": "file_upload",
            "source_checksum": "batch-checksum",
        }

    async def get_latest_mapping(self, tenant_id: str, import_id: str) -> dict:
        return {
            "id": "mapping-1",
            "version": 4,
            "fields": [
                FieldMapping(
                    source_column="external_id",
                    primitive="entity",
                    target_field="external_id",
                ).model_dump(mode="json")
            ],
        }

    async def list_schemas(self, tenant_id: str, import_id: str) -> list[dict]:
        return [{"file_id": "file-1"}]


class _Storage:
    async def get_content(self, tenant_id: str, file_id: str) -> tuple[dict, bytes]:
        assert tenant_id == "tenant-a"
        assert file_id == "file-1"
        return (
            {
                "id": file_id,
                "filename": "entities.csv",
                "content_type": "text/csv",
                "sha256": "file-checksum",
                "size_bytes": 21,
                "created_at": "2026-09-09T00:00:00+00:00",
            },
            b"external_id\nentity-1\n",
        )


@pytest.mark.asyncio
async def test_graph_preview_contains_file_lineage_and_fail_closed_rights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(commit_module, "get_imports_repository", lambda: _Imports())
    monkeypatch.setattr(
        "services.imports.storage.get_import_storage", lambda: _Storage()
    )

    result = await commit_module.graph_preview("tenant-a", "imp-1")

    assert result["mapping_version"] == 4
    assert result["counts"] == {
        "vertices": 1,
        "edges": 0,
        "records": 1,
        "mapping_errors": 0,
    }
    lineage = result["lineage"]
    assert lineage["source_checksum"] == "batch-checksum"
    assert lineage["files"][0]["sha256"] == "file-checksum"
    assert lineage["file_rollup"] == [
        {
            "file_id": "file-1",
            "filename": "entities.csv",
            "sha256": "file-checksum",
            "row_count": 1,
            "mapped_record_count": 1,
            "mapping_error_count": 0,
        }
    ]
    assert lineage["rights_context"]["authorization_status"] == "not_evaluated"
    assert lineage["rights_context"]["activation_allowed"] is False
