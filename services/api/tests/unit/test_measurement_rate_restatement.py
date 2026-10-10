"""Regression tests for rate restatement through the integrity plane."""

from __future__ import annotations

import pytest

from repositories.measurement_results_repo import MeasurementResultsRepository
from shared.measurement.compute import record_rate
from shared.measurement.context import MeasurementContext


@pytest.fixture
def context() -> MeasurementContext:
    return MeasurementContext(
        tenant_id="tenant-a",
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-07-02T00:00:00Z",
        attribution_model="last_touch",
        registry_version="1",
    )


@pytest.fixture(autouse=True)
def local_results_backend(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(
        "repositories.measurement_results_repo.get_pool",
        no_pool,
    )


@pytest.mark.asyncio
async def test_record_rate_restatement_supersedes_instead_of_overwriting(
    context: MeasurementContext,
) -> None:
    repo = MeasurementResultsRepository()
    original = await record_rate(
        repo,
        context,
        metric_name="conversion_rate",
        numerator=20,
        denominator=100,
        lineage={"attribution_run_id": "run-before-repair"},
    )

    restated = await record_rate(
        repo,
        context,
        metric_name="conversion_rate",
        numerator=35,
        denominator=100,
        lineage={"attribution_run_id": "run-after-repair"},
        restatement_reason="source classification repair to 2.0",
    )

    assert original is not None
    assert restated is not None
    assert original["id"] != restated["id"]
    assert restated["value"] == pytest.approx(0.35)
    assert restated["lineage"] == {
        "attribution_run_id": "run-after-repair",
        "restatement_reason": "source classification repair to 2.0",
    }

    chain = await repo.restatement_chain("tenant-a", restated["id"])
    assert [row["id"] for row in chain] == [original["id"], restated["id"]]
    assert chain[0]["value"] == pytest.approx(0.2)
    assert chain[0]["superseded_by"] == restated["id"]
    assert chain[1]["superseded_by"] is None

    audit = await repo.list_restatements("tenant-a")
    assert len(audit) == 1
    assert audit[0]["prior_result_id"] == original["id"]
    assert audit[0]["new_result_id"] == restated["id"]
    assert audit[0]["reason"] == "source classification repair to 2.0"


@pytest.mark.asyncio
async def test_restatement_reason_without_prior_result_creates_initial_active_result(
    context: MeasurementContext,
) -> None:
    repo = MeasurementResultsRepository()

    result = await record_rate(
        repo,
        context,
        metric_name="conversion_rate",
        numerator=30,
        denominator=100,
        restatement_reason="repair found no prior publication",
    )

    assert result is not None
    assert result["value"] == pytest.approx(0.3)
    assert result["superseded_by"] is None
    assert await repo.list_restatements("tenant-a") == []
