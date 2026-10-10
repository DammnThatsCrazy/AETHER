"""Public status history: rollup math, sampling, storage and the HTTP feed.

``GET /v1/status/history`` feeds the public status page's 90-day bars
(``apps/public-site/src/site/status.ts`` ``parseHistory``/``fillDays``). The
contract these tests pin:

1. Scoring — unknown samples are unobserved (excluded from the denominator);
   degraded counts as available; any down sample makes the day an outage and
   keeps its uptime strictly below 100; a day with nothing observed is omitted,
   never reported as 0% or 100%.
2. Input — ``days`` defaults to 90 and must be 1..90.
3. Shape — ``{"components": [{"name", "days": [{"date", "status",
   "uptime_pct"}]}], "incidents": []}``, aggregate only.
4. Sampling — the ``/v1/health`` verdict is recorded at most once per interval
   per process, after the response, and a failed write never fails liveness.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.gateway import component_status as cs
from services.gateway import routes as gateway_routes
from services.gateway import status_history as sh
from services.gateway import status_history_repository as repo_mod
from services.gateway.status_history_repository import DailyRollup, StatusHistoryRepository

TODAY = date(2026, 9, 27)
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260927_status_component_daily.py"
)


def rollup(day: date, component: str = "api", **counts: int) -> DailyRollup:
    return DailyRollup(day=day, component=component, **counts)


@pytest.fixture(autouse=True)
def in_memory_store(monkeypatch: pytest.MonkeyPatch):
    """Force the repository onto its in-memory path and reset shared state."""

    async def _no_pool():
        return None

    monkeypatch.setattr(repo_mod, "get_pool", _no_pool)
    repo_mod.reset_status_history_store()
    sh.service.clear_cache()
    yield
    repo_mod.reset_status_history_store()
    sh.service.clear_cache()


# ── 1. scoring ───────────────────────────────────────────────────────────────


def test_all_ok_day_is_operational_at_100():
    assert sh.score_day(rollup(TODAY, ok=288)) == {
        "date": "2026-09-27",
        "status": "operational",
        "uptime_pct": 100.0,
    }


def test_degraded_samples_count_as_available_but_mark_the_day():
    entry = sh.score_day(rollup(TODAY, ok=280, degraded=8))
    assert entry["status"] == "degraded"
    assert entry["uptime_pct"] == 100.0


def test_down_samples_reduce_uptime_and_make_the_day_an_outage():
    entry = sh.score_day(rollup(TODAY, ok=287, down=1))
    assert entry["status"] == "outage"
    # 287/288 = 99.6527… → floored, never rounded up.
    assert entry["uptime_pct"] == 99.65


def test_any_down_sample_never_displays_as_100_percent():
    entry = sh.score_day(rollup(TODAY, ok=999_999, down=1))
    assert entry["uptime_pct"] < 100.0
    assert entry["uptime_pct"] == 99.99


def test_unknown_samples_are_excluded_from_the_denominator():
    entry = sh.score_day(rollup(TODAY, ok=3, down=1, unknown=500))
    assert entry["uptime_pct"] == 75.0


def test_day_with_only_unknown_samples_is_omitted_not_zero_or_hundred():
    assert sh.score_day(rollup(TODAY, unknown=12)) is None
    assert sh.score_day(rollup(TODAY)) is None


def test_all_down_day_is_zero_percent_outage():
    assert sh.score_day(rollup(TODAY, down=4)) == {
        "date": "2026-09-27",
        "status": "outage",
        "uptime_pct": 0.0,
    }


# ── 2. window / input validation ─────────────────────────────────────────────


def test_window_is_inclusive_and_ends_today():
    assert sh.history_window(90, TODAY) == (TODAY - timedelta(days=89), TODAY)
    assert sh.history_window(1, TODAY) == (TODAY, TODAY)


@pytest.mark.parametrize("days", [0, -1, 91, 365])
def test_window_rejects_out_of_range_days(days: int):
    with pytest.raises(ValueError):
        sh.history_window(days, TODAY)


# ── 3. payload assembly ──────────────────────────────────────────────────────


def test_build_history_omits_days_without_samples_and_orders_oldest_first():
    rollups = [
        rollup(TODAY, ok=10),
        rollup(TODAY - timedelta(days=2), ok=5, down=5),
        rollup(TODAY - timedelta(days=1), unknown=7),  # nothing observed
    ]
    body = sh.build_history(rollups, days=90, today=TODAY, generated_at=NOW)

    api = next(c for c in body["components"] if c["name"] == "api")
    assert [d["date"] for d in api["days"]] == ["2026-09-25", "2026-09-27"]
    assert api["days"][0] == {"date": "2026-09-25", "status": "outage", "uptime_pct": 50.0}


def test_build_history_lists_every_published_component_even_without_data():
    body = sh.build_history([], days=90, today=TODAY, generated_at=NOW)

    assert [c["name"] for c in body["components"]] == list(sh.HISTORY_COMPONENTS)
    assert all(c["days"] == [] for c in body["components"])
    assert body["incidents"] == []
    assert body["window_days"] == 90
    assert body["start_date"] == "2026-06-30"
    assert body["end_date"] == "2026-09-27"


def test_build_history_drops_out_of_window_days_and_unpublished_components():
    rollups = [
        rollup(TODAY - timedelta(days=90), ok=1),  # one day before a 90-day window
        rollup(TODAY + timedelta(days=1), ok=1),  # clock skew: tomorrow
        rollup(TODAY, component="internal-db-primary.example", ok=1),
        rollup(TODAY, component="identity", ok=1),
    ]
    body = sh.build_history(rollups, days=90, today=TODAY, generated_at=NOW)

    names = [c["name"] for c in body["components"]]
    assert "internal-db-primary.example" not in names
    assert next(c for c in body["components"] if c["name"] == "api")["days"] == []
    identity = next(c for c in body["components"] if c["name"] == "identity")
    assert [d["date"] for d in identity["days"]] == ["2026-09-27"]


def test_build_history_merges_duplicate_rows_for_the_same_day():
    rollups = [rollup(TODAY, ok=3), rollup(TODAY, down=1)]
    body = sh.build_history(rollups, days=1, today=TODAY, generated_at=NOW)
    api = body["components"][0]
    assert api["days"] == [{"date": "2026-09-27", "status": "outage", "uptime_pct": 75.0}]


def test_history_components_cover_the_live_health_components_plus_api():
    assert sh.HISTORY_COMPONENTS[0] == "api"
    assert set(sh.HISTORY_COMPONENTS[1:]) == set(cs.COMPONENT_NAMES)


# ── 4. sampling from the health verdict ──────────────────────────────────────


def test_samples_map_the_health_verdict_per_component():
    components = {name: {"status": cs.STATUS_OK} for name in cs.COMPONENT_NAMES}
    components["identity"] = {"status": cs.STATUS_DOWN}
    components["agent"] = {"status": "mystery"}
    components["not-a-component"] = {"status": cs.STATUS_OK}

    samples = sh.samples_from_health(overall_healthy=False, components=components)

    assert samples["api"] == cs.STATUS_DEGRADED
    assert samples["identity"] == cs.STATUS_DOWN
    assert samples["agent"] == cs.STATUS_UNKNOWN
    assert samples["ingestion"] == cs.STATUS_OK
    assert "not-a-component" not in samples
    assert set(samples) == set(sh.HISTORY_COMPONENTS)


def test_missing_component_entry_is_sampled_unknown():
    samples = sh.samples_from_health(overall_healthy=True, components={})
    assert samples["api"] == cs.STATUS_OK
    assert {samples[name] for name in cs.COMPONENT_NAMES} == {cs.STATUS_UNKNOWN}


# ── 5. repository ────────────────────────────────────────────────────────────


def test_repository_accumulates_samples_per_day_and_component():
    store = StatusHistoryRepository()

    async def _run():
        await store.record(NOW, {"api": "ok", "identity": "down"})
        await store.record(NOW + timedelta(minutes=5), {"api": "degraded", "identity": "ok"})
        await store.record(NOW + timedelta(days=1), {"api": "ok"})
        return await store.read_window(TODAY, TODAY)

    rows = asyncio.run(_run())
    assert rows == [
        DailyRollup(day=TODAY, component="api", ok=1, degraded=1),
        DailyRollup(day=TODAY, component="identity", ok=1, down=1),
    ]


def test_repository_buckets_by_utc_day():
    store = StatusHistoryRepository()
    late_pacific = datetime(2026, 9, 26, 20, 0, tzinfo=timezone(timedelta(hours=-7)))

    async def _run():
        await store.record(late_pacific, {"api": "ok"})
        return await store.read_window(TODAY, TODAY)

    assert [r.day for r in asyncio.run(_run())] == [TODAY]


def test_repository_prunes_rows_before_the_retention_cutoff():
    store = StatusHistoryRepository()

    async def _run():
        await store.record(NOW - timedelta(days=10), {"api": "ok"})
        await store.record(NOW, {"api": "ok"}, prune_before=TODAY - timedelta(days=5))
        return await store.read_window(TODAY - timedelta(days=30), TODAY)

    assert [r.day for r in asyncio.run(_run())] == [TODAY]


def test_repository_rejects_naive_timestamps_and_unknown_statuses():
    store = StatusHistoryRepository()
    with pytest.raises(ValueError):
        asyncio.run(store.record(datetime(2026, 9, 27, 12, 0), {"api": "ok"}))
    with pytest.raises(ValueError):
        asyncio.run(store.record(NOW, {"api": "healthy"}))


def test_repository_sql_path_upserts_additively_in_one_statement():
    class _Pool:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[Any, ...]]] = []

        async def execute(self, sql: str, *args: Any) -> str:
            self.calls.append((sql, args))
            return "INSERT 0 2"

    pool = _Pool()
    store = StatusHistoryRepository()
    store._pool = pool  # noqa: SLF001 - exercising the SQL path without Postgres

    asyncio.run(
        store.record(
            NOW, {"identity": "down", "api": "ok"}, prune_before=date(2025, 8, 23)
        )
    )

    ddl, upsert, prune = pool.calls
    assert ddl[0] == repo_mod.SCHEMA_SQL
    sql, args = upsert
    assert "ON CONFLICT (day, component) DO UPDATE" in sql
    assert "status_component_daily.ok_samples + EXCLUDED.ok_samples" in sql
    day, names, ok, degraded, down, at, unknown = args
    assert day == TODAY and at == NOW
    assert names == ["api", "identity"]
    assert (ok, degraded, down, unknown) == ([1, 0], [0, 0], [0, 1], [0, 0])
    assert prune == (repo_mod._PRUNE_SQL, (date(2025, 8, 23),))  # noqa: SLF001


def _migration_schema_sql() -> str:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "SCHEMA_SQL"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("SCHEMA_SQL not found in migration")


def test_repository_ddl_is_string_identical_to_the_migration():
    assert _migration_schema_sql() == repo_mod.SCHEMA_SQL


def test_table_carries_no_tenant_or_free_text_columns():
    ddl = repo_mod.SCHEMA_SQL.lower()
    for forbidden in ("tenant", "host", "error", "detail", "message"):
        assert forbidden not in ddl


# ── 6. recorder ──────────────────────────────────────────────────────────────


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _healthy_components() -> dict[str, dict[str, str]]:
    return {name: {"status": cs.STATUS_OK} for name in cs.COMPONENT_NAMES}


def test_recorder_samples_at_most_once_per_interval():
    mono = _Clock()
    store = StatusHistoryRepository()
    recorder = sh.StatusHistoryRecorder(
        store, interval_seconds=300, enabled=True, clock=lambda: NOW, monotonic=mono
    )

    first = recorder.claim(overall_healthy=True, components=_healthy_components())
    assert first is not None
    mono.now += 299
    assert recorder.claim(overall_healthy=True, components=_healthy_components()) is None
    mono.now += 1
    second = recorder.claim(overall_healthy=False, components=_healthy_components())
    assert second is not None

    async def _run():
        await first()
        await second()
        return await store.read_window(TODAY, TODAY)

    api = next(r for r in asyncio.run(_run()) if r.component == "api")
    assert (api.ok, api.degraded) == (1, 1)


def test_disabled_recorder_never_claims():
    recorder = sh.StatusHistoryRecorder(StatusHistoryRepository(), enabled=False)
    assert recorder.claim(overall_healthy=True, components={}) is None


def test_recorder_env_switch_and_interval(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STATUS_HISTORY_RECORDING_ENABLED", "false")
    monkeypatch.setenv("STATUS_HISTORY_SAMPLE_INTERVAL_SECONDS", "not-a-number")
    recorder = sh.StatusHistoryRecorder(StatusHistoryRepository())
    assert recorder.claim(overall_healthy=True, components={}) is None
    assert recorder._interval == sh.DEFAULT_SAMPLE_INTERVAL_SECONDS  # noqa: SLF001


def test_failed_write_is_swallowed_and_reported_false():
    class _Broken(StatusHistoryRepository):
        async def record(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionRefusedError("db at 10.0.0.5 refused")

    recorder = sh.StatusHistoryRecorder(_Broken(), enabled=True)
    assert asyncio.run(recorder.write(NOW, {"api": "ok"})) is False


def test_slow_write_times_out_instead_of_hanging(monkeypatch: pytest.MonkeyPatch):
    class _Slow(StatusHistoryRepository):
        async def record(self, *args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(10)

    monkeypatch.setattr(sh, "RECORD_TIMEOUT_SECONDS", 0.01)
    recorder = sh.StatusHistoryRecorder(_Slow(), enabled=True)
    assert asyncio.run(recorder.write(NOW, {"api": "ok"})) is False


def test_recorder_prunes_beyond_retention():
    seen: dict[str, Any] = {}

    class _Spy(StatusHistoryRepository):
        async def record(self, at, samples, *, prune_before=None) -> None:
            seen["prune_before"] = prune_before

    asyncio.run(sh.StatusHistoryRecorder(_Spy(), enabled=True).write(NOW, {"api": "ok"}))
    assert seen["prune_before"] == TODAY - timedelta(days=sh.RETENTION_DAYS)


# ── 7. rate limiting / client address ────────────────────────────────────────


def test_rate_limiter_allows_the_budget_then_reports_retry_after():
    clock = _Clock()
    clock.now = 600.0  # start of a minute window
    limiter = sh.PublicIpRateLimiter(3, clock=clock)

    async def _run():
        return [await limiter.check("203.0.113.9") for _ in range(4)]

    results = asyncio.run(_run())
    assert results[:3] == [None, None, None]
    assert results[3] == 60
    # Another caller has its own budget.
    assert asyncio.run(limiter.check("198.51.100.1")) is None


def test_rate_limiter_window_resets():
    clock = _Clock()
    clock.now = 600.0
    limiter = sh.PublicIpRateLimiter(1, clock=clock)
    assert asyncio.run(limiter.check("203.0.113.9")) is None
    assert asyncio.run(limiter.check("203.0.113.9")) is not None
    clock.now = 660.0
    assert asyncio.run(limiter.check("203.0.113.9")) is None


def test_rate_limiter_uses_redis_when_available():
    class _Redis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}
            self.expiries: dict[str, int] = {}

        async def incr(self, key: str) -> int:
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        async def expire(self, key: str, seconds: int) -> None:
            self.expiries[key] = seconds

    redis = _Redis()
    clock = _Clock()
    clock.now = 600.0
    limiter = sh.PublicIpRateLimiter(1, clock=clock)
    assert asyncio.run(limiter.check("203.0.113.9", redis)) is None
    assert asyncio.run(limiter.check("203.0.113.9", redis)) == 60
    assert list(redis.expiries.values()) == [60]


def test_client_ip_uses_the_load_balancer_appended_address():
    headers = {"x-forwarded-for": "1.2.3.4, 203.0.113.9"}
    assert sh.client_ip(headers, "10.0.0.2") == "203.0.113.9"
    assert sh.client_ip({}, "10.0.0.2") == "10.0.0.2"
    assert sh.client_ip({}, None) == "unknown"


# ── 8. HTTP surface ──────────────────────────────────────────────────────────


class _Registry:
    cache = None

    async def health_check(self) -> dict[str, Any]:
        return {name: {"status": "ok"} for name in ("database", "cache", "graph", "event_bus")}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gateway_routes, "get_registry", lambda: _Registry())
    monkeypatch.setattr(sh, "rate_limiter", sh.PublicIpRateLimiter(1000))
    fixed = sh.StatusHistoryService(clock=lambda: NOW)
    monkeypatch.setattr(sh, "service", fixed)
    app = FastAPI()
    app.include_router(gateway_routes.router)
    return TestClient(app)


def _seed(*entries: tuple[date, str, str]) -> None:
    store = StatusHistoryRepository()

    async def _run():
        for day, component, status in entries:
            at = datetime(day.year, day.month, day.day, 6, 0, tzinfo=timezone.utc)
            await store.record(at, {component: status})

    asyncio.run(_run())


def test_history_endpoint_serves_the_site_contract(client: TestClient):
    _seed(
        (TODAY, "api", "ok"),
        (TODAY, "api", "down"),
        (TODAY - timedelta(days=3), "identity", "degraded"),
    )
    response = client.get("/v1/status/history", params={"days": 90})

    assert response.status_code == 200
    assert response.headers["cache-control"] == sh.CACHE_CONTROL
    body = response.json()
    assert set(body) == {
        "generated_at",
        "window_days",
        "start_date",
        "end_date",
        "components",
        "incidents",
    }
    assert body["incidents"] == []
    by_name = {c["name"]: c["days"] for c in body["components"]}
    assert by_name["api"] == [{"date": "2026-09-27", "status": "outage", "uptime_pct": 50.0}]
    assert by_name["identity"] == [
        {"date": "2026-09-24", "status": "degraded", "uptime_pct": 100.0}
    ]
    assert by_name["ingestion"] == []
    for component in body["components"]:
        assert set(component) == {"name", "days"}
        for day in component["days"]:
            assert set(day) == {"date", "status", "uptime_pct"}
            assert day["status"] in {"operational", "degraded", "outage"}


def test_history_endpoint_defaults_to_90_days(client: TestClient):
    body = client.get("/v1/status/history").json()
    assert body["window_days"] == 90
    assert body["start_date"] == "2026-06-30"


@pytest.mark.parametrize("days", ["0", "91", "-5", "abc", "1.5"])
def test_history_endpoint_rejects_invalid_days(client: TestClient, days: str):
    assert client.get("/v1/status/history", params={"days": days}).status_code == 422


def test_history_endpoint_honors_a_shorter_window(client: TestClient):
    _seed((TODAY - timedelta(days=10), "api", "ok"), (TODAY, "api", "ok"))
    body = client.get("/v1/status/history", params={"days": 7}).json()
    api = next(c for c in body["components"] if c["name"] == "api")
    assert [d["date"] for d in api["days"]] == ["2026-09-27"]


def test_history_endpoint_hides_storage_failures(client: TestClient, monkeypatch):
    class _Broken(StatusHistoryRepository):
        async def read_window(self, start: date, end: date):
            raise ConnectionRefusedError("aurora-cluster.internal:5432 refused")

    monkeypatch.setattr(sh, "service", sh.StatusHistoryService(_Broken()))
    response = client.get("/v1/status/history")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "aurora" not in response.text
    assert "ConnectionRefused" not in response.text


def test_history_endpoint_rate_limits_per_client(client: TestClient, monkeypatch):
    monkeypatch.setattr(sh, "rate_limiter", sh.PublicIpRateLimiter(2))
    headers = {"X-Forwarded-For": "203.0.113.9"}
    assert client.get("/v1/status/history", headers=headers).status_code == 200
    assert client.get("/v1/status/history", headers=headers).status_code == 200
    limited = client.get("/v1/status/history", headers=headers)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_history_responses_are_cached_briefly_in_process():
    reads: list[tuple[date, date]] = []

    class _Counting(StatusHistoryRepository):
        async def read_window(self, start: date, end: date):
            reads.append((start, end))
            return []

    mono = _Clock()
    service = sh.StatusHistoryService(_Counting(), clock=lambda: NOW, monotonic=mono)

    async def _run():
        await service.history(90)
        await service.history(90)
        mono.now += sh.RESPONSE_CACHE_SECONDS + 1
        await service.history(90)

    asyncio.run(_run())
    assert len(reads) == 2


def test_health_check_records_one_sample_after_responding(client: TestClient, monkeypatch):
    mono = _Clock()
    recorder = sh.StatusHistoryRecorder(
        StatusHistoryRepository(), interval_seconds=300, enabled=True,
        clock=lambda: NOW, monotonic=mono,
    )
    monkeypatch.setattr(sh, "recorder", recorder)

    assert client.get("/v1/health").status_code == 200
    assert client.get("/v1/health").status_code == 200  # within the interval

    rows = asyncio.run(StatusHistoryRepository().read_window(TODAY, TODAY))
    assert {r.component for r in rows} == set(sh.HISTORY_COMPONENTS)
    assert all(r.ok + r.degraded + r.down + r.unknown == 1 for r in rows)


def test_health_check_stays_200_when_recording_fails(client: TestClient, monkeypatch):
    class _Broken(StatusHistoryRepository):
        async def record(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("DATABASE_URL not set")

    monkeypatch.setattr(sh, "recorder", sh.StatusHistoryRecorder(_Broken(), enabled=True))
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["probe"] == "liveness"
