"""Tests for the bounded exponential backoff / jitter coordinator."""

from __future__ import annotations

from services.provider_runtime.retry import RetryCoordinator
from shared.integration_contracts.results import AdapterStatus, RateLimitInfo


def _coordinator() -> RetryCoordinator:
    return RetryCoordinator()


def test_should_retry_retryable_statuses():
    rc = _coordinator()
    assert rc.should_retry(AdapterStatus.RETRYABLE_ERROR, attempt=0) is True
    assert rc.should_retry(AdapterStatus.RATE_LIMITED, attempt=2) is True


def test_should_retry_never_retries_terminal_statuses():
    rc = _coordinator()
    for status in (
        AdapterStatus.OK,
        AdapterStatus.UNAUTHORIZED,
        AdapterStatus.PERMANENT_ERROR,
        AdapterStatus.NOT_SUPPORTED,
    ):
        assert rc.should_retry(status, attempt=0) is False, status


def test_should_retry_respects_attempt_cap():
    rc = _coordinator()
    assert rc.MAX_RETRIES == 3
    assert rc.should_retry(AdapterStatus.RATE_LIMITED, attempt=2) is True
    assert rc.should_retry(AdapterStatus.RATE_LIMITED, attempt=3) is False
    assert rc.should_retry(AdapterStatus.RETRYABLE_ERROR, attempt=99) is False


def test_delay_exponential_backoff():
    rc = _coordinator()
    assert rc.BASE_DELAY_MS == 250
    assert rc.delay_ms(0) == 250.0
    assert rc.delay_ms(1) == 500.0
    assert rc.delay_ms(2) == 1000.0
    assert rc.delay_ms(3) == 2000.0


def test_delay_capped_at_max_delay():
    rc = _coordinator()
    assert rc.MAX_DELAY_MS == 8_000
    assert rc.delay_ms(10) == 8_000.0  # 250 * 2**10 would exceed the cap
    assert rc.delay_ms(6) == 8_000.0


def test_delay_honors_provider_retry_after():
    rc = _coordinator()
    info = RateLimitInfo(retry_after_ms=1500)
    assert rc.delay_ms(0, info) == 1500.0
    assert rc.delay_ms(4, info) == 1500.0  # overrides exponential backoff


def test_delay_ignores_nonpositive_retry_after():
    rc = _coordinator()
    assert rc.delay_ms(2, RateLimitInfo(retry_after_ms=0)) == 1000.0
    assert rc.delay_ms(2, RateLimitInfo(retry_after_ms=-5)) == 1000.0


def test_delay_jitter_is_deterministic_via_param():
    """Jitter is an explicit parameter so tests stay exact (documented choice)."""
    rc = _coordinator()
    assert rc.delay_ms(2, jitter=10.0) == 1010.0
    assert rc.delay_ms(2, jitter=0.0) == 1000.0
