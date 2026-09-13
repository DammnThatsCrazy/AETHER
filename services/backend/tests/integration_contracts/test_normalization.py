"""Normalization contract: deterministic, network-free, drops are never silent."""

from __future__ import annotations

import pytest

from shared.integration_contracts.events import AetherEvent, RawProviderRecord
from shared.integration_contracts.normalization import EventNormalizer, NormalizationResult


def test_normalization_result_defaults() -> None:
    r = NormalizationResult()
    assert r.events == []
    assert r.skipped == 0
    assert r.dropped == []
    assert r.normalizer_version == "1"


def test_normalization_result_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        NormalizationResult(unexpected_field=True)  # type: ignore[call-arg]


# ── a deterministic EventNormalizer ─────────────────────────────────────────


class _OrderNormalizer:
    """Converts order records into a commerce.order.created event, deterministically."""

    def normalize(self, raw: RawProviderRecord) -> NormalizationResult:
        if raw.provider_record_type != "order":
            return NormalizationResult(
                dropped=[f"{raw.record_id}:{raw.provider_record_type}"]
            )
        # event_id is derived deterministically from the raw record so that
        # re-normalizing the same record yields byte-identical output (replay).
        return NormalizationResult(
            events=[
                AetherEvent(
                    event_id=raw.idempotency_key,
                    event_type="commerce.order.created",
                    event_family="commerce",
                    tenant_id=raw.tenant_id,
                    provider=raw.provider_identity.split(".")[0],
                    provider_identity=raw.provider_identity,
                    source_record_id=raw.record_id,
                    occurred_at=raw.provider_occurred_at or "",
                    observed_at=raw.observed_at,
                    account_id=raw.account_id,
                    data=dict(raw.payload),
                    context={"connection_id": raw.connection_id},
                )
            ],
            skipped=0,
        )


def _order_record(**overrides: object) -> RawProviderRecord:
    base: dict[str, object] = dict(
        provider_identity="shopify.admin.orders_read",
        tenant_id="t1",
        connection_id="c1",
        account_id="a1",
        provider_record_type="order",
        provider_record_id="p-1",
        provider_occurred_at="2026-01-01T00:00:00+00:00",
        observed_at="2026-01-01T00:00:01+00:00",
        payload={"order_id": "p-1", "total": 12.5},
    )
    base.update(overrides)
    return RawProviderRecord(**base)  # type: ignore[arg-type]


def test_normalize_produces_event() -> None:
    raw = _order_record()
    result = _OrderNormalizer().normalize(raw)
    assert len(result.events) == 1
    e = result.events[0]
    assert e.event_type == "commerce.order.created"
    assert e.provider_identity == "shopify.admin.orders_read"
    assert e.source_record_id == raw.record_id
    assert e.tenant_id == "t1"


def test_normalize_is_deterministic() -> None:
    raw = _order_record()
    n = _OrderNormalizer()
    first = n.normalize(raw)
    second = n.normalize(raw)
    # Same input -> byte-identical output (no time/randomness inside normalize).
    assert first.model_dump() == second.model_dump()
    assert first.events[0].event_id == second.events[0].event_id


def test_normalize_never_silently_drops() -> None:
    raw = _order_record(provider_record_type="refund", provider_record_id="p-2")
    result = _OrderNormalizer().normalize(raw)
    assert result.events == []
    assert result.dropped == [f"{raw.record_id}:refund"]


def test_normalizer_surfaces_skipped_count() -> None:
    class _Skipper:
        def normalize(self, raw: RawProviderRecord) -> NormalizationResult:
            return NormalizationResult(skipped=1)

    assert _Skipper().normalize(_order_record()).skipped == 1


def test_normalizer_protocol_is_structural() -> None:
    # EventNormalizer is a plain Protocol; conformance is by method shape.
    assert callable(getattr(_OrderNormalizer(), "normalize"))
    assert _OrderNormalizer().normalize(_order_record()).__class__ is NormalizationResult
