"""Adapter result: bridge mappers and the not_supported constructor."""

from __future__ import annotations

from services.integrations.connectors.base import (
    ConnectionTestResult,
    NormalizedEvent,
    SyncResult,
)
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    from_connection_test,
    from_provider_result,
    from_sync_result,
)
from shared.providers.base import ProviderResult


def test_not_supported_sets_status() -> None:
    r = AdapterResult.not_supported("get_orders")
    assert r.success is False
    assert r.status is AdapterStatus.NOT_SUPPORTED
    assert r.retryable is False
    assert r.error_code == "not_supported:get_orders"


def test_ok_constructor() -> None:
    r = AdapterResult.ok({"x": 1}, latency_ms=12.5, provider_request_id="req-1")
    assert r.success is True
    assert r.status is AdapterStatus.OK
    assert r.data == {"x": 1}
    assert r.latency_ms == 12.5
    assert r.provider_request_id == "req-1"


def test_from_provider_result_success() -> None:
    pr = ProviderResult(
        success=True, data={"price": 100}, provider_name="coingecko", latency_ms=42.0
    )
    r = from_provider_result(pr)
    assert r.success is True
    assert r.status is AdapterStatus.OK
    assert r.data == {"price": 100}
    assert r.latency_ms == 42.0
    assert r.provider_request_id == "coingecko"


def test_from_provider_result_failure_is_permanent_nonretryable() -> None:
    pr = ProviderResult(success=False, error="boom", provider_name="dune", latency_ms=5.0)
    r = from_provider_result(pr)
    assert r.success is False
    assert r.status is AdapterStatus.PERMANENT_ERROR
    assert r.retryable is False
    assert r.error_code == "boom"
    assert r.latency_ms == 5.0


def test_from_connection_test_ok() -> None:
    t = ConnectionTestResult(
        connector_type="shopify", ok=True, status="ready", detail="credential resolved"
    )
    r = from_connection_test(t)
    assert r.success is True
    assert r.status is AdapterStatus.OK
    assert r.data == {"detail": "credential resolved", "status": "ready"}


def test_from_connection_test_failures_map_by_status() -> None:
    not_configured = from_connection_test(
        ConnectionTestResult(connector_type="stripe", ok=False, status="not_configured")
    )
    assert not_configured.success is False
    assert not_configured.status is AdapterStatus.UNAUTHORIZED
    assert not_configured.error_code == "not_configured"

    disabled = from_connection_test(
        ConnectionTestResult(connector_type="stripe", ok=False, status="disabled")
    )
    assert disabled.status is AdapterStatus.PERMANENT_ERROR
    assert disabled.retryable is False

    errored = from_connection_test(
        ConnectionTestResult(connector_type="stripe", ok=False, status="error")
    )
    assert errored.status is AdapterStatus.RETRYABLE_ERROR
    assert errored.retryable is True


def test_from_sync_result_healthy_and_failed() -> None:
    healthy = from_sync_result(
        SyncResult(
            connector_type="shopify",
            status="healthy",
            events_ingested=7,
            events=[NormalizedEvent(event_type="order.created", source="shopify")],
        )
    )
    assert healthy.success is True
    assert healthy.status is AdapterStatus.OK
    assert healthy.data["events_ingested"] == 7
    assert healthy.data["sync_status"] == "healthy"

    failed = from_sync_result(
        SyncResult(connector_type="shopify", status="failed", events_ingested=0)
    )
    assert failed.success is False
    assert failed.status is AdapterStatus.RETRYABLE_ERROR
    assert failed.retryable is True
    assert failed.error_code == "failed"

    disabled = from_sync_result(
        SyncResult(connector_type="shopify", status="disabled")
    )
    assert disabled.status is AdapterStatus.PERMANENT_ERROR
    assert disabled.retryable is False
