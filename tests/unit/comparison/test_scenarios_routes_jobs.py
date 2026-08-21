"""Scenario read-only guarantee, route flag-gating, and jobs-plane handler."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from comparison_fakes import FakeAnalytics, make_events

from repositories.repos import _IN_MEMORY_STORES
from shared.auth.auth import TenantContext
from shared.common.common import NotFoundError

from services.intelligence.comparison.collection import AnalyticsDimensionCollector
from services.intelligence.comparison.contracts import (
    BaselineSpec,
    ComparisonDefinition,
    ComparisonSubject,
)
from services.intelligence.comparison.scenarios import ScenarioRunner

TENANT = "t1"


def definition(mode="scenario_vs_current", baseline=None) -> ComparisonDefinition:
    return ComparisonDefinition(
        definition_id="def-1",
        tenant_id=TENANT,
        mode=mode,
        subject=ComparisonSubject(subject_type="entity", subject_id="user-a"),
        baseline=baseline or BaselineSpec(baseline_type="scenario", scenario_id="s1"),
        dimensions=["behavior"],
    )


def _store_snapshot() -> dict[str, int]:
    return {name: len(rows) for name, rows in _IN_MEMORY_STORES.items()}


class TestScenariosReadOnly:
    async def test_scenario_computes_counterfactual_deltas(self, fake_analytics):
        fake_analytics.seed(TENANT, "user-a", make_events(30, spacing_hours=6))
        runner = ScenarioRunner(AnalyticsDimensionCollector(fake_analytics))
        result = await runner.run(
            TENANT, definition(),
            {"behavior": [
                {"name": "events_per_day", "value": 1.0, "unit": "count_per_day"},
                {"name": "event_count", "value": 30.0, "unit": "count", "window_days": 30.0},
                {"name": "distinct_event_types", "value": 1.0, "unit": "types"},
            ]},
            scenario_id="s1",
        )
        assert result.read_only is True
        assert result.causal_claim == "counterfactual_estimate"
        assert result.deltas, "expected counterfactual deltas"
        for delta in result.deltas:
            assert delta.causal_claim == "counterfactual_estimate"

    async def test_scenario_never_writes_anything(self, fake_analytics):
        fake_analytics.seed(TENANT, "user-a", make_events(10))
        runner = ScenarioRunner(AnalyticsDimensionCollector(fake_analytics))
        before = _store_snapshot()
        await runner.run(
            TENANT, definition(),
            {"behavior": [{"name": "events_per_day", "value": 1.0, "unit": "count_per_day"}]},
        )
        assert _store_snapshot() == before, "read-only scenario wrote to a store"

    async def test_empty_subject_yields_refusals_not_deltas(self, fake_analytics):
        runner = ScenarioRunner(AnalyticsDimensionCollector(fake_analytics))
        result = await runner.run(
            TENANT, definition(),
            {"behavior": [{"name": "events_per_day", "value": 1.0, "unit": "count_per_day"}]},
        )
        # Subject empty + scenario baseline non-empty → still comparable
        # (observed zero); scenario with NO params for the dimension refuses.
        empty_params = await runner.run(TENANT, definition(), {})
        assert empty_params.deltas == []
        assert empty_params.refusal_reasons


def _request(tenant_id=TENANT, permissions=None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


def _enable(monkeypatch, enabled=True):
    import services.intelligence.comparison.routes as routes

    monkeypatch.setattr(
        routes, "settings", SimpleNamespace(comparison=SimpleNamespace(enabled=enabled))
    )


class TestRouteFlagGating:
    async def test_handlers_404_when_flag_off(self, monkeypatch):
        import services.intelligence.comparison.routes as routes

        _enable(monkeypatch, enabled=False)
        request = _request()
        with pytest.raises(NotFoundError, match="feature not enabled"):
            await routes.list_definitions(request, limit=100, offset=0)
        with pytest.raises(NotFoundError, match="feature not enabled"):
            await routes.list_findings(
                request, run_id=None, disposition=None, severity=None,
                limit=100, offset=0,
            )
        with pytest.raises(NotFoundError, match="feature not enabled"):
            await routes.list_watchlists(request, limit=100, offset=0)

    async def test_definition_crud_roundtrip_when_enabled(self, monkeypatch):
        import services.intelligence.comparison.routes as routes

        _enable(monkeypatch)
        request = _request()
        created = await routes.create_definition(
            request,
            routes.DefinitionCreateRequest(
                name="a vs b",
                mode="entity_vs_entity",
                subject=ComparisonSubject(subject_type="entity", subject_id="a"),
                baseline=BaselineSpec(
                    baseline_type="entity",
                    subject=ComparisonSubject(subject_type="entity", subject_id="b"),
                ),
                dimensions=["behavior"],
            ),
        )
        definition_id = created.data["definition"]["definition_id"]
        got = await routes.get_definition(request, definition_id)
        assert got.data["definition"]["mode"] == "entity_vs_entity"

        listed = await routes.list_definitions(request, limit=100, offset=0)
        assert len(listed.data["definitions"]) == 1

        # Other tenant sees nothing.
        other = await routes.list_definitions(_request("t2"), limit=100, offset=0)
        assert other.data["definitions"] == []

        deleted = await routes.delete_definition(request, definition_id)
        assert deleted.data["deleted"] == definition_id

    async def test_incompatible_mode_rejected_at_create(self, monkeypatch):
        import services.intelligence.comparison.routes as routes
        from shared.common.common import BadRequestError

        _enable(monkeypatch)
        with pytest.raises(BadRequestError):
            await routes.create_definition(
                _request(),
                routes.DefinitionCreateRequest(
                    mode="entity_vs_cohort",
                    subject=ComparisonSubject(subject_type="entity", subject_id="a"),
                    baseline=BaselineSpec(baseline_type="historical"),
                ),
            )

    async def test_write_requires_write_permission(self, monkeypatch):
        import services.intelligence.comparison.routes as routes
        from shared.common.common import ForbiddenError

        _enable(monkeypatch)
        with pytest.raises(ForbiddenError):
            await routes.upsert_watchlist(
                _request(permissions=["read"]),
                routes.WatchlistUpsertRequest(name="w"),
            )


class TestJobsPlane:
    async def test_run_executes_via_job_handler(self, monkeypatch, fake_analytics):
        """The comparison.run handler drives a queued run to terminal state."""
        from services.intelligence.comparison import jobs as comparison_jobs
        from services.intelligence.comparison.engine import ComparisonEngine
        from services.intelligence.comparison.store import (
            ComparisonDefinitionRepository,
        )
        from services.jobs.handlers import JobContext

        fake_analytics.seed(TENANT, "user-a", make_events(20, spacing_hours=6))
        fake_analytics.seed(TENANT, "user-b", make_events(2, spacing_hours=6))

        engine = ComparisonEngine(AnalyticsDimensionCollector(fake_analytics))
        monkeypatch.setattr(comparison_jobs, "_default_engine", lambda: engine)

        d = definition(
            mode="entity_vs_entity",
            baseline=BaselineSpec(
                baseline_type="entity",
                subject=ComparisonSubject(subject_type="entity", subject_id="user-b"),
            ),
        )
        await ComparisonDefinitionRepository().upsert_scoped(
            TENANT, d.definition_id, d.model_dump(mode="json")
        )
        run = await engine.create_run(TENANT, d.definition_id)

        events: list[tuple[str, dict]] = []

        async def emit_event(event_type: str, payload: dict) -> None:
            events.append((event_type, payload))

        async def heartbeat() -> bool:
            return True

        ctx = JobContext(
            job_id="job-1", tenant_id=TENANT, correlation_id="",
            worker_id="test_worker",
            heartbeat=heartbeat, emit_event=emit_event,
        )
        outcome = await comparison_jobs.run_comparison_job(
            {"run_id": run["run_id"]}, ctx
        )
        assert outcome.status == "succeeded"
        assert outcome.result["state"] in ("completed", "completed_degraded")
        assert [e[0] for e in events] == [
            "comparison.run.started", "comparison.run.finished",
        ]

    async def test_missing_run_id_fails_cleanly(self):
        from services.intelligence.comparison.jobs import run_comparison_job
        from services.jobs.handlers import JobContext

        async def noop_event(_t, _p):
            return None

        async def hb():
            return True

        ctx = JobContext(
            job_id="j", tenant_id=TENANT, correlation_id="",
            worker_id="test_worker",
            heartbeat=hb, emit_event=noop_event,
        )
        outcome = await run_comparison_job({}, ctx)
        assert outcome.status == "failed"
        assert "run_id" in outcome.error

    def test_handler_registration_is_idempotent(self):
        from services.intelligence.comparison.jobs import (
            COMPARISON_RUN_JOB_TYPE,
            register_comparison_handlers,
        )
        from services.jobs.handlers import HANDLER_REGISTRY, unregister_handler

        try:
            register_comparison_handlers()
            register_comparison_handlers()  # no duplicate-registration error
            assert COMPARISON_RUN_JOB_TYPE in HANDLER_REGISTRY
        finally:
            unregister_handler(COMPARISON_RUN_JOB_TYPE)
