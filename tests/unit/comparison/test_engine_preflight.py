"""Data-truth preflight: missing data is NEVER equality.

Empty-vs-empty yields an explicit refusal (typed reason + fact-linkage
states) and a ``suppressed`` run — never a completed run with "no
differences". Also covers the full run state machine happy path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from comparison_fakes import FakeAnalytics, make_events

from services.intelligence.comparison.collection import AnalyticsDimensionCollector
from services.intelligence.comparison.contracts import (
    BaselineSpec,
    ComparisonDefinition,
    ComparisonSubject,
)
from services.intelligence.comparison.engine import (
    RUN_STATE_TRANSITIONS,
    ComparisonEngine,
    preflight_dimension,
    validate_definition,
)
from services.intelligence.comparison.findings import FindingsService
from services.intelligence.comparison.generated_vocabulary import (
    COMPARISON_RUN_STATES,
    FACT_LINKAGE_STATES,
)
from services.intelligence.comparison.store import (
    ComparisonDefinitionRepository,
    ComparisonFindingRepository,
)

TENANT = "t1"


def make_engine(fake_analytics: FakeAnalytics) -> ComparisonEngine:
    collector = AnalyticsDimensionCollector(fake_analytics)
    return ComparisonEngine(collector)


async def store_definition(
    *,
    mode: str = "entity_vs_entity",
    subject_id: str = "user-a",
    baseline: BaselineSpec | None = None,
    dimensions: list[str] | None = None,
) -> ComparisonDefinition:
    definition = ComparisonDefinition(
        definition_id="def-1",
        tenant_id=TENANT,
        mode=mode,
        subject=ComparisonSubject(subject_type="entity", subject_id=subject_id),
        baseline=baseline
        or BaselineSpec(
            baseline_type="entity",
            subject=ComparisonSubject(subject_type="entity", subject_id="user-b"),
        ),
        dimensions=dimensions or ["behavior"],
    )
    await ComparisonDefinitionRepository().upsert_scoped(
        TENANT, definition.definition_id, definition.model_dump(mode="json")
    )
    return definition


class TestStateMachineShape:
    def test_transitions_only_use_registry_states(self):
        for state, targets in RUN_STATE_TRANSITIONS.items():
            assert state in COMPARISON_RUN_STATES
            for target in targets:
                assert target in COMPARISON_RUN_STATES

    def test_all_registry_states_are_modeled(self):
        assert set(RUN_STATE_TRANSITIONS) == set(COMPARISON_RUN_STATES)


class TestEmptyVsEmptyRefusal:
    async def test_empty_vs_empty_suppresses_run_with_refusal(self, fake_analytics):
        # Neither subject nor baseline has ANY events.
        engine = make_engine(fake_analytics)
        await store_definition()
        run = await engine.create_run(TENANT, "def-1")
        final = await engine.execute_run(TENANT, run["run_id"])

        assert final["state"] == "suppressed"
        assert final["degraded_reason"] == "all_dimensions_refused_by_data_truth_preflight"
        assert final["finding_count"] == 0

        truth = final["data_truth"]
        assert len(truth) == 1
        entry = truth[0]
        assert entry["decision"] == "refuse"
        assert entry["refusal_reason"] == "empty_vs_empty_no_evidence_on_either_side"
        assert entry["subject_state"] == "empty"
        assert entry["baseline_state"] == "empty"
        assert entry["subject_fact_linkage"] in FACT_LINKAGE_STATES
        assert entry["baseline_fact_linkage"] in FACT_LINKAGE_STATES

        # And crucially: no findings were minted for the "equality".
        findings = await ComparisonFindingRepository().list_scoped(TENANT)
        assert findings == []

    async def test_uncollectable_dimension_refuses(self, fake_analytics):
        engine = make_engine(fake_analytics)
        # "trust" has no observation source registered in the collector.
        await store_definition(dimensions=["trust"])
        run = await engine.create_run(TENANT, "def-1")
        final = await engine.execute_run(TENANT, run["run_id"])
        assert final["state"] == "suppressed"
        assert final["data_truth"][0]["refusal_reason"] == (
            "dimension_has_no_observation_source"
        )

    async def test_one_sided_data_is_compared_not_refused(self, fake_analytics):
        # Subject active, baseline entity silent → absence is a real,
        # comparable difference (not empty-vs-empty).
        fake_analytics.seed(TENANT, "user-a", make_events(20))
        engine = make_engine(fake_analytics)
        await store_definition()
        run = await engine.create_run(TENANT, "def-1")
        final = await engine.execute_run(TENANT, run["run_id"])
        assert final["state"] in ("completed", "completed_degraded")
        entry = final["data_truth"][0]
        assert entry["decision"] == "compare"
        assert entry["baseline_state"] == "empty"


class TestPreflightUnit:
    def test_preflight_states(self, fake_analytics):
        from services.intelligence.comparison.collection import DimensionObservations

        empty = DimensionObservations(
            dimension="behavior", collectable=True, observation_count=0
        )
        ready = DimensionObservations(
            dimension="behavior", collectable=True, observation_count=5
        )
        entry = preflight_dimension(empty, empty)
        assert (entry.decision, entry.refusal_reason) == (
            "refuse", "empty_vs_empty_no_evidence_on_either_side"
        )
        assert preflight_dimension(ready, empty).decision == "compare"
        assert preflight_dimension(empty, ready).decision == "compare"
        assert preflight_dimension(ready, ready).decision == "compare"


class TestHappyPath:
    async def test_entity_vs_entity_produces_findings_and_states(self, fake_analytics):
        now = datetime.now(timezone.utc)
        fake_analytics.seed(TENANT, "user-a", make_events(40, end=now, spacing_hours=6))
        fake_analytics.seed(TENANT, "user-b", make_events(5, end=now, spacing_hours=6))
        engine = make_engine(fake_analytics)
        await store_definition()
        run = await engine.create_run(TENANT, "def-1")
        final = await engine.execute_run(TENANT, run["run_id"])

        assert final["state"] == "completed"
        states = [h["state"] for h in final["state_history"]]
        assert states == [
            "queued", "resolving", "collecting", "aligning",
            "computing", "scoring", "completed",
        ]
        assert final["alignment_outcome"] == "aligned"
        assert final["finding_count"] > 0

        findings = await FindingsService().list(TENANT, run_id=run["run_id"])
        assert findings
        for f in findings:
            assert f["causal_claim"] == "observed"
            assert f["severity"] is not None
            assert f["materiality"] is not None

    async def test_execute_is_idempotent_on_terminal_runs(self, fake_analytics):
        engine = make_engine(fake_analytics)
        await store_definition()
        run = await engine.create_run(TENANT, "def-1")
        first = await engine.execute_run(TENANT, run["run_id"])
        second = await engine.execute_run(TENANT, run["run_id"])
        assert second["state"] == first["state"]

    async def test_stale_queued_run_expires(self, fake_analytics):
        engine = make_engine(fake_analytics)
        await store_definition()
        run = await engine.create_run(TENANT, "def-1")
        stale = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        await engine._runs.update_scoped(TENANT, run["run_id"], {"requested_at": stale})
        final = await engine.execute_run(TENANT, run["run_id"])
        assert final["state"] == "expired"


class TestModeValidation:
    async def test_mode_baseline_compatibility_enforced(self):
        from shared.common.common import BadRequestError

        definition = ComparisonDefinition(
            definition_id="def-x",
            tenant_id=TENANT,
            mode="entity_vs_cohort",
            subject=ComparisonSubject(subject_type="entity", subject_id="u"),
            baseline=BaselineSpec(baseline_type="historical"),
        )
        with pytest.raises(BadRequestError, match="does not accept baseline type"):
            validate_definition(definition)

    async def test_unknown_dimension_rejected(self):
        definition = ComparisonDefinition(
            definition_id="def-x",
            tenant_id=TENANT,
            mode="entity_vs_history",
            subject=ComparisonSubject(subject_type="entity", subject_id="u"),
            baseline=BaselineSpec(baseline_type="rolling_history", rolling_window_days=7),
            dimensions=["nonsense"],
        )
        with pytest.raises(ValueError, match="Unknown comparison dimensions"):
            validate_definition(definition)

    async def test_baseline_unresolved_fails_run_explicitly(self, fake_analytics):
        engine = make_engine(fake_analytics)
        # rolling_history without rolling_window_days cannot resolve.
        await store_definition(
            mode="entity_vs_history",
            baseline=BaselineSpec(baseline_type="rolling_history"),
        )
        run = await engine.create_run(TENANT, "def-1")
        final = await engine.execute_run(TENANT, run["run_id"])
        assert final["state"] == "failed"
        assert final["error_code"] == "baseline_unresolved"
        assert "rolling_window_days" in final["degraded_reason"]
