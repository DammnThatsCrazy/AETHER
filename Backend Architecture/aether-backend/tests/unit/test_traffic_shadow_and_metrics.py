"""Shadow classification divergence + traffic metric emission."""

from __future__ import annotations

import pytest

from services.traffic import metrics as traffic_metrics
from services.traffic import shadow
from services.traffic.shadow import (
    ShadowDivergenceRepository,
    shadow_compare_rows,
    legacy_source_class,
    _reset_local_divergences,
)
from shared.logger.logger import metrics


@pytest.fixture(autouse=True)
def _clean_shadow_store():
    _reset_local_divergences()
    yield
    _reset_local_divergences()


def _touchpoint_row(**over):
    row = {
        "tenant_id": "tenant-a",
        "source_event_id": "evt-1",
        "touchpoint_id": "11111111-1111-1111-1111-111111111111",
        "source_class": "direct_unknown",
        "proof_level": "none",
        "source_classifier_version": "3.0",
        "attribution_eligible": True,
    }
    row.update(over)
    return row


def test_legacy_reverse_mapping() -> None:
    assert legacy_source_class("direct_unknown") == "direct"
    assert legacy_source_class("paid_search") == "paid"
    assert legacy_source_class("paid_social") == "paid"
    assert legacy_source_class("display") == "paid"
    # Legacy-representable classes map to themselves (no divergence).
    assert legacy_source_class("organic_search") == "organic_search"
    assert legacy_source_class("email") == "email"


@pytest.mark.asyncio
async def test_shadow_records_divergence_and_does_not_mutate_rows() -> None:
    rows = [_touchpoint_row(source_class="paid_search", source_event_id="evt-paid")]
    before = dict(rows[0])

    recorded = await shadow_compare_rows("tenant-a", rows)

    # Invariant: customer-visible row is untouched.
    assert rows[0] == before
    assert len(recorded) == 1
    div = recorded[0]
    assert div["canonical_source_class"] == "paid_search"
    assert div["legacy_source_class"] == "paid"
    assert div["diverged"] is True


@pytest.mark.asyncio
async def test_shadow_non_divergent_row_recorded_as_not_diverged() -> None:
    rows = [_touchpoint_row(source_class="organic_search", source_event_id="evt-org")]
    recorded = await shadow_compare_rows("tenant-a", rows)
    assert recorded[0]["diverged"] is False
    assert recorded[0]["legacy_source_class"] == "organic_search"


@pytest.mark.asyncio
async def test_shadow_is_idempotent_on_replay() -> None:
    repo = ShadowDivergenceRepository()
    args = dict(
        tenant_id="tenant-a",
        source_event_id="evt-1",
        touchpoint_id=None,
        legacy_source_class="direct",
        canonical_source_class="direct_unknown",
        diverged=True,
    )
    await repo.record(**args)
    await repo.record(**args)  # replay
    rate = await repo.divergence_rate("tenant-a")
    assert rate["total"] == 1
    assert rate["diverged"] == 1
    assert rate["rate"] == 1.0


@pytest.mark.asyncio
async def test_shadow_divergence_rate_is_tenant_scoped() -> None:
    await shadow_compare_rows(
        "tenant-a", [_touchpoint_row(source_class="paid_search", source_event_id="a1")]
    )
    await shadow_compare_rows(
        "tenant-b", [_touchpoint_row(tenant_id="tenant-b", source_class="organic_search", source_event_id="b1")]
    )
    repo = ShadowDivergenceRepository()
    a = await repo.divergence_rate("tenant-a")
    b = await repo.divergence_rate("tenant-b")
    assert a == {"total": 1, "diverged": 1, "rate": 1.0}
    assert b == {"total": 1, "diverged": 0, "rate": 0.0}


@pytest.mark.asyncio
async def test_shadow_emits_divergence_metric() -> None:
    key_true = "shadow_divergence_total{diverged=true}"
    start = metrics.get_counter("shadow_divergence_total", labels={"diverged": "true"})
    await shadow_compare_rows(
        "tenant-a", [_touchpoint_row(source_class="paid_social", source_event_id="m1")]
    )
    end = metrics.get_counter("shadow_divergence_total", labels={"diverged": "true"})
    assert end == start + 1


def test_metric_helpers_increment_named_counters() -> None:
    start = metrics.get_counter("classification_total", labels={"source_class": "organic_search"})
    traffic_metrics.record_classification("organic_search", "domain_verified")
    end = metrics.get_counter("classification_total", labels={"source_class": "organic_search"})
    assert end == start + 1

    d0 = metrics.get_counter("deferred_attribution_total", labels={"status": "resolved"})
    traffic_metrics.record_deferred_attribution("resolved")
    assert metrics.get_counter("deferred_attribution_total", labels={"status": "resolved"}) == d0 + 1


def test_traffic_metrics_summary_selects_only_family() -> None:
    traffic_metrics.record_direct_unknown()
    summary = traffic_metrics.traffic_metrics_summary()
    assert "traffic_intelligence" in summary
    keys = summary["traffic_intelligence"].keys()
    for key in keys:
        base = key.split("{", 1)[0]
        assert base in traffic_metrics.METRIC_NAMES
