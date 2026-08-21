"""Cross-surface exporters route targeting packages + evidence packs through the
durable export service.

Proves each new exporter is registered, is read-only and tenant-scoped, and that
the shared generate handler turns its rows into a verified, checksummed artifact.
The exporters never build or mutate — they export already-persisted records.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("AETHER_ENV", "local")

from repositories import artifacts as artifacts_mod  # noqa: E402
from services.export.service import (  # noqa: E402
    EXPORTERS,
    _governance_evidence_pack_exporter as governance_evidence_pack_exporter,
    _targeting_package_exporter as targeting_package_exporter,
    generate_export_artifact,
)
from services.jobs.handlers import JobContext  # noqa: E402

TENANT = "tenant-domain-export"
OTHER = "tenant-domain-export-other"


@pytest.fixture(autouse=True)
def _fresh_artifact_store(monkeypatch):
    # Fresh artifact store per test. The exporters self-register by decorator on
    # module import, so no registration call is needed here.
    monkeypatch.setattr(artifacts_mod, "_repo", artifacts_mod.ArtifactRepository())
    yield


def _ctx(job_id="job-dx-1", tenant=TENANT):
    async def heartbeat():
        return True

    events: list[tuple[str, dict]] = []

    async def emit_event(event_type: str, payload: dict):
        events.append((event_type, payload))

    ctx = JobContext(
        job_id=job_id,
        tenant_id=tenant,
        correlation_id="corr-dx-1",
        worker_id="test_worker",
        heartbeat=heartbeat,
        emit_event=emit_event,
    )
    return ctx, events


async def _seed_targeting_package(tenant: str, export_id: str) -> dict:
    from services.targeting_intelligence.repository import get_targeting_repositories

    return await get_targeting_repositories().exports.save(
        tenant,
        {
            "exportId": export_id,
            "campaignId": "camp-1",
            "includeClusterIds": ["c1", "c2"],
            "excludeClusterIds": ["c9"],
            "holdoutClusterIds": [],
            "implementationNotes": ["external only"],
        },
    )


# ── registration ─────────────────────────────────────────────────────────────


def test_domain_exporters_registered():
    # Both self-register by decorator on module import, alongside the reference
    # audit_log exporter.
    assert "targeting_package" in EXPORTERS
    assert "governance_evidence_pack" in EXPORTERS
    assert "audit_log" in EXPORTERS


# ── targeting packages ───────────────────────────────────────────────────────


async def test_targeting_exporter_lists_tenant_packages():
    await _seed_targeting_package(TENANT, "tex_a")
    await _seed_targeting_package(TENANT, "tex_b")
    payload = await targeting_package_exporter(TENANT, {})
    ids = {r["exportId"] for r in payload.rows}
    assert {"tex_a", "tex_b"} <= ids
    assert payload.per_source["targeting_export_packages"] == len(payload.rows)


async def test_targeting_exporter_selects_by_export_id():
    await _seed_targeting_package(TENANT, "tex_single")
    payload = await targeting_package_exporter(TENANT, {"export_id": "tex_single"})
    assert len(payload.rows) == 1
    assert payload.rows[0]["exportId"] == "tex_single"


async def test_targeting_exporter_is_tenant_scoped():
    await _seed_targeting_package(TENANT, "tex_owned")
    # Another tenant's listing never sees it.
    other_rows = (await targeting_package_exporter(OTHER, {})).rows
    assert all(r["exportId"] != "tex_owned" for r in other_rows)
    # A cross-tenant id lookup is a 404, not a silent leak.
    with pytest.raises(Exception) as exc:
        await targeting_package_exporter(OTHER, {"export_id": "tex_owned"})
    assert type(exc.value).__name__ == "NotFoundError"


async def test_targeting_export_produces_verified_artifact():
    await _seed_targeting_package(TENANT, "tex_artifact")
    ctx, events = _ctx()
    outcome = await generate_export_artifact(
        {"export_type": "targeting_package", "params": {"format": "ndjson"}}, ctx
    )
    assert outcome.status == "succeeded", outcome.error
    assert outcome.result["sha256"]
    assert outcome.result["download_url"].endswith("/download")
    assert any(evt == "export.ready" for evt, _ in events)
    repo = artifacts_mod.get_artifact_repository()
    assert await repo.verify(TENANT, outcome.result["artifact_id"]) is True
    meta, content = await repo.get_content(TENANT, outcome.result["artifact_id"])
    assert meta["manifest"]["export_type"] == "targeting_package"
    assert b"tex_artifact" in content


# ── governance evidence packs ────────────────────────────────────────────────


async def test_evidence_pack_exporter_reads_tenant_packs():
    from services.security.evidence_packs import evidence_pack_service

    pack = await evidence_pack_service.generate(
        pack_type="access_control", requested_by="op-1", tenant_id=TENANT
    )
    payload = await governance_evidence_pack_exporter(
        TENANT, {"pack_type": "access_control"}
    )
    ids = {r.get("evidence_pack_id") for r in payload.rows}
    assert pack.evidence_pack_id in ids


async def test_evidence_pack_exporter_is_tenant_scoped():
    from services.security.evidence_packs import evidence_pack_service

    pack = await evidence_pack_service.generate(
        pack_type="access_control", requested_by="op-1", tenant_id=TENANT
    )
    other = await governance_evidence_pack_exporter(OTHER, {})
    assert all(r.get("evidence_pack_id") != pack.evidence_pack_id for r in other.rows)


async def test_evidence_pack_exporter_unknown_id_is_404():
    with pytest.raises(Exception) as exc:
        await governance_evidence_pack_exporter(TENANT, {"evidence_pack_id": "evpack_missing"})
    assert type(exc.value).__name__ == "NotFoundError"
