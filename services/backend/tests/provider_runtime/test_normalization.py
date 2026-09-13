"""Tests for the normalization engine (against the Team A contract)."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from shared.integration_contracts.events import make_aether_event, make_raw_record
from shared.integration_contracts.normalization import (
    EventNormalizer,
    NormalizationResult,
)

from services.provider_runtime.normalization import NormalizationEngine


def _record(record_id: str = "ord_1") -> Any:
    return make_raw_record(
        provider_identity="shopify.orders.catalog",
        provider_record_id=record_id,
        payload={"order_id": record_id},
        tenant_id="tenant-1",
    )


def _event(event_id: str = "evt_1") -> Any:
    return make_aether_event(
        provider_identity="shopify.orders.catalog",
        event_type="commerce.order.created",
        event_family="commerce",
        tenant_id="tenant-1",
        source_record_id="raw_1",
        data={"order_id": event_id},
    )


class _FakeNormalizer:
    """Protocol-conforming normalizer double (normalize is sync per the seam)."""

    def __init__(
        self,
        events=None,
        skipped: int = 0,
        dropped: Optional[list[str]] = None,
        version: Optional[str] = None,
    ) -> None:
        self._events = list(events or [])
        self._skipped = skipped
        self._dropped = list(dropped or [])
        self._version = version

    def normalize(self, record) -> NormalizationResult:
        return NormalizationResult(
            events=list(self._events),
            skipped=self._skipped,
            dropped=list(self._dropped),
            normalizer_version=self._version or "1",
        )


def _plugin(normalizer: Optional[_FakeNormalizer] = None):
    class _P:
        def __init__(self, n) -> None:
            self._n = n

        def normalizer(self):
            return self._n

    return _P(normalizer)


def test_normalizer_contract_is_sync():
    # EventNormalizer.normalize is synchronous per the Team A protocol.
    assert not hasattr(EventNormalizer, "async_normalize")


def test_normalizer_missing_drops_every_record_with_reason():
    class _NoNormalizerPlugin:
        def normalizer(self):
            return None

    engine = NormalizationEngine(_NoNormalizerPlugin())
    result = engine.run([_record("ord_1"), _record("ord_2")])
    assert isinstance(result, NormalizationResult)
    assert result.events == []
    assert result.skipped == 0
    assert result.dropped == ["ord_1:no_normalizer", "ord_2:no_normalizer"]
    assert result.normalizer_version == "1"


def test_normalizer_missing_attribute_drops_every_record():
    class _BarePlugin:  # exposes no normalizer accessor at all
        pass

    engine = NormalizationEngine(_BarePlugin())
    result = engine.run([_record("ord_1")])
    assert result.dropped == ["ord_1:no_normalizer"]


def test_run_aggregates_normalized_events():
    ev1 = _event("evt_1")

    engine = NormalizationEngine(_plugin(_FakeNormalizer(events=[ev1], version="v3")))
    result = engine.run([_record("ord_1"), _record("ord_2")])
    assert result.events == [ev1, ev1]
    assert result.skipped == 0
    assert result.dropped == []


def test_run_sums_skipped_counts():
    engine = NormalizationEngine(_plugin(_FakeNormalizer(skipped=2, version="v2")))
    result = engine.run([_record("ord_1"), _record("ord_2")])
    assert result.skipped == 4  # 2 per record, aggregated


def test_run_aggregates_dropped_reasons():
    engine = NormalizationEngine(
        _plugin(_FakeNormalizer(dropped=["ord_1:invalid_payload"], version="v2"))
    )
    result = engine.run([_record("ord_1")])
    assert result.dropped == ["ord_1:invalid_payload"]


def test_normalizer_version_taken_from_first_non_default():
    engine = NormalizationEngine(_plugin(_FakeNormalizer(events=[_event()], version="v9")))
    result = engine.run([_record("ord_1")])
    assert result.normalizer_version == "v9"


def test_normalizer_version_defaults_to_one():
    engine = NormalizationEngine(_plugin(_FakeNormalizer(skipped=0)))
    result = engine.run([_record("ord_1")])
    assert result.normalizer_version == "1"


def test_run_on_empty_records_returns_empty_result():
    engine = NormalizationEngine(_plugin(_FakeNormalizer(events=[_event()], version="v2")))
    result = engine.run([])
    assert result.events == []
    assert result.skipped == 0
    assert result.dropped == []
    assert result.normalizer_version == "1"
