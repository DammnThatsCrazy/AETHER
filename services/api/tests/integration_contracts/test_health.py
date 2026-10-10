"""Provider health report contract."""

from __future__ import annotations

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.health import ProviderHealthReport
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.manifest import ManifestReadiness
from shared.integration_contracts.results import RateLimitInfo


def test_health_report_defaults() -> None:
    r = ProviderHealthReport(
        provider_identity="shopify.admin.orders_read",
        connection_id="c1",
        state=ConnectionState.CONNECTED,
        readiness=ManifestReadiness(state=CredentialReadiness.SANDBOX_VALIDATED, level=4),
    )
    assert r.last_sync_at is None
    assert r.last_webhook_at is None
    assert r.rate_limit is None
    assert r.error_count == 0
    assert r.last_error is None
    assert r.schema_version == "1"


def test_health_report_carries_rate_limit_and_errors() -> None:
    r = ProviderHealthReport(
        provider_identity="shopify.admin.orders_read",
        connection_id="c1",
        state=ConnectionState.RATE_LIMITED,
        readiness=ManifestReadiness(state=CredentialReadiness.PARTNER_LIVE, level=5),
        last_sync_at="2026-01-01T00:00:00+00:00",
        rate_limit=RateLimitInfo(limit=100, remaining=0, retry_after_ms=5000.0),
        error_count=3,
        last_error="429 too many requests",
    )
    assert r.state == ConnectionState.RATE_LIMITED
    assert r.rate_limit is not None
    assert r.rate_limit.remaining == 0
    assert r.error_count == 3


def test_health_report_requires_state_and_readiness() -> None:
    with pytest.raises(Exception):
        ProviderHealthReport(provider_identity="x", connection_id="c1")  # type: ignore[call-arg]


def test_health_report_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        ProviderHealthReport(  # type: ignore[call-arg]
            provider_identity="x",
            connection_id="c1",
            state=ConnectionState.CONNECTED,
            readiness=ManifestReadiness(state=CredentialReadiness.SANDBOX_VALIDATED, level=4),
            unexpected_field=True,
        )
