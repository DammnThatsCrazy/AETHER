"""DB-free tests for the Data Exchange reports plane (M5).

Covers the M5 deliverables without any Postgres or a durable-job runtime:

- ``request_report`` creates the egress ``data_artifacts`` intent row
  (``artifact_type="report"``, status ``generating``) and enqueues the
  ``report.generate`` durable job (request → row → job-enqueue round-trip);
- unknown templates fail fast (``BadRequestError``) before any enqueue;
- ``render_report`` renders PDF bytes (injectable renderer), writes them to the
  shared ObjectStore at the tenant-scoped key, records the verified checksum in
  the render-state store, and marks the artifact ``available``;
- download/list/detail/delete semantics and cross-tenant refusal;
- ``report.generate`` handler shapes (JobOutcome succeeded/failed);
- the reportlab renderer is deterministic — two renders of one tiny fixture with
  a fixed ``generated_at`` are byte-equal.  reportlab is absent from the dev
  venv until the coordinator adds the pyproject extra, so every test that
  touches the real renderer gates on ``pytest.importorskip("reportlab")``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from repositories.data_artifacts import (
    DataArtifactRepository,
    reset_data_artifact_in_memory_store,
)
from services.data_exchange.contracts import ReportSpecContract
from services.jobs.handlers import HANDLER_REGISTRY, unregister_handler
from services.data_exchange.authz import require_data_exchange
from services.reports import (
    delete_report,
    download_report,
    get_report_detail,
    list_report_artifacts,
    mark_report_failed,
    render_report,
    request_report,
    reports_router,
)
from services.reports.jobs_reports import REPORT_JOB_TYPE, generate_report_artifact
from services.reports.renderers import (
    DEFAULT_TEMPLATE,
    ReportRenderError,
    resolve_template_name,
)
from services.reports.renderers.pdf import _default_template_sections
from services.reports.routes import (
    REPORT_CREATE_REQUIRED_GRANTS,
    REPORT_DELETE_REQUIRED_GRANTS,
    REPORT_DOWNLOAD_REQUIRED_GRANTS,
    REPORT_READ_REQUIRED_GRANTS,
)
from services.reports.service import (
    get_report_render_state_repository,
    reset_report_render_store,
)
from shared.auth.auth import Role, TenantContext
from shared.common.common import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from shared.storage.object_store import InMemoryObjectStore

TENANT_A = "tnt_a"
TENANT_B = "tnt_b"
PDF_BYTES = b"%PDF-1.4\n% determinism-fake-renderer\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    """Guarantee the in-memory repository/render-state backends regardless of
    DATABASE_URL / boto3 presence in the surrounding environment."""

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    monkeypatch.setattr("services.reports.service.get_pool", _no_pool)
    reset_data_artifact_in_memory_store()
    reset_report_render_store()
    yield
    reset_data_artifact_in_memory_store()
    reset_report_render_store()


class FakeJobsService:
    """Records enqueue calls; never touches a real jobs repository."""

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self._seq = 0

    async def enqueue(self, tenant_id: str, job_type: str, payload: dict, **kwargs: Any) -> dict:
        self._seq += 1
        job_id = f"job_{self._seq}"
        self.enqueued.append(
            {
                "tenant_id": tenant_id,
                "job_type": job_type,
                "payload": payload,
                "kwargs": kwargs,
                "id": job_id,
            }
        )
        return {"id": job_id, "tenant_id": tenant_id, "job_type": job_type,
                "status": "queued", "replayed": False}


def _spec(
    report_id: str,
    tenant_id: str = TENANT_A,
    *,
    resource: str = "audit-log",
    template: str = DEFAULT_TEMPLATE,
    **overrides: Any,
) -> ReportSpecContract:
    kwargs: dict[str, Any] = {
        "report_id": report_id,
        "tenant_id": tenant_id,
        "resource": resource,
        "scope": {"family": "recommendation_audit"},
        "temporal": {"start": "2026-09-01", "end": "2026-09-05"},
        "filters": {},
        "display_timezone": "UTC",
        "template": template,
        "include_methodology": True,
        "include_provenance_summary": True,
        "requested_by": "user-1",
    }
    kwargs.update(overrides)
    return ReportSpecContract(**kwargs)


def _fake_renderer(*args: Any, **kwargs: Any) -> bytes:
    return PDF_BYTES


async def _request(
    report_id: str,
    *,
    tenant_id: str = TENANT_A,
    repo: DataArtifactRepository,
    store: InMemoryObjectStore,
    jobs: FakeJobsService,
    template: str = DEFAULT_TEMPLATE,
) -> tuple[dict, ReportSpecContract]:
    spec = _spec(report_id, tenant_id, template=template)
    result = await request_report(
        tenant_id,
        spec,
        requested_by="user-1",
        correlation_id="corr-1",
        artifact_repo=repo,
        object_store=store,
        jobs_service=jobs,
    )
    return result, spec


# ── request → row → job-enqueue round-trip ──────────────────────────────────


@pytest.mark.asyncio
async def test_request_report_creates_intent_row_and_enqueues_job() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()

    result, spec = await _request("rep_1", repo=repo, store=store, jobs=jobs)

    assert result["report_id"] == "rep_1"
    assert result["status"] == "generating"
    assert result["artifact_id"].startswith("rep_")
    assert result["job_id"] == "job_1"

    # exactly one durable job enqueued for report.generate
    assert len(jobs.enqueued) == 1
    enqueued = jobs.enqueued[0]
    assert enqueued["job_type"] == "report.generate"
    assert enqueued["payload"]["report_id"] == "rep_1"
    assert enqueued["payload"]["artifact_id"] == result["artifact_id"]
    assert enqueued["payload"]["spec"]["resource"] == "audit-log"

    # the intent row is on the data_artifacts envelope
    row = await repo.get(TENANT_A, result["artifact_id"])
    assert row["direction"] == "egress"
    assert row["artifact_type"] == "report"
    assert row["status"] == "generating"
    assert row["canonical_id"] == "rep_1"
    assert row["job_id"] == "job_1"
    assert row["format"] == "pdf"
    assert row["content_type"] == "application/pdf"
    assert row["object_key"].startswith(f"data-exchange/{TENANT_A}/egress/")
    assert row["manifest"]["template"] == DEFAULT_TEMPLATE

    # list by artifact_type finds exactly the one report
    report_rows = await repo.list_for_tenant(
        TENANT_A, direction="egress", artifact_type="report"
    )
    assert len(report_rows) == 1
    assert report_rows[0]["artifact_id"] == result["artifact_id"]


@pytest.mark.asyncio
async def test_request_report_refuses_cross_tenant_spec() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    spec = _spec("rep_x", tenant_id=TENANT_B)  # spec claims another tenant
    with pytest.raises(BadRequestError):
        await request_report(
            TENANT_A,
            spec,
            artifact_repo=repo,
            object_store=store,
            jobs_service=jobs,
        )
    assert jobs.enqueued == []
    assert await repo.list_for_tenant(TENANT_A) == []


@pytest.mark.asyncio
async def test_request_report_unknown_template_fails_fast() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    with pytest.raises(BadRequestError):
        await _request(
            "rep_bad", repo=repo, store=store, jobs=jobs, template="bogus_template"
        )
    assert jobs.enqueued == []
    assert await repo.list_for_tenant(TENANT_A) == []


@pytest.mark.asyncio
async def test_request_report_replayed_generating_row_returns_existing_intent() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, spec = await _request("rep_replay", repo=repo, store=store, jobs=jobs)
    assert result["status"] == "generating"

    # Replayed request while the row is still ``generating``: return the existing
    # intent — no duplicate envelope row, no second durable job.
    replay = await request_report(
        TENANT_A,
        spec,
        requested_by="user-1",
        correlation_id="corr-1",
        artifact_repo=repo,
        object_store=store,
        jobs_service=jobs,
    )
    assert replay["artifact_id"] == result["artifact_id"]
    assert replay["job_id"] == result["job_id"]
    assert replay["status"] == "generating"
    assert replay["replayed"] is True
    assert len(jobs.enqueued) == 1  # the replay must not enqueue again

    report_rows = await repo.list_for_tenant(
        TENANT_A, direction="egress", artifact_type="report"
    )
    assert len(report_rows) == 1
    assert report_rows[0]["artifact_id"] == result["artifact_id"]
    assert report_rows[0]["status"] == "generating"


@pytest.mark.asyncio
async def test_request_report_reuses_available_row_within_ttl() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, spec = await _render_and_get("rep_avail", repo=repo, store=store, jobs=jobs)

    # A durable ``available`` row within its TTL is a live intent: re-requesting
    # the same report_id must return it, not stack a second generating envelope.
    replay = await request_report(
        TENANT_A,
        spec,
        requested_by="user-1",
        correlation_id="corr-1",
        artifact_repo=repo,
        object_store=store,
        jobs_service=jobs,
    )
    assert replay["artifact_id"] == result["artifact_id"]
    assert replay["status"] == "available"
    assert replay["replayed"] is True
    assert len(jobs.enqueued) == 1

    report_rows = await repo.list_for_tenant(
        TENANT_A, direction="egress", artifact_type="report"
    )
    assert len(report_rows) == 1


@pytest.mark.asyncio
async def test_request_report_new_report_id_still_creates_envelope() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result_a, _ = await _request("rep_new_a", repo=repo, store=store, jobs=jobs)
    result_b, _ = await _request("rep_new_b", repo=repo, store=store, jobs=jobs)

    # A genuinely new report_id always creates a fresh generating envelope + job.
    assert result_b["artifact_id"] != result_a["artifact_id"]
    assert result_b["status"] == "generating"
    assert result_b["replayed"] is False
    assert len(jobs.enqueued) == 2

    report_rows = await repo.list_for_tenant(
        TENANT_A, direction="egress", artifact_type="report"
    )
    assert len(report_rows) == 2
    assert {r["canonical_id"] for r in report_rows} == {"rep_new_a", "rep_new_b"}


@pytest.mark.asyncio
async def test_request_report_after_delete_mints_fresh_envelope() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, spec = await _render_and_get("rep_regen", repo=repo, store=store, jobs=jobs)
    await repo.mark_deleted(TENANT_A, result["artifact_id"])

    # A tombstoned report is not a live intent: a re-request is genuinely new.
    again = await request_report(
        TENANT_A,
        spec,
        requested_by="user-1",
        correlation_id="corr-1",
        artifact_repo=repo,
        object_store=store,
        jobs_service=jobs,
    )
    assert again["artifact_id"] != result["artifact_id"]
    assert again["status"] == "generating"
    assert again["replayed"] is False
    assert len(jobs.enqueued) == 2  # delete did not consume a job; re-request did


# ── render: bytes → ObjectStore → available ─────────────────────────────────


@pytest.mark.asyncio
async def test_render_report_puts_bytes_and_marks_available_with_checksum() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, spec = await _request("rep_1", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]

    rendered = await render_report(
        TENANT_A,
        spec,
        artifact_id=artifact_id,
        correlation_id="corr-1",
        job_id="job_1",
        artifact_repo=repo,
        object_store=store,
        renderer=_fake_renderer,
    )

    assert rendered["status"] == "available"
    assert rendered["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert rendered["size_bytes"] == len(PDF_BYTES)
    assert rendered["download_url"] == "/v1/data-exchange/reports/rep_1/download"

    # bytes live in the object store (never Postgres)
    row = await repo.get(TENANT_A, artifact_id)
    assert store.get(row["object_key"]) == PDF_BYTES
    stat = store.head(row["object_key"])
    assert stat is not None and stat.size_bytes == len(PDF_BYTES)

    # envelope is available AND carries the real size/sha256 back-filled by
    # repo.mark_available (never the "0"*64 placeholder the row was created with)
    available = await repo.get(TENANT_A, artifact_id)
    assert available["status"] == "available"
    assert available["size_bytes"] == len(PDF_BYTES)
    assert available["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert available["sha256"] != "0" * 64
    render_state = await get_report_render_state_repository().get(TENANT_A, artifact_id)
    assert render_state is not None
    assert render_state["status"] == "available"
    assert render_state["sha256"] == rendered["sha256"]
    assert render_state["size_bytes"] == len(PDF_BYTES)
    assert render_state["rendered_at"] is not None


@pytest.mark.asyncio
async def test_render_report_is_idempotent() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, spec = await _request("rep_1", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]

    first = await render_report(TENANT_A, spec, artifact_id=artifact_id,
                                artifact_repo=repo, object_store=store,
                                renderer=_fake_renderer)
    second = await render_report(TENANT_A, spec, artifact_id=artifact_id,
                                 artifact_repo=repo, object_store=store,
                                 renderer=_fake_renderer)
    assert first["sha256"] == second["sha256"]
    # one object, one available row
    assert len(store.list(f"data-exchange/{TENANT_A}/")) == 1
    assert (await repo.get(TENANT_A, artifact_id))["status"] == "available"
    render_rows = await get_report_render_state_repository().get(TENANT_A, artifact_id)
    assert render_rows["sha256"] == first["sha256"]


@pytest.mark.asyncio
async def test_render_report_does_not_resurrect_deleted_row() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, spec = await _request("rep_resurrect", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]
    await repo.mark_deleted(TENANT_A, artifact_id)

    # A queued render reaching a tombstone must fail fast *before* any bytes are
    # written: no orphan object, no flip back to available.
    with pytest.raises(ConflictError):
        await render_report(
            TENANT_A,
            spec,
            artifact_id=artifact_id,
            artifact_repo=repo,
            object_store=store,
            renderer=_fake_renderer,
        )

    row = await repo.get(TENANT_A, artifact_id)
    assert row["status"] == "deleted"
    assert row["sha256"] != hashlib.sha256(PDF_BYTES).hexdigest()
    assert len(store.list(f"data-exchange/{TENANT_A}/")) == 0  # no orphan bytes


@pytest.mark.asyncio
async def test_render_report_idempotent_noop_on_available_row_does_not_double_write() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, spec = await _request("rep_idem2", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]
    await render_report(TENANT_A, spec, artifact_id=artifact_id,
                        artifact_repo=repo, object_store=store,
                        renderer=_fake_renderer)

    replayed = await render_report(TENANT_A, spec, artifact_id=artifact_id,
                                   artifact_repo=repo, object_store=store,
                                   renderer=_fake_renderer)
    assert replayed["status"] == "available"
    assert replayed["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    # Exactly one object + one available row — the replay is a no-op, not a
    # double write (already covered by test_render_report_is_idempotent; this
    # pins the envelope-authoritative no-op return shape).
    assert len(store.list(f"data-exchange/{TENANT_A}/")) == 1
    assert len(await repo.list_for_tenant(TENANT_A, direction="egress", artifact_type="report")) == 1


# ── download / list / detail / delete ───────────────────────────────────────


async def _render_and_get(
    report_id: str,
    *,
    repo: DataArtifactRepository,
    store: InMemoryObjectStore,
    jobs: FakeJobsService,
) -> tuple[dict, ReportSpecContract]:
    result, spec = await _request(report_id, repo=repo, store=store, jobs=jobs)
    await render_report(TENANT_A, spec, artifact_id=result["artifact_id"],
                        artifact_repo=repo, object_store=store,
                        renderer=_fake_renderer)
    return result, spec


@pytest.mark.asyncio
async def test_download_report_serves_bytes_and_meta() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _render_and_get("rep_dl", repo=repo, store=store, jobs=jobs)

    meta, content = await download_report(TENANT_A, "rep_dl", artifact_repo=repo, object_store=store)
    assert content == PDF_BYTES
    assert meta["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert meta["size_bytes"] == len(PDF_BYTES)
    assert meta["filename"].endswith(".pdf")
    assert meta["report_id"] == "rep_dl"


@pytest.mark.asyncio
async def test_download_report_refuses_when_not_ready() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _request("rep_pending", repo=repo, store=store, jobs=jobs)
    assert result["status"] == "generating"

    with pytest.raises(ConflictError):
        await download_report(TENANT_A, "rep_pending", artifact_repo=repo, object_store=store)


@pytest.mark.asyncio
async def test_download_report_refuses_deleted() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _render_and_get("rep_del", repo=repo, store=store, jobs=jobs)
    await repo.mark_deleted(TENANT_A, result["artifact_id"])

    with pytest.raises(NotFoundError):
        await download_report(TENANT_A, "rep_del", artifact_repo=repo, object_store=store)


@pytest.mark.asyncio
async def test_download_report_refuses_failed() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _request("rep_fail", repo=repo, store=store, jobs=jobs)
    await mark_report_failed(
        TENANT_A, result["artifact_id"], error="render boom",
        report_id="rep_fail", artifact_repo=repo,
    )
    assert (await repo.get(TENANT_A, result["artifact_id"]))["status"] == "failed"

    # a ``failed`` tombstone is byte-free and absorbing — download must refuse.
    with pytest.raises(NotFoundError):
        await download_report(TENANT_A, "rep_fail", artifact_repo=repo, object_store=store)


@pytest.mark.asyncio
async def test_download_report_refuses_expired() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _render_and_get("rep_exp", repo=repo, store=store, jobs=jobs)
    await repo.mark_expired(TENANT_A, result["artifact_id"])
    assert (await repo.get(TENANT_A, result["artifact_id"]))["status"] == "expired"

    with pytest.raises(NotFoundError):
        await download_report(TENANT_A, "rep_exp", artifact_repo=repo, object_store=store)


@pytest.mark.asyncio
async def test_download_report_serves_checksum_from_envelope_row() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _render_and_get("rep_sha", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]
    real_sha = hashlib.sha256(PDF_BYTES).hexdigest()

    # After fix #1 the envelope row carries the verified checksum; the download
    # response must source X-Checksum-SHA256 from the row, not a fallback hash.
    meta, content = await download_report(TENANT_A, "rep_sha", artifact_repo=repo, object_store=store)
    assert content == PDF_BYTES
    assert meta["sha256"] == (await repo.get(TENANT_A, artifact_id))["sha256"]
    assert meta["sha256"] == real_sha
    assert meta["size_bytes"] == len(PDF_BYTES)


@pytest.mark.asyncio
async def test_download_report_refuses_cross_tenant() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    await _render_and_get("rep_ta", repo=repo, store=store, jobs=jobs)

    with pytest.raises(NotFoundError):
        await download_report(TENANT_B, "rep_ta", artifact_repo=repo, object_store=store)


@pytest.mark.asyncio
async def test_list_and_detail_reports() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()

    await _render_and_get("rep_a", repo=repo, store=store, jobs=jobs)
    # rep_b is requested but not yet rendered (generating)
    await _request("rep_b", repo=repo, store=store, jobs=jobs)

    listing = await list_report_artifacts(TENANT_A, artifact_repo=repo)
    assert listing["count"] == 2
    by_id = {a["report_id"]: a for a in listing["artifacts"]}
    assert set(by_id) == {"rep_a", "rep_b"}
    # rendered report carries verified checksum + render meta
    assert by_id["rep_a"]["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert by_id["rep_a"]["size_bytes"] == len(PDF_BYTES)
    assert by_id["rep_a"]["template"] == DEFAULT_TEMPLATE
    assert by_id["rep_a"]["rendered_at"] is not None
    assert by_id["rep_a"]["status"] == "available"
    # still-generating report carries the placeholder envelope
    assert by_id["rep_b"]["status"] == "generating"
    assert by_id["rep_b"]["rendered_at"] is None

    filtered = await list_report_artifacts(TENANT_A, status="generating", artifact_repo=repo)
    assert filtered["count"] == 1
    assert filtered["artifacts"][0]["report_id"] == "rep_b"

    detail = await get_report_detail(TENANT_A, "rep_a", artifact_repo=repo)
    assert detail["report_id"] == "rep_a"
    assert detail["artifact"]["status"] == "available"
    assert detail["render_meta"]["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()

    with pytest.raises(NotFoundError):
        await get_report_detail(TENANT_A, "rep_unknown", artifact_repo=repo)


@pytest.mark.asyncio
async def test_delete_report_tombstones_and_removes_render_state() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _render_and_get("rep_d", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]
    sha = hashlib.sha256(PDF_BYTES).hexdigest()

    deleted = await delete_report(TENANT_A, "rep_d", artifact_repo=repo, object_store=store)
    assert deleted["deleted"] is True
    assert deleted["artifact_id"] == artifact_id
    assert deleted["tombstone_sha256"] == sha

    row = await repo.get(TENANT_A, artifact_id)
    assert row["status"] == "deleted"
    assert row["deleted_at"] is not None
    assert await get_report_render_state_repository().get(TENANT_A, artifact_id) is None


# ── failure bookkeeping ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_report_failed_flips_generating_row_to_failed() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _request("rep_genfail", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]

    await mark_report_failed(
        TENANT_A, artifact_id, error="render boom",
        report_id="rep_genfail", artifact_repo=repo,
    )
    row = await repo.get(TENANT_A, artifact_id)
    assert row["status"] == "failed"
    render_state = await get_report_render_state_repository().get(TENANT_A, artifact_id)
    assert render_state is not None
    assert render_state["status"] == "failed"
    assert render_state["error"] == "render boom"


@pytest.mark.asyncio
async def test_mark_report_failed_does_not_tombstone_available() -> None:
    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    jobs = FakeJobsService()
    result, _ = await _render_and_get("rep_keep", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]
    real_sha = hashlib.sha256(PDF_BYTES).hexdigest()

    # A durable ``available`` artifact must never be silently tombstoned as
    # ``failed``: mark_report_failed is a best-effort no-flip success and the
    # bytes stay downloadable.
    outcome = await mark_report_failed(
        TENANT_A, artifact_id, error="late failure",
        report_id="rep_keep", artifact_repo=repo,
    )
    row = await repo.get(TENANT_A, artifact_id)
    assert row["status"] == "available"
    assert row["sha256"] == real_sha
    assert outcome["status"] == "failed"  # return value is advisory only

    meta, content = await download_report(TENANT_A, "rep_keep", artifact_repo=repo, object_store=store)
    assert content == PDF_BYTES
    assert meta["sha256"] == real_sha


@pytest.mark.asyncio
async def test_mark_report_failed_is_best_effort_on_missing_row() -> None:
    repo = DataArtifactRepository()
    outcome = await mark_report_failed(
        TENANT_A, "rep_ghost_missing", error="boom", artifact_repo=repo,
    )
    assert outcome["artifact_id"] == "rep_ghost_missing"
    assert outcome["status"] == "failed"


# ── render-state repository tenant scoping ──────────────────────────────────


@pytest.mark.asyncio
async def test_render_state_is_tenant_scoped() -> None:
    render_repo = get_report_render_state_repository()
    await render_repo.save(
        tenant_id=TENANT_A, report_id="rep_1", artifact_id="rep_x", object_key="k",
        template=DEFAULT_TEMPLATE, filename="f.pdf", status="available",
        size_bytes=3, sha256="a" * 64,
    )
    assert (await render_repo.get(TENANT_A, "rep_x")) is not None
    assert (await render_repo.get(TENANT_B, "rep_x")) is None
    assert await render_repo.delete(TENANT_B, "rep_x") is False
    assert (await render_repo.get(TENANT_A, "rep_x")) is not None
    assert await render_repo.delete(TENANT_A, "rep_x") is True


# ── durable job handler shape ───────────────────────────────────────────────


async def _ctx(tenant_id: str = TENANT_A, job_id: str = "job_h") -> SimpleNamespace:
    async def _heartbeat() -> bool:
        return True

    return SimpleNamespace(
        tenant_id=tenant_id,
        job_id=job_id,
        correlation_id="corr-h",
        worker_id="w1",
        heartbeat=_heartbeat,
        emit_event=lambda *a, **k: _noop(),
    )


async def _noop() -> None:  # pragma: no cover - trivial
    return None


@pytest.mark.asyncio
async def test_generate_report_handler_succeeds_and_marks_artifact_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("reportlab")  # real render path needs reportlab
    from services.jobs.handlers import JobOutcome

    repo = DataArtifactRepository()
    store = InMemoryObjectStore()
    monkeypatch.setattr(
        "services.reports.service.get_data_artifact_repository", lambda: repo
    )
    monkeypatch.setattr("services.reports.service.get_object_store", lambda: store)
    jobs = FakeJobsService()
    result, spec = await _request("rep_job", repo=repo, store=store, jobs=jobs)
    artifact_id = result["artifact_id"]

    payload = {
        "report_id": "rep_job",
        "artifact_id": artifact_id,
        "template": DEFAULT_TEMPLATE,
        "spec": spec.model_dump(mode="json"),
    }
    outcome = await generate_report_artifact(payload, await _ctx())
    assert outcome.status == "succeeded"
    assert outcome.result["artifact_id"] == artifact_id
    assert outcome.result["status"] == "available"
    assert (await repo.get(TENANT_A, artifact_id))["status"] == "available"
    assert isinstance(outcome, JobOutcome)


@pytest.mark.asyncio
async def test_generate_report_handler_failed_when_spec_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.jobs.handlers import JobOutcome

    monkeypatch.setattr(
        "services.reports.service.get_data_artifact_repository",
        lambda: DataArtifactRepository(),
    )
    outcome = await generate_report_artifact({"artifact_id": "rep_ghost"}, await _ctx())
    assert outcome.status == "failed"
    assert "no report spec" in (outcome.error or "")
    assert isinstance(outcome, JobOutcome)


@pytest.mark.asyncio
async def test_register_report_jobs_is_idempotent() -> None:
    from services.reports.jobs_reports import register_report_jobs

    if REPORT_JOB_TYPE not in HANDLER_REGISTRY:
        register_report_jobs()
        assert REPORT_JOB_TYPE in HANDLER_REGISTRY
    else:
        register_report_jobs()  # must not raise on duplicate
    assert REPORT_JOB_TYPE in HANDLER_REGISTRY
    if REPORT_JOB_TYPE in HANDLER_REGISTRY:
        unregister_handler(REPORT_JOB_TYPE)
        assert REPORT_JOB_TYPE not in HANDLER_REGISTRY


# ── pure template sections + template policy (no reportlab) ─────────────────


def test_default_template_sections_are_pure_and_ordered() -> None:
    generated_at = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    spec = _spec("rep_s", resource="audit-log").model_dump(mode="json")
    sections = _default_template_sections(
        spec,
        include_methodology=True,
        include_provenance_summary=True,
        display_timezone="UTC",
        generated_at=generated_at,
        source_rows=None,
        source_meta=None,
    )
    kinds = [s["kind"] for s in sections]
    assert kinds[0] == "title"
    assert "heading" in kinds
    assert "bullets" in kinds
    assert "kv" in kinds
    # methodology/provenance can be toggled off
    slim = _default_template_sections(
        spec,
        include_methodology=False,
        include_provenance_summary=False,
        display_timezone="UTC",
        generated_at=generated_at,
    )
    slim_kinds = [s["kind"] for s in slim]
    assert "heading" not in slim_kinds
    assert "bullets" not in slim_kinds


def test_template_resolution_policy() -> None:
    assert resolve_template_name(None) == DEFAULT_TEMPLATE
    assert resolve_template_name("") == DEFAULT_TEMPLATE
    assert resolve_template_name(DEFAULT_TEMPLATE) == DEFAULT_TEMPLATE
    # unknown lenient -> default; strict -> error
    assert resolve_template_name("nope") == DEFAULT_TEMPLATE
    with pytest.raises(ReportRenderError):
        resolve_template_name("nope", strict=True)


# ── reportlab renderer determinism (skipped when reportlab is absent) ───────


def test_render_report_pdf_is_deterministic() -> None:
    pytest.importorskip("reportlab")
    from services.reports.renderers import render_report_pdf

    generated_at = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    spec = _spec("rep_det", resource="audit-log").model_dump(mode="json")
    first = render_report_pdf(
        spec,
        template=DEFAULT_TEMPLATE,
        include_methodology=True,
        include_provenance_summary=True,
        display_timezone="UTC",
        generated_at=generated_at,
    )
    second = render_report_pdf(
        spec,
        template=DEFAULT_TEMPLATE,
        include_methodology=True,
        include_provenance_summary=True,
        display_timezone="UTC",
        generated_at=generated_at,
    )
    assert isinstance(first, bytes) and first.startswith(b"%PDF")
    assert first == second


def test_render_report_pdf_fails_cleanly_without_reportlab() -> None:
    try:
        import reportlab  # noqa: F401

        pytest.skip("reportlab installed — clean-failure path not reachable here")
    except ImportError:
        pass
    from services.reports.renderers import render_report_pdf

    with pytest.raises(ReportRenderError):
        render_report_pdf({"report_id": "r1", "resource": "audit-log"})


# ── route surface shape ─────────────────────────────────────────────────────


def test_reports_router_surface() -> None:
    prefix = "/v1/data-exchange/reports"
    methods_by_path: dict[str, set[str]] = {}
    for route in reports_router.routes:
        path = getattr(route, "path", "")
        for method in getattr(route, "methods", []) or []:
            methods_by_path.setdefault(path, set()).add(method)

    assert methods_by_path[prefix] == {"POST", "GET"}
    assert methods_by_path[f"{prefix}/{{report_id}}"] == {"GET", "DELETE"}
    assert methods_by_path[f"{prefix}/{{report_id}}/download"] == {"GET"}


# ── route RBAC mirrors the sibling data_exchange routers ────────────────────


def test_report_route_grant_tuples_match_envelope_doctrine() -> None:
    # A byte download is never weaker than the canonical export-download gate:
    # it must anchor on data_exchange.export.download (as the sibling transfer
    # download route does) and/or a report grant — never plain read.
    assert "data_exchange.read" not in REPORT_DOWNLOAD_REQUIRED_GRANTS
    assert "data_exchange.export.download" in REPORT_DOWNLOAD_REQUIRED_GRANTS
    assert "data_exchange.report.create" in REPORT_DOWNLOAD_REQUIRED_GRANTS
    assert "admin" in REPORT_DOWNLOAD_REQUIRED_GRANTS

    # Create/read/delete carry their dedicated grant + the admin bypass.
    assert REPORT_CREATE_REQUIRED_GRANTS == ("data_exchange.report.create", "admin")
    assert REPORT_READ_REQUIRED_GRANTS == ("data_exchange.read", "admin")

    # Delete requires the dedicated report.delete grant and is deliberately not
    # reachable by a read-only tenant (the old code listed read in the delete
    # tuple, which let any metadata reader delete reports).
    assert "data_exchange.report.delete" in REPORT_DELETE_REQUIRED_GRANTS
    assert "data_exchange.read" not in REPORT_DELETE_REQUIRED_GRANTS
    assert "admin" in REPORT_DELETE_REQUIRED_GRANTS


def _tenant_ctx(*permissions: str, role: Role = Role.VIEWER) -> TenantContext:
    return TenantContext(tenant_id="tnt-a", role=role, permissions=list(permissions))


def test_report_route_effective_authorization_matches_sibling_routers() -> None:
    # Metadata reads are open to the domain read grant …
    require_data_exchange(_tenant_ctx("data_exchange.read"), *REPORT_READ_REQUIRED_GRANTS)
    # … but a read-only tenant can neither download PDF bytes nor delete.
    with pytest.raises(ForbiddenError):
        require_data_exchange(_tenant_ctx("data_exchange.read"), *REPORT_DOWNLOAD_REQUIRED_GRANTS)
    with pytest.raises(ForbiddenError):
        require_data_exchange(_tenant_ctx("data_exchange.read"), *REPORT_DELETE_REQUIRED_GRANTS)
    with pytest.raises(ForbiddenError):
        require_data_exchange(_tenant_ctx("read"), *REPORT_DOWNLOAD_REQUIRED_GRANTS)

    # Report creators and canonical egress-download holders can download (the
    # export.download anchor mirrors the sibling transfer download route).
    require_data_exchange(_tenant_ctx("data_exchange.report.create"), *REPORT_DOWNLOAD_REQUIRED_GRANTS)
    require_data_exchange(_tenant_ctx("data_exchange.export.download"), *REPORT_DOWNLOAD_REQUIRED_GRANTS)

    # Delete stays behind the dedicated report.delete grant (or admin).
    require_data_exchange(_tenant_ctx("data_exchange.report.delete"), *REPORT_DELETE_REQUIRED_GRANTS)
    require_data_exchange(_tenant_ctx("admin"), *REPORT_DELETE_REQUIRED_GRANTS)
    require_data_exchange(_tenant_ctx("admin"), *REPORT_DOWNLOAD_REQUIRED_GRANTS)
    require_data_exchange(_tenant_ctx(role=Role.ADMIN), *REPORT_DOWNLOAD_REQUIRED_GRANTS)
