"""Campaign360 communication rates use the governed measurement registry."""

from __future__ import annotations

from shared.measurement.compute import rate_result
from shared.measurement.registry import get_definition
from shared.measurement.value_states import ValueState


def test_campaign_rate_definitions_are_registry_backed():
    for name in (
        "email_open_rate",
        "email_click_rate",
        "email_reply_rate",
        "machine_event_rate",
    ):
        definition = get_definition(name)
        assert definition is not None
        assert definition.unit == "ratio"
        assert definition.min_sample == 30
        assert (definition.lower, definition.upper) == (0.0, 1.0)


def test_campaign_rate_withholds_small_samples():
    value, state, uncertainty, sufficiency = rate_result(
        5,
        10,
        metric_name="email_click_rate",
    )
    assert value is None
    assert state is ValueState.INSUFFICIENT_DATA
    assert uncertainty is None
    assert sufficiency == {"sample_size": 10, "min_required": 30, "met": False}


def test_campaign_rate_reports_wilson_uncertainty_when_sufficient():
    value, state, uncertainty, sufficiency = rate_result(
        15,
        30,
        metric_name="email_open_rate",
    )
    assert value == 0.5
    assert state is ValueState.OBSERVED
    assert uncertainty is not None
    assert uncertainty.method == "wilson"
    assert sufficiency["met"] is True
