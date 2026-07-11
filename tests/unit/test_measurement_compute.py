"""Measurement computation bridge — honest rate → plane result.

Proves the engine bridge never emits a bare 0 on missing/insufficient data: a
rate below the metric's sample floor is INSUFFICIENT_DATA with value None, no
sample at all is MISSING_INPUTS, and a sufficient proportion is OBSERVED with a
Wilson interval — and that record_rate persists it into the plane idempotently.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from shared.measurement.compute import build_result, rate_result, record_rate  # noqa: E402
from shared.measurement.context import MeasurementContext  # noqa: E402
from shared.measurement.value_states import ValueState  # noqa: E402

CTX = MeasurementContext(
    tenant_id="t-compute", window_start="2026-07-01T00:00:00+00:00",
    window_end="2026-07-02T00:00:00+00:00",
)


# ── rate_result ──────────────────────────────────────────────────────────────


def test_observed_rate_has_value_and_wilson():
    # conversion_rate min_sample is 30; 50 clicks clears it.
    value, state, unc, suff = rate_result(10, 50, metric_name="conversion_rate")
    assert state is ValueState.OBSERVED
    assert value == 10 / 50
    assert unc is not None and unc.method == "wilson"
    assert unc.lower is not None and unc.upper is not None
    assert unc.lower <= value <= unc.upper
    assert suff["met"] is True


def test_below_floor_is_insufficient_not_zero():
    # 5 clicks is below conversion_rate's min_sample of 30.
    value, state, unc, suff = rate_result(0, 5, metric_name="conversion_rate")
    assert value is None                       # never a bare 0
    assert state is ValueState.INSUFFICIENT_DATA
    assert unc is None and suff["met"] is False


def test_no_sample_is_missing_inputs():
    value, state, unc, _ = rate_result(0, 0, metric_name="conversion_rate")
    assert value is None
    assert state is ValueState.MISSING_INPUTS
    assert unc is None


def test_non_proportion_metric_has_no_wilson():
    # journey_completion_rate is a proportion; a count metric would not get Wilson.
    value, state, unc, _ = rate_result(3, 10, metric_name="attributed_conversions")
    # attributed_conversions min_sample is 1, so 10 trials is OBSERVED, but it is
    # not a [0,1] proportion → no Wilson band.
    assert state is ValueState.OBSERVED
    assert value == 3 / 10
    assert unc is None


# ── build_result ─────────────────────────────────────────────────────────────


def test_build_result_observed():
    result = build_result(CTX, metric_name="conversion_rate", numerator=12, denominator=40)
    assert result.value == 12 / 40
    assert result.value_state is ValueState.OBSERVED
    assert result.context_hash == CTX.context_hash()
    assert result.uncertainty is not None


def test_build_result_insufficient_has_no_value():
    result = build_result(CTX, metric_name="conversion_rate", numerator=1, denominator=3)
    assert result.value is None
    assert result.value_state is ValueState.INSUFFICIENT_DATA


# ── record_rate (into the plane) ─────────────────────────────────────────────


@pytest.fixture()
def repo():
    from repositories.measurement_results_repo import get_measurement_results_repository

    r = get_measurement_results_repository()
    for name in list(vars(r)):
        v = getattr(r, name)
        if isinstance(v, dict):
            v.clear()
    return r


async def test_record_rate_persists_and_is_idempotent(repo):
    row = await record_rate(repo, CTX, metric_name="conversion_rate", numerator=15, denominator=60)
    assert row is not None and row["value_state"] == "observed"
    active = await repo.get_active("t-compute", "conversion_rate", "1", CTX.context_hash())
    assert active is not None and active["id"] == row["id"]
    # A second record for the same context does not raise (reject-active-dup is
    # swallowed) and returns the existing active row.
    again = await record_rate(repo, CTX, metric_name="conversion_rate", numerator=15, denominator=60)
    assert again is not None and again["id"] == row["id"]


async def test_record_rate_insufficient_persists_stateful(repo):
    row = await record_rate(repo, CTX, metric_name="conversion_rate", numerator=0, denominator=4)
    assert row is not None
    assert row["value"] is None and row["value_state"] == "insufficient_data"
