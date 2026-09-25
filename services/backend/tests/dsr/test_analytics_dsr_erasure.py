"""Analytics event-store DSR erasure (``analytics_events`` component).

The ``analytics_event_recorder`` stream projector persists one ``events`` row per
validated SDK event (``user_id`` / ``anonymous_id``) plus a ``sessions`` rollup
per session. A user-level DSR erasure must remove the subject's rows from both,
tenant-scoped, idempotently, and report the store's own counts on the
``analytics_events`` propagation step. Suites pin:

1. ``AnalyticsRepository.erase_subject`` deletes the subject's events and the
   session rollups attributed to the subject, recomputes another identity's
   rollup that counted the subject's events, and never touches another tenant's
   rows (even for the same ``user_id``) or another user's sessions — on the
   in-memory backend and, with ``ANALYTICS_TEST_DATABASE_URL``, on PostgreSQL;
2. the request's ``anonymous_id`` also keys the erasure (pre-identify events);
3. the durable ``consent.erasure`` job marks ``analytics_events`` completed with
   records_impacted / artifacts_impacted and drops the tenant's query cache;
4. a plane failure marks the component ``failed`` and keeps the job retryable.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from repositories.jobs_repo import reset_jobs_memory  # noqa: E402
from repositories.repos import (  # noqa: E402
    AnalyticsRepository,
    ConsentRepository,
    analytics_session_record_id,
    reset_in_memory_stores,
)
from services.consent import erasure_jobs  # noqa: E402
from services.consent.authority import ConsentReceiptRepository  # noqa: E402
from services.consent.erasure_jobs import (  # noqa: E402
    ANALYTICS_EVENTS_COMPONENT,
    register_consent_erasure_handler,
)
from services.consent.routes import DataSubjectRequest, submit_dsr  # noqa: E402
from services.dsr_propagation.service import DSRPropagationService  # noqa: E402
from services.ingestion import workers as ingestion_workers  # noqa: E402
from services.ingestion.workers import build_analytics_event_record  # noqa: E402
from services.jobs.handlers import JobContext  # noqa: E402
from services.jobs.models import JobStatus  # noqa: E402
from services.jobs.service import get_jobs_service  # noqa: E402
from services.jobs.worker import JobWorker  # noqa: E402
from services.measurement import privacy as privacy_mod  # noqa: E402
from shared.cache.cache import CacheKey  # noqa: E402
from shared.events.events import Event, Topic  # noqa: E402

try:  # asyncpg ships with the backend runtime; guard so collection never fails.
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

PG_URL = os.getenv("ANALYTICS_TEST_DATABASE_URL")
BACKENDS = ["inmem", "pg"]


class _DictCache:
    def __init__(self) -> None:
        self.store: dict = {}

    async def get_json(self, key):
        return self.store.get(key)

    async def set_json(self, key, value, ttl=None):
        self.store[key] = value

    async def delete_pattern(self, pattern):
        prefix = pattern.rstrip("*")
        doomed = [k for k in self.store if k.startswith(prefix)]
        for k in doomed:
            del self.store[k]
        return len(doomed)


async def _ensure_tables_serially(pool, analytics) -> None:
    """Create the JSONB tables under an advisory lock: concurrent
    ``CREATE TABLE IF NOT EXISTS`` from parallel xdist workers on a fresh
    database can race on the catalog's unique index."""
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", _DDL_LOCK_KEY)
        try:
            await analytics._events._ensure_table()
            await analytics._sessions._ensure_table()
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _DDL_LOCK_KEY)


_DDL_LOCK_KEY = 0x616E_616C_7974  # "analyt"


@pytest.fixture
async def repo(request):
    kind = request.param
    analytics = AnalyticsRepository(_DictCache())
    pool = None
    if kind == "pg":
        if asyncpg is None or not PG_URL:
            pytest.skip("ANALYTICS_TEST_DATABASE_URL not set")
        try:
            pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=4)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"postgres unavailable: {exc}")
        analytics._events._pool = pool
        analytics._sessions._pool = pool
        await _ensure_tables_serially(pool, analytics)
    else:
        reset_in_memory_stores()
    try:
        yield analytics
    finally:
        if pool is not None:
            await pool.close()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def _record(repo, tenant, *, session_id, user_id=None, anonymous_id=None,
                  ts="2026-05-01T10:00:00Z", event_type="page") -> str:
    event_id = str(uuid.uuid4())
    payload = {
        "event_id": event_id, "tenant_id": tenant, "event_type": event_type,
        "event_family": "core", "session_id": session_id, "anonymous_id": anonymous_id,
        "user_id": user_id, "properties": {"path": "/"}, "timestamp": ts,
        "received_at": ts, "schema_version": "1.0.0", "source": "sdk",
    }
    record = build_analytics_event_record(payload, tenant_id=tenant, event_id=event_id)
    assert await repo.record_processed_event(record) is True
    return event_id


async def _event_ids(repo, tenant, **filters) -> set[str]:
    rows = await repo._events.query(tenant, filters, limit=200)
    return {r["event_id"] for r in rows}


async def _session(repo, tenant, session_id):
    return await repo._sessions.find_by_id(analytics_session_record_id(tenant, session_id))


# ── 1. Repository erasure: subject gone, everyone else intact ──────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_erase_subject_is_tenant_scoped_and_spares_other_users(repo):
    tenant_a, tenant_b = _uid("ta"), _uid("tb")
    subject, other = _uid("u-subject"), _uid("u-other")
    s_subject, s_other, s_shared = _uid("s"), _uid("s"), _uid("s")
    s_b = _uid("s")

    # Subject's own session (two events), another user's session, and a shared
    # session: the subject's event first, then another user's (rollup now
    # attributed to ``other``).
    subj_1 = await _record(repo, tenant_a, session_id=s_subject, user_id=subject,
                           ts="2026-05-01T10:00:00Z")
    subj_2 = await _record(repo, tenant_a, session_id=s_subject, user_id=subject,
                           ts="2026-05-01T10:05:00Z")
    other_1 = await _record(repo, tenant_a, session_id=s_other, user_id=other)
    shared_subj = await _record(repo, tenant_a, session_id=s_shared, user_id=subject,
                                ts="2026-05-01T09:00:00Z")
    shared_other = await _record(repo, tenant_a, session_id=s_shared, user_id=other,
                                 ts="2026-05-01T11:00:00Z")
    # The SAME user_id in another tenant is a different data subject's scope.
    b_event = await _record(repo, tenant_b, session_id=s_b, user_id=subject)

    result = await repo.erase_subject(tenant_a, subject)
    assert result == {"events_deleted": 3, "sessions_deleted": 1, "sessions_recomputed": 1}
    assert not {subj_1, subj_2, shared_subj} & await _event_ids(repo, tenant_a)

    # Subject's own session rollup is gone.
    assert await _session(repo, tenant_a, s_subject) is None
    # The other user's session and events are untouched.
    assert await _event_ids(repo, tenant_a, user_id=other) == {other_1, shared_other}
    other_session = await _session(repo, tenant_a, s_other)
    assert other_session["event_count"] == 1 and other_session["user_id"] == other
    # The shared rollup survives (attributed to ``other``) without the subject's
    # contribution.
    shared = await _session(repo, tenant_a, s_shared)
    assert shared["user_id"] == other
    assert shared["event_count"] == 1
    assert shared["first_seen_at"] == shared["last_seen_at"] == "2026-05-01T11:00:00.000000Z"
    # Tenant B's rows for the same user_id are untouched.
    assert await _event_ids(repo, tenant_b, user_id=subject) == {b_event}
    assert (await _session(repo, tenant_b, s_b))["event_count"] == 1

    # Idempotent: a retry erases nothing more.
    assert await repo.erase_subject(tenant_a, subject) == {
        "events_deleted": 0, "sessions_deleted": 0, "sessions_recomputed": 0,
    }
    summary = await repo.dashboard_summary(tenant_a)
    assert summary["total_events"] == 2
    assert summary["total_sessions"] == 2


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_anonymous_id_keys_pre_identify_events(repo):
    tenant = _uid("t")
    subject, anon, other_anon = _uid("u"), _uid("anon"), _uid("anon")
    s1, s2 = _uid("s"), _uid("s")
    pre = await _record(repo, tenant, session_id=s1, anonymous_id=anon,
                        ts="2026-05-01T08:00:00Z")
    post = await _record(repo, tenant, session_id=s1, anonymous_id=anon, user_id=subject,
                         ts="2026-05-01T08:01:00Z")
    stranger = await _record(repo, tenant, session_id=s2, anonymous_id=other_anon)

    # Without the anonymous id only the identified event is erased; the rollup
    # (attributed to the subject's user_id) goes with it.
    result = await repo.erase_subject(tenant, subject)
    assert result["events_deleted"] == 1 and result["sessions_deleted"] == 1
    assert await _event_ids(repo, tenant, session_id=s1) == {pre}

    # With the anonymous id the pre-identify event goes too; the stranger stays.
    result = await repo.erase_subject(tenant, subject, anon)
    assert result["events_deleted"] == 1
    assert await _event_ids(repo, tenant) == {stranger}
    assert post not in await _event_ids(repo, tenant)
    assert (await _session(repo, tenant, s2))["anonymous_id"] == other_anon


async def test_erase_subject_requires_scope_and_identity():
    reset_in_memory_stores()
    repo = AnalyticsRepository(_DictCache())
    with pytest.raises(ValueError):
        await repo.erase_subject("", "u")
    with pytest.raises(ValueError):
        await repo.erase_subject("t", None, None)


# ── 2/3. Durable DSR erasure job end-to-end ────────────────────────────────────


TENANT = "tenant-analytics-dsr"
USER = "user-to-erase"


@pytest.fixture
def job_env(monkeypatch):
    reset_in_memory_stores()
    reset_jobs_memory()
    register_consent_erasure_handler()
    monkeypatch.setattr(
        privacy_mod._touchpoint_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        privacy_mod._conversion_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    from services.measurement.engine.journey_compiler import JourneyCompiler

    monkeypatch.setattr(
        JourneyCompiler, "rebuild_affected_by_consent_change", AsyncMock(return_value=None)
    )
    # The erasure plane invalidates the process registry's cache — the same
    # cache the analytics routes read through.
    from dependencies.providers import get_registry

    yield get_registry().cache
    reset_in_memory_stores()
    reset_jobs_memory()


class _Producer:
    async def publish(self, event) -> None:
        return None


def _request(tenant_id: str) -> MagicMock:
    req = MagicMock()
    req.state.tenant.tenant_id = tenant_id
    req.state.tenant.require_permission = MagicMock()
    return req


async def _submit(tenant_id: str, anonymous_id: str | None = None) -> dict:
    await ConsentReceiptRepository().record(
        receipt_id=f"rcpt_{tenant_id}_{USER}", tenant_id=tenant_id,
        purpose="analytics", state="granted", subject_id=USER,
    )
    body = DataSubjectRequest(
        user_id=USER, request_type="erasure", anonymous_id=anonymous_id
    )
    return (await submit_dsr(body, _request(tenant_id), producer=_Producer()))["data"]


async def _step(propagation_id: str, tenant_id: str = TENANT) -> dict:
    status = await DSRPropagationService().status(propagation_id, tenant_id=tenant_id)
    return next(c for c in status["components"] if c["component"] == ANALYTICS_EVENTS_COMPONENT)


async def test_dsr_erasure_job_erases_analytics_and_marks_step(job_env):
    repo = AnalyticsRepository(job_env)
    anon = "anon-subject"
    s_subject, s_other, s_b = _uid("s"), _uid("s"), _uid("s")
    await _record(repo, TENANT, session_id=s_subject, anonymous_id=anon)
    await _record(repo, TENANT, session_id=s_subject, anonymous_id=anon, user_id=USER)
    await _record(repo, TENANT, session_id=s_subject, anonymous_id=anon, user_id=USER)
    kept = await _record(repo, TENANT, session_id=s_other, user_id="someone-else")
    other_tenant = await _record(repo, "tenant-other", session_id=s_b, user_id=USER)
    # Warm the query cache with the subject's events: without invalidation the
    # same query would keep serving them from cache after the rows are gone.
    assert len(await repo.query_events(TENANT, {"user_id": USER}, limit=10)) == 2
    generation_key = CacheKey.analytics_query_generation(TENANT)
    generation = await job_env.get_json(generation_key)
    assert generation  # recording the events issued a query-cache generation
    cache_key = CacheKey.analytics_query(
        TENANT,
        CacheKey.hash_query(
            f"{sorted({'user_id': USER}.items())}|from=None|to=None|limit=10|gen={generation}"
        ),
    )
    assert await job_env.get_json(cache_key)

    dsr = await _submit(TENANT, anonymous_id=anon)
    assert (await get_jobs_service().get_job(TENANT, dsr["erasure_job_id"]))["payload"][
        "anonymous_id"
    ] == anon
    assert await JobWorker().run_once() is True

    job = await get_jobs_service().get_job(TENANT, dsr["erasure_job_id"])
    assert job["status"] == JobStatus.SUCCEEDED.value
    step = await _step(dsr["propagation_request_id"])
    assert step["status"] == "completed"
    assert step["records_impacted"] == 4  # 3 events + 1 session rollup
    assert step["artifacts_impacted"] == 0
    assert step["audit_event_id"] == dsr["erasure_job_id"]

    assert await repo.query_events(TENANT, {"user_id": USER}, limit=10) == []
    assert await repo.query_events(TENANT, {"session_id": s_subject}, limit=10) == []
    assert await _session(repo, TENANT, s_subject) is None
    assert await _event_ids(repo, TENANT) == {kept}
    assert await job_env.get_json(cache_key) is None  # tenant cache dropped
    # ...and its generation retired, so a read that raced the erasure and
    # re-cached under the old generation is never served again.
    assert await job_env.get_json(generation_key) not in (None, generation)
    # Another tenant's rows for the same user_id are untouched.
    assert await _event_ids(repo, "tenant-other", user_id=USER) == {other_tenant}
    assert len(await repo.query_events("tenant-other", {"user_id": USER}, limit=10)) == 1

    record = await ConsentRepository().find_by_id(f"dsr_{dsr['dsr_id']}")
    assert record["status"] == "completed"
    assert record["anonymous_id"] == anon


async def test_analytics_plane_failure_marks_component_failed_and_retries(job_env, monkeypatch):
    monkeypatch.setattr(
        erasure_jobs,
        "_erase_analytics_plane",
        AsyncMock(side_effect=RuntimeError("analytics store down")),
    )
    dsr = await _submit(TENANT)
    assert await JobWorker().run_once() is True

    job = await get_jobs_service().get_job(TENANT, dsr["erasure_job_id"])
    assert job["status"] == JobStatus.RETRYING.value
    assert "analytics" in (job["error"] or "")
    step = await _step(dsr["propagation_request_id"])
    assert step["status"] == "failed"


def test_registered_component_is_the_tail_member():
    from services.dsr_propagation.models import DSR_COMPONENTS

    assert DSR_COMPONENTS[-1] == ANALYTICS_EVENTS_COMPONENT


# ── 4. Retried erasure keeps the committed receipt ─────────────────────────────


async def test_cache_failure_retry_keeps_the_committed_erasure_receipt(job_env, monkeypatch):
    """The deletes commit before the cache is dropped. When invalidation fails,
    the retry erases nothing, so it must add the first attempt's counts rather
    than complete the component with a zero receipt."""
    repo = AnalyticsRepository(job_env)
    session = _uid("s")
    await _record(repo, TENANT, session_id=session, user_id=USER)
    await _record(repo, TENANT, session_id=session, user_id=USER)
    real_delete = job_env.delete_pattern
    calls = {"n": 0}

    async def _flaky_delete(pattern):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("cache unavailable")
        return await real_delete(pattern)

    monkeypatch.setattr(job_env, "delete_pattern", _flaky_delete)
    dsr = await _submit(TENANT)
    assert await JobWorker().run_once() is True
    step = await _step(dsr["propagation_request_id"])
    assert step["status"] == "failed"
    assert step["records_impacted"] == 3  # 2 events + 1 session, already deleted

    handler = erasure_jobs.HANDLER_REGISTRY[erasure_jobs.ERASURE_JOB_TYPE]
    ctx = JobContext(
        job_id=dsr["erasure_job_id"], tenant_id=TENANT, correlation_id=dsr["dsr_id"],
        worker_id="test_worker", heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )
    outcome = await handler(
        {"dsr_id": dsr["dsr_id"], "user_id": USER,
         "propagation_request_id": dsr["propagation_request_id"]},
        ctx,
    )
    assert outcome.status == "succeeded"
    step = await _step(dsr["propagation_request_id"])
    assert step["status"] == "completed"
    assert step["records_impacted"] == 3


# ── 5. Erasure fence: queued events cannot undo an erasure ────────────────────


async def _dsr_record(tenant_id: str, *, submitted_at: str, user_id=USER, anonymous_id=None):
    from services.consent.erasure_fence import record_erasure_markers

    await record_erasure_markers(
        tenant_id, user_id=user_id, anonymous_id=anonymous_id, submitted_at=submitted_at,
    )


def _validated(tenant_id: str, *, received_at: str, user_id=None, anonymous_id=None) -> Event:
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED, tenant_id=tenant_id, source_service="ingestion.batch",
        payload={
            "event_id": str(uuid.uuid4()), "tenant_id": tenant_id, "event_type": "page",
            "event_family": "core", "session_id": _uid("s"), "user_id": user_id,
            "anonymous_id": anonymous_id, "properties": {}, "timestamp": received_at,
            "received_at": received_at, "schema_version": "1.0.0", "source": "sdk",
        },
    )


@pytest.fixture
def recorder_repo():
    reset_in_memory_stores()
    repo = AnalyticsRepository(_DictCache())
    previous = ingestion_workers._analytics_repository
    ingestion_workers._analytics_repository = repo
    yield repo
    ingestion_workers._analytics_repository = previous
    reset_in_memory_stores()


async def test_event_received_before_an_erasure_is_not_written_back(recorder_repo):
    tenant = _uid("t")
    await _dsr_record(tenant, submitted_at="2026-05-02T00:00:00+00:00")

    await ingestion_workers.analytics_event_recorder(
        _validated(tenant, received_at="2026-05-01T10:00:00Z", user_id=USER)
    )

    assert await _event_ids(recorder_repo, tenant) == set()


async def test_anonymous_id_named_by_the_erasure_is_fenced(recorder_repo):
    tenant = _uid("t")
    await _dsr_record(tenant, submitted_at="2026-05-02T00:00:00+00:00", anonymous_id="anon-1")

    await ingestion_workers.analytics_event_recorder(
        _validated(tenant, received_at="2026-05-01T10:00:00Z", anonymous_id="anon-1")
    )

    assert await _event_ids(recorder_repo, tenant) == set()


async def test_activity_after_the_erasure_and_other_subjects_are_recorded(recorder_repo):
    tenant = _uid("t")
    await _dsr_record(tenant, submitted_at="2026-05-02T00:00:00+00:00")
    later = _validated(tenant, received_at="2026-05-03T10:00:00Z", user_id=USER)
    other = _validated(tenant, received_at="2026-05-01T10:00:00Z", user_id="someone-else")
    elsewhere = _validated(_uid("t"), received_at="2026-05-01T10:00:00Z", user_id=USER)

    for event in (later, other, elsewhere):
        await ingestion_workers.analytics_event_recorder(event)

    assert await _event_ids(recorder_repo, tenant) == {
        later.payload["event_id"], other.payload["event_id"]
    }


async def test_erasure_submission_records_markers_without_the_identifier(job_env):
    from services.consent.erasure_fence import ErasureMarkerRepository, erasure_marker_id

    await _submit(TENANT, anonymous_id="anon-subject")

    repo = ErasureMarkerRepository()
    for kind, identifier in (("user_id", USER), ("anonymous_id", "anon-subject")):
        marker = await repo.find_by_id(erasure_marker_id(TENANT, kind, identifier))
        assert marker is not None and marker["tenant_id"] == TENANT
        assert identifier not in str(marker)


async def test_marker_is_written_before_the_erasure_request(job_env, monkeypatch):
    """The one-time backfill never revisits, so no crash may leave a stored
    erasure request without its marker: the marker is written first."""
    from services.consent import routes as consent_routes
    from services.consent.erasure_fence import ErasureMarkerRepository, erasure_marker_id

    monkeypatch.setattr(
        consent_routes._repo, "insert", AsyncMock(side_effect=RuntimeError("process died")),
    )
    with pytest.raises(RuntimeError):
        await _submit(TENANT)

    marker = await ErasureMarkerRepository().find_by_id(erasure_marker_id(TENANT, "user_id", USER))
    assert marker is not None and marker["submitted_at"]


async def test_fence_is_key_lookups_only():
    """The fence runs for every projected event, so it must not scan."""
    from services.consent.erasure_fence import erasure_fences_event

    class _Repo:
        def __init__(self) -> None:
            self.reads = 0

        async def find_by_id(self, _id):
            if _id == "dsrm_backfill_v1":
                return {"id": _id}  # backfill already recorded
            self.reads += 1
            return None

        async def find_many(self, *args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("the fence must not scan")

    repo = _Repo()
    assert await erasure_fences_event(
        TENANT, user_id=USER, anonymous_id="anon", received_at="2026-05-01T00:00:00Z", repo=repo,
    ) is False
    assert repo.reads == 2


async def test_later_erasure_advances_the_marker():
    from services.consent.erasure_fence import erasure_fences_event

    tenant = _uid("t")
    await _dsr_record(tenant, submitted_at="2026-05-02T00:00:00+00:00")
    await _dsr_record(tenant, submitted_at="2026-05-04T00:00:00+00:00")
    await _dsr_record(tenant, submitted_at="2026-05-03T00:00:00+00:00")

    assert await erasure_fences_event(
        tenant, user_id=USER, anonymous_id=None, received_at="2026-05-03T12:00:00Z",
    ) is True
    assert await erasure_fences_event(
        tenant, user_id=USER, anonymous_id=None, received_at="2026-05-05T00:00:00Z",
    ) is False


async def test_overlapping_erasures_never_rewind_the_marker():
    """Advancing is a max, not read-then-write: an older erasure applied last
    must not replace a newer submission time."""
    from services.consent.erasure_fence import ErasureMarkerRepository, erasure_marker_id

    repo = ErasureMarkerRepository()
    marker = erasure_marker_id("t-race", "user_id", USER)
    await repo.advance(marker, "t-race", "user_id", "2026-05-04T00:00:00.000000Z")
    await repo.advance(marker, "t-race", "user_id", "2026-05-02T00:00:00.000000Z")

    assert (await repo.find_by_id(marker))["submitted_at"] == "2026-05-04T00:00:00.000000Z"


async def test_erasures_submitted_before_markers_existed_are_backfilled():
    from services.consent import erasure_fence
    from services.consent.erasure_fence import erasure_fences_event

    erasure_fence.reset_backfill_state()
    tenant = _uid("t")
    dsr_id = str(uuid.uuid4())
    await ConsentRepository().insert(f"dsr_{dsr_id}", {
        "tenant_id": tenant, "dsr_id": dsr_id, "user_id": USER, "anonymous_id": "anon-old",
        "request_type": "erasure", "status": "completed",
        "submitted_at": "2026-05-02T00:00:00+00:00",
    })

    for kwargs in ({"user_id": USER, "anonymous_id": None}, {"user_id": None, "anonymous_id": "anon-old"}):
        assert await erasure_fences_event(
            tenant, received_at="2026-05-01T10:00:00Z", **kwargs,
        ) is True
    erasure_fence.reset_backfill_state()
