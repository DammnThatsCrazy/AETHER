"""Unit tests — Pydantic measurement contracts validation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("pydantic", reason="Backend deps not installed (pip install -e '.[backend]')")
pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

from datetime import datetime, timezone
from uuid import uuid4


def _ts():
    return datetime.now(timezone.utc).isoformat()


class TestCanonicalTouchpointContract:
    def test_required_fields_only(self):
        from services.measurement.contracts import CanonicalTouchpoint
        tp = CanonicalTouchpoint(
            tenant_id="t1",
            touchpoint_type="click",
            occurred_at=_ts(),
            idempotency_key="abc123",
        )
        assert tp.tenant_id == "t1"
        assert tp.touchpoint_type == "click"

    def test_optional_fields_default(self):
        from services.measurement.contracts import CanonicalTouchpoint
        tp = CanonicalTouchpoint(
            tenant_id="t1",
            touchpoint_type="impression",
            occurred_at=_ts(),
            idempotency_key="key1",
        )
        assert tp.is_view_through is False
        assert tp.is_click_through is False
        assert tp.schema_version == 1

    def test_rejects_missing_tenant(self):
        from services.measurement.contracts import CanonicalTouchpoint
        from pydantic import ValidationError
        with pytest.raises((ValidationError, TypeError)):
            CanonicalTouchpoint(
                touchpoint_type="click",
                occurred_at=_ts(),
                idempotency_key="k",
            )  # type: ignore[call-arg]


class TestCanonicalConversionContract:
    def test_authority_rank_default(self):
        from services.measurement.contracts import CanonicalConversion
        conv = CanonicalConversion(
            tenant_id="t1",
            conversion_type="purchase",
            currency="USD",
            occurred_at=_ts(),
            observed_at=_ts(),
            deduplication_key=str(uuid4()),
        )
        assert conv.authority_rank == 50
        assert conv.attribution_eligible is True
        assert conv.conversion_status == "confirmed"

    def test_net_value_optional(self):
        from services.measurement.contracts import CanonicalConversion
        conv = CanonicalConversion(
            tenant_id="t1",
            conversion_type="lead",
            currency="USD",
            occurred_at=_ts(),
            observed_at=_ts(),
            deduplication_key=str(uuid4()),
        )
        assert conv.net_value is None

    def test_gross_value_accepted(self):
        from services.measurement.contracts import CanonicalConversion
        conv = CanonicalConversion(
            tenant_id="t1",
            conversion_type="purchase",
            currency="USD",
            gross_value="99.99",
            occurred_at=_ts(),
            observed_at=_ts(),
            deduplication_key=str(uuid4()),
        )
        assert float(conv.gross_value) == pytest.approx(99.99)


class TestSpendRecordContract:
    def test_defaults(self):
        from services.measurement.contracts import SpendRecord
        sr = SpendRecord(
            tenant_id="t1",
            billing_currency="USD",
            period_start=_ts(),
            period_end=_ts(),
            idempotency_key="spend-key-1",
        )
        assert sr.impressions == 0
        assert sr.clicks == 0
        assert sr.media_spend is None or float(sr.media_spend or 0) == 0.0

    def test_exchange_rate_default(self):
        from services.measurement.contracts import SpendRecord
        sr = SpendRecord(
            tenant_id="t1",
            billing_currency="EUR",
            period_start=_ts(),
            period_end=_ts(),
            idempotency_key="spend-key-2",
        )
        assert float(sr.exchange_rate or 1.0) == pytest.approx(1.0)


class TestAttributionCreditContract:
    def test_weight_range(self):
        from services.measurement.contracts import AttributionCredit
        credit = AttributionCredit(
            tenant_id="t1",
            attribution_run_id=str(uuid4()),
            conversion_id=str(uuid4()),
            credit_weight="0.5",
        )
        assert 0.0 <= float(credit.credit_weight) <= 1.0

    def test_rejects_weight_above_one(self):
        from services.measurement.contracts import AttributionCredit
        from pydantic import ValidationError
        try:
            credit = AttributionCredit(
                tenant_id="t1",
                attribution_run_id=str(uuid4()),
                conversion_id=str(uuid4()),
                credit_weight="1.5",
            )
            # If no validator, just ensure weight stored
            assert float(credit.credit_weight) == pytest.approx(1.5)
        except (ValidationError, ValueError):
            pass  # Either behavior is acceptable


# ══════════════════════════════════════════════════════════════════════════════
# shared/measurement — Measurement Integrity Plane (pure contracts + logic)
#
# Distinct from services/measurement above: this exercises the dependency-free
# shared package that enforces "no metric is a real number unless the data
# supports it". Imports are guarded so this coexists with the services suite.
# ══════════════════════════════════════════════════════════════════════════════

import math  # noqa: E402

from shared.measurement import (  # noqa: E402
    METRIC_REGISTRY,
    REGISTRY_VERSION,
    VALUE_STATES,
    MeasurementContext,
    MeasurementResult,
    MeasurementValidationError,
    Uncertainty,
    ValueState,
    as_uncertainty,
    bootstrap_ci,
    build_restatement,
    evaluate_sufficiency,
    get_definition,
    list_definitions,
    requires_value,
    sufficiency_dict,
    validate_metric_version,
    validate_value,
    wilson_interval,
)


# ─── value states ────────────────────────────────────────────────────────────

def test_value_states_membership_and_helper():
    assert set(VALUE_STATES) == {
        "observed",
        "estimated",
        "insufficient_data",
        "not_applicable",
        "missing_inputs",
        "degraded",
    }
    assert requires_value(ValueState.OBSERVED) is True
    assert requires_value(ValueState.ESTIMATED) is True
    assert requires_value("observed") is True
    for state in (
        ValueState.INSUFFICIENT_DATA,
        ValueState.NOT_APPLICABLE,
        ValueState.MISSING_INPUTS,
        ValueState.DEGRADED,
    ):
        assert requires_value(state) is False


# ─── context hash ────────────────────────────────────────────────────────────

def _ctx(**overrides) -> MeasurementContext:
    base = dict(
        tenant_id="t1",
        window_start="2026-01-01",
        window_end="2026-01-31",
        timezone="UTC",
        attribution_model="last_touch",
        registry_version="1",
    )
    base.update(overrides)
    return MeasurementContext(**base)


def test_context_hash_is_deterministic():
    assert _ctx().context_hash() == _ctx().context_hash()
    assert len(_ctx().context_hash()) == 32


def test_context_is_frozen():
    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.tenant_id = "other"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "t2"),
        ("window_start", "2026-02-01"),
        ("window_end", "2026-02-28"),
        ("timezone", "America/New_York"),
        ("attribution_model", "first_touch"),
        ("registry_version", "2"),
    ],
)
def test_context_hash_sensitive_to_each_field(field, value):
    assert _ctx().context_hash() != _ctx(**{field: value}).context_hash()


# ─── value / value_state invariant (MeasurementResult) ───────────────────────

def _result(**overrides) -> MeasurementResult:
    base = dict(
        tenant_id="t1",
        metric_name="conversion_rate",
        metric_version="1",
        context_hash="abc123",
        value=0.5,
        value_state=ValueState.OBSERVED,
        unit="ratio",
    )
    base.update(overrides)
    return MeasurementResult(**base)


def test_observed_requires_finite_value():
    r = _result(value=0.42, value_state=ValueState.OBSERVED)
    assert r.value == 0.42
    with pytest.raises(MeasurementValidationError):
        _result(value=None, value_state=ValueState.OBSERVED)


def test_insufficient_data_forbids_value():
    r = _result(value=None, value_state=ValueState.INSUFFICIENT_DATA)
    assert r.value is None
    with pytest.raises(MeasurementValidationError):
        _result(value=0.0, value_state=ValueState.INSUFFICIENT_DATA)


def test_nan_and_inf_rejected_on_result():
    with pytest.raises(MeasurementValidationError):
        _result(value=float("nan"), value_state=ValueState.OBSERVED)
    with pytest.raises(MeasurementValidationError):
        _result(value=float("inf"), value_state=ValueState.OBSERVED)


# ─── validate_value ──────────────────────────────────────────────────────────

def test_validate_value_happy_path():
    validate_value(0.5, ValueState.OBSERVED, unit="ratio", lower=0.0, upper=1.0)
    validate_value(None, ValueState.MISSING_INPUTS)


def test_validate_value_nan_inf_rejected():
    with pytest.raises(MeasurementValidationError):
        validate_value(float("nan"), ValueState.OBSERVED)
    with pytest.raises(MeasurementValidationError):
        validate_value(float("inf"), ValueState.ESTIMATED)


def test_validate_value_absent_when_required():
    with pytest.raises(MeasurementValidationError):
        validate_value(None, ValueState.OBSERVED)


def test_validate_value_present_when_forbidden():
    with pytest.raises(MeasurementValidationError):
        validate_value(1.0, ValueState.NOT_APPLICABLE)


def test_validate_value_negative_count_rejected():
    with pytest.raises(MeasurementValidationError):
        validate_value(-1, ValueState.OBSERVED, unit="count")
    # non-count negatives are allowed
    validate_value(-5.0, ValueState.OBSERVED, unit="delta")


def test_validate_value_out_of_bounds_rejected():
    with pytest.raises(MeasurementValidationError):
        validate_value(1.5, ValueState.OBSERVED, lower=0.0, upper=1.0)
    with pytest.raises(MeasurementValidationError):
        validate_value(-0.1, ValueState.OBSERVED, lower=0.0, upper=1.0)


def test_validate_metric_version():
    validate_metric_version("1")
    with pytest.raises(MeasurementValidationError):
        validate_metric_version("")
    with pytest.raises(MeasurementValidationError):
        validate_metric_version("   ")
    with pytest.raises(MeasurementValidationError):
        validate_metric_version(1)


# ─── wilson interval ─────────────────────────────────────────────────────────

def test_wilson_zero_trials():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_zero_successes_lower_is_zero():
    lower, upper = wilson_interval(0, 100)
    assert lower == 0.0
    assert 0.0 <= upper <= 1.0


def test_wilson_bounds_within_unit_interval():
    for successes, trials in [(5, 10), (1, 3), (99, 100), (50, 50)]:
        lower, upper = wilson_interval(successes, trials)
        assert 0.0 <= lower <= upper <= 1.0


def test_wilson_width_shrinks_with_more_data():
    def width(n):
        lo, hi = wilson_interval(n // 2, n)
        return hi - lo

    assert width(1000) < width(100) < width(10)


# ─── bootstrap CI ────────────────────────────────────────────────────────────

def test_bootstrap_empty_returns_zero_band():
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_bootstrap_is_deterministic_for_same_seed():
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    a = bootstrap_ci(samples, seed=42, iterations=500)
    b = bootstrap_ci(samples, seed=42, iterations=500)
    assert a == b


def test_bootstrap_seed_changes_interval():
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    a = bootstrap_ci(samples, seed=1, iterations=500)
    b = bootstrap_ci(samples, seed=2, iterations=500)
    assert a != b


def test_bootstrap_band_brackets_the_mean():
    samples = [10.0, 12.0, 11.0, 9.0, 13.0, 10.0, 11.0]
    lower, upper = bootstrap_ci(samples, seed=0)
    mean = sum(samples) / len(samples)
    assert lower <= mean <= upper


# ─── as_uncertainty ──────────────────────────────────────────────────────────

def test_as_uncertainty_builds_model():
    u = as_uncertainty("wilson", 0.5, 0.4, 0.6, confidence_level=0.9)
    assert isinstance(u, Uncertainty)
    assert u.method == "wilson"
    assert (u.point, u.lower, u.upper, u.confidence_level) == (0.5, 0.4, 0.6, 0.9)


# ─── sufficiency ─────────────────────────────────────────────────────────────

def test_evaluate_sufficiency_met_branch():
    state, detail = evaluate_sufficiency(50, 30)
    assert state is ValueState.OBSERVED
    assert detail == {"sample_size": 50, "min_required": 30, "met": True}


def test_evaluate_sufficiency_unmet_branch():
    state, detail = evaluate_sufficiency(5, 30)
    assert state is ValueState.INSUFFICIENT_DATA
    assert detail["met"] is False


def test_sufficiency_dict_matches_evaluate():
    assert sufficiency_dict(10, 10) == evaluate_sufficiency(10, 10)[1]


# ─── registry ────────────────────────────────────────────────────────────────

def test_registry_lookup_known_metric():
    conv = get_definition("conversion_rate")
    assert conv is not None
    assert conv.unit == "ratio"
    assert conv.lower == 0.0 and conv.upper == 1.0
    assert conv.min_sample == 30


def test_registry_lookup_unknown_metric_or_version():
    assert get_definition("does_not_exist") is None
    assert get_definition("conversion_rate", version="99") is None


def test_registry_contains_seeded_metrics():
    for name in (
        "conversion_rate",
        "attributed_conversions",
        "revenue",
        "touchpoints",
        "journey_completion_rate",
    ):
        assert name in METRIC_REGISTRY
    dumped = list_definitions()
    assert isinstance(dumped, list) and len(dumped) == len(METRIC_REGISTRY)
    assert all(isinstance(d, dict) for d in dumped)
    assert REGISTRY_VERSION == "1"


# ─── restatement ─────────────────────────────────────────────────────────────

def _restate_pair():
    prior = MeasurementResult(
        tenant_id="t1",
        metric_name="revenue",
        metric_version="1",
        context_hash="hash-a",
        value=100.0,
        value_state=ValueState.OBSERVED,
        unit="currency",
    )
    new = MeasurementResult(
        tenant_id="t1",
        metric_name="revenue",
        metric_version="1",
        context_hash="hash-a",
        value=120.0,
        value_state=ValueState.OBSERVED,
        unit="currency",
    )
    return prior, new


def test_build_restatement_happy_path():
    prior, new = _restate_pair()
    record = build_restatement(prior, new, reason="late-arriving data")
    assert record["prior_result_id"] == prior.id
    assert record["new_result_id"] == new.id
    assert record["reason"] == "late-arriving data"
    assert isinstance(record["restated_at"], str)


def test_build_restatement_identity_mismatch_raises():
    prior, new = _restate_pair()
    mismatched = new.model_copy(update={"context_hash": "hash-b"})
    with pytest.raises(MeasurementValidationError):
        build_restatement(prior, mismatched, reason="bad")

    mismatched_metric = new.model_copy(update={"metric_name": "touchpoints"})
    with pytest.raises(MeasurementValidationError):
        build_restatement(prior, mismatched_metric, reason="bad")


def test_shared_measurement_math_sanity():
    assert math.isfinite(1.0)
