"""Dispatcher-level wiring for traffic metrics + shadow compare (spec §16/§2)."""

from __future__ import annotations

import pytest

from services.silver import dispatcher as dispatcher_module
from services.silver.dispatcher import (
    _emit_classification_metrics,
    _shadow_compare_touchpoints,
)
from services.traffic import shadow
from shared.logger.logger import metrics


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    shadow._reset_local_divergences()
    yield
    shadow._reset_local_divergences()


def _row(**over):
    row = {
        "tenant_id": "tenant-a",
        "source_event_id": "evt-1",
        "source_class": "direct_unknown",
        "proof_level": "none",
        "attribution_eligible": True,
    }
    row.update(over)
    return row


def test_emit_classification_metrics_counts_dimensions() -> None:
    before = metrics.get_counter("direct_unknown_total")
    _emit_classification_metrics([_row(), _row(source_class="paid_search", source_event_id="e2")])
    assert metrics.get_counter("direct_unknown_total") == before + 1


def test_emit_classification_metrics_counts_machine_exclusion() -> None:
    before = metrics.get_counter("machine_excluded_total")
    _emit_classification_metrics([
        _row(source_class="machine_referral", attribution_eligible=False, actor_type="machine")
    ])
    assert metrics.get_counter("machine_excluded_total") == before + 1


@pytest.mark.asyncio
async def test_shadow_compare_gated_off_by_default(monkeypatch) -> None:
    # Default flags: shadow disabled -> no divergence rows written.
    monkeypatch.delenv("TRAFFIC_SHADOW_CLASSIFICATION_ENABLED", raising=False)
    rows = [_row(source_class="paid_search")]
    await _shadow_compare_touchpoints("tenant-a", rows)
    repo = shadow.ShadowDivergenceRepository()
    assert (await repo.divergence_rate("tenant-a"))["total"] == 0


@pytest.mark.asyncio
async def test_shadow_compare_records_without_mutating_rows(monkeypatch) -> None:
    monkeypatch.setenv("TRAFFIC_SHADOW_CLASSIFICATION_ENABLED", "true")
    monkeypatch.delenv("TRAFFIC_CANARY_TENANTS", raising=False)
    rows = [_row(source_class="paid_search")]
    snapshot_before = [dict(r) for r in rows]

    await _shadow_compare_touchpoints("tenant-a", rows)

    # Invariant: dispatcher copies rows -> customer-visible rows untouched.
    assert rows == snapshot_before
    repo = shadow.ShadowDivergenceRepository()
    rate = await repo.divergence_rate("tenant-a")
    assert rate["total"] == 1
    assert rate["diverged"] == 1
