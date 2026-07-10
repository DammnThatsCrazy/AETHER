"""End-to-end export flow: request → durable job → handler → verified artifact → download refusals."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))

from repositories import artifacts as artifacts_mod  # noqa: E402
from services.export import service as export_service  # noqa: E402
from services.jobs.handlers import (  # noqa: E402
    HANDLER_REGISTRY,
    JobContext,
    unregister_handler,
)
from shared.common.common import BadRequestError  # noqa: E402

TENANT = "tenant-export-flow"


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    # Fresh artifact store per test and freshly-registered handlers.
    monkeypatch.setattr(artifacts_mod, "_repo", artifacts_mod.ArtifactRepository())
    unregister_handler("export.generate")
    unregister_handler("export.expire_sweep")
    export_service.register_export_handlers()
    yield
    unregister_handler("export.generate")
    unregister_handler("export.expire_sweep")


def _ctx(job_id="job-1", tenant=TENANT):
    async def heartbeat():
        return True

    events: list[tuple[str, dict]] = []

    async def emit_event(event_type: str, payload: dict):
        events.append((event_type, payload))

    ctx = JobContext(
        job_id=job_id,
        tenant_id=tenant,
        correlation_id="corr-export-1",
        heartbeat=heartbeat,
        emit_event=emit_event,
    )
    return ctx, events


async def test_request_export_enqueues_durable_job():
    result = await export_service.request_export(
        TENANT,
        export_type="audit_log",
        params={"format": "json"},
        requested_by="user-1",
        correlation_id="corr-export-1",
    )
    assert result["job_id"] and result["status_url"].startswith("/v1/jobs/")

    # Idempotency: identical request in the same hour replays the same job.
    again = await export_service.request_export(
        TENANT,
        export_type="audit_log",
        params={"format": "json"},
        requested_by="user-1",
        correlation_id="corr-export-2",
    )
    assert again["job_id"] == result["job_id"]
    assert again["replayed"] is True


async def test_unknown_export_type_rejected():
    with pytest.raises(BadRequestError):
        await export_service.request_export(
            TENANT, export_type="nope", params={}, requested_by=None, correlation_id=None
        )


async def test_generate_handler_produces_verified_artifact():
    handler = HANDLER_REGISTRY["export.generate"]
    ctx, events = _ctx()
    outcome = await handler({"export_type": "audit_log", "params": {"format": "csv"}}, ctx)
    assert outcome.status == "succeeded", outcome.error
    artifact_id = outcome.result["artifact_id"]
    assert outcome.result["sha256"]
    assert outcome.result["download_url"].endswith("/download")
    assert any(evt == "export.ready" for evt, _ in events)

    repo = artifacts_mod.get_artifact_repository()
    meta, content = await repo.get_content(TENANT, artifact_id)
    assert meta["manifest"]["export_type"] == "audit_log"
    assert meta["manifest"]["generator_version"]
    assert await repo.verify(TENANT, artifact_id) is True
    # CSV artifact really is CSV (header line exists even for empty stores)
    assert meta["content_type"] == "text/csv"
    assert isinstance(content, bytes)


async def test_generate_handler_fails_on_unknown_exporter():
    handler = HANDLER_REGISTRY["export.generate"]
    ctx, _ = _ctx()
    outcome = await handler({"export_type": "ghost", "params": {}}, ctx)
    assert outcome.status == "failed"
    assert "no exporter registered" in (outcome.error or "")


async def test_expire_sweep_handler_reports_counts():
    handler = HANDLER_REGISTRY["export.expire_sweep"]
    ctx, _ = _ctx()
    outcome = await handler({}, ctx)
    assert outcome.status == "succeeded"
    assert "swept" in outcome.result


async def test_artifact_not_visible_cross_tenant():
    handler = HANDLER_REGISTRY["export.generate"]
    ctx, _ = _ctx()
    outcome = await handler({"export_type": "audit_log", "params": {"format": "json"}}, ctx)
    artifact_id = outcome.result["artifact_id"]
    repo = artifacts_mod.get_artifact_repository()
    from shared.common.common import NotFoundError

    with pytest.raises(NotFoundError):
        await repo.get_content("tenant-other", artifact_id)
