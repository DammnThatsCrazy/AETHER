"""Export artifact repository, serialization safety, and manifest evidence."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))

from repositories.artifacts import (  # noqa: E402
    EXPORT_ARTIFACTS_DDL,
    MAX_ARTIFACT_BYTES,
    ArtifactRepository,
)
from services.export.manifest import build_manifest, sanitize_params  # noqa: E402
from services.export.service import serialize_rows  # noqa: E402
from shared.common.common import BadRequestError, NotFoundError  # noqa: E402


@pytest.fixture()
def repo():
    return ArtifactRepository()


async def _put(repo, tenant="tenant-a", content=b"hello world", **kw):
    return await repo.put(
        tenant,
        export_type=kw.pop("export_type", "audit_log"),
        filename=kw.pop("filename", "audit.json"),
        content=content,
        content_type=kw.pop("content_type", "application/json"),
        manifest=kw.pop("manifest", {"row_count": 1}),
        **kw,
    )


class TestArtifactRepository:
    async def test_put_get_verify_roundtrip(self, repo):
        art = await _put(repo)
        assert art["sha256"] and art["size_bytes"] == 11
        meta, content = await repo.get_content("tenant-a", art["id"])
        assert content == b"hello world"
        assert meta["sha256"] == art["sha256"]
        assert await repo.verify("tenant-a", art["id"]) is True

    async def test_size_cap_rejected(self, repo):
        with pytest.raises(BadRequestError):
            await _put(repo, content=b"x" * (MAX_ARTIFACT_BYTES + 1))

    async def test_tenant_isolation(self, repo):
        art = await _put(repo, tenant="tenant-a")
        with pytest.raises(NotFoundError):
            await repo.get_meta("tenant-b", art["id"])
        with pytest.raises(NotFoundError):
            await repo.get_content("tenant-b", art["id"])
        assert await repo.list_for_tenant("tenant-b") == []

    async def test_soft_delete_leaves_tombstone(self, repo):
        art = await _put(repo)
        tomb = await repo.soft_delete("tenant-a", art["id"])
        assert tomb["deleted_at"]
        # Content refused, but the tombstone metadata (sha) survives.
        with pytest.raises(NotFoundError):
            await repo.get_content("tenant-a", art["id"])
        meta = await repo.get_meta("tenant-a", art["id"])
        assert meta["sha256"] == art["sha256"]

    async def test_expire_sweep_physically_deletes(self, repo):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        expired = await _put(repo, expires_at=past)
        fresh = await _put(repo, expires_at=future)
        swept = await repo.expire_sweep()
        assert swept["swept"] == 1
        with pytest.raises(NotFoundError):
            await repo.get_content("tenant-a", expired["id"])
        # tombstone remains with manifest + checksum
        tomb = await repo.get_meta("tenant-a", expired["id"])
        assert tomb["deleted_at"] and tomb["sha256"]
        # fresh artifact unaffected
        _, content = await repo.get_content("tenant-a", fresh["id"])
        assert content == b"hello world"

    async def test_expired_content_refused_even_before_sweep(self, repo):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        art = await _put(repo, expires_at=past)
        with pytest.raises(NotFoundError):
            await repo.get_content("tenant-a", art["id"])


class TestDdlParity:
    def test_repo_ddl_matches_migration(self):
        migration = (
            BACKEND / "alembic" / "versions" / "20260713_platform_control_plane.py"
        ).read_text(encoding="utf-8")
        match = re.search(
            r'EXPORT_ARTIFACTS_DDL = """\n(.*?)"""', migration, re.DOTALL
        )
        assert match, "migration lost its EXPORT_ARTIFACTS_DDL constant"
        assert match.group(1).strip() == EXPORT_ARTIFACTS_DDL.strip()


class TestSerialization:
    def test_csv_formula_injection_neutralized(self):
        rows = [
            {"name": "=SUM(A1:A9)", "note": "+cmd", "id": "@x", "neg": "-1+1", "ok": "safe"}
        ]
        content, content_type, cols = serialize_rows(rows, "csv")
        body = content.decode()
        assert content_type == "text/csv"
        assert "'=SUM(A1:A9)" in body
        assert "'+cmd" in body
        assert "'@x" in body
        assert "'-1+1" in body
        assert ",safe" in body or "safe" in body.splitlines()[1]

    def test_json_and_ndjson(self):
        rows = [{"a": 1}, {"a": 2}]
        j, jt, _ = serialize_rows(rows, "json")
        assert jt == "application/json" and b'"a": 1' in j
        n, nt, _ = serialize_rows(rows, "ndjson")
        assert nt == "application/x-ndjson" and len(n.splitlines()) == 2

    def test_unknown_format_rejected(self):
        with pytest.raises(BadRequestError):
            serialize_rows([], "xlsx")


class TestManifest:
    def test_manifest_evidence(self):
        m = build_manifest(
            b"data",
            export_type="audit_log",
            tenant_id="tenant-a",
            params={"format": "json", "api_key": "SECRET"},
            correlation_id="corr-1",
            row_count=3,
            per_source={"agent_audit": 3},
        )
        assert m["sha256"] and m["size_bytes"] == 4
        assert m["generator_version"] != "unknown"
        assert m["params"]["api_key"] == "[redacted]"
        assert m["row_count"] == 3 and m["correlation_id"] == "corr-1"

    def test_sanitize_params(self):
        clean = sanitize_params({"webhook_secret": "x", "window": "24h"})
        assert clean == {"webhook_secret": "[redacted]", "window": "24h"}
