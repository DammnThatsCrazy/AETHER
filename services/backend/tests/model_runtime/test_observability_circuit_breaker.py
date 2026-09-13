"""Tests for the model-runtime provider/tenant circuit breaker (ADR-008 D8).

Deterministic via the injectable ``now`` clock passed to ``allowed`` /
``record_failure`` / ``record_success`` — no sleeps, plain asserts only.
"""

from services.model_runtime.observability.circuit_breaker import (
    CircuitBreaker,
    CircuitRegistry,
    CircuitState,
)


def test_closed_allows():
    breaker = CircuitBreaker()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allowed() is True


def test_failures_open_at_threshold():
    breaker = CircuitBreaker(failure_threshold=3)
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.1)
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allowed() is True
    breaker.record_failure(now=0.2)  # reaches threshold -> opens
    assert breaker.state is CircuitState.OPEN
    assert breaker.allowed(now=0.5) is False  # still inside recovery window


def test_open_not_allowed():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=60.0)
    breaker.record_failure(now=10.0)
    breaker.record_failure(now=10.1)
    assert breaker.state is CircuitState.OPEN
    assert breaker.allowed(now=10.2) is False  # still within recovery window


def test_half_open_probe_after_recovery_timeout():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=60.0)
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.1)  # opens at 0.1
    assert breaker.state is CircuitState.OPEN
    # Before the timeout elapses the circuit stays closed to traffic.
    assert breaker.allowed(now=30.0) is False
    assert breaker.allowed(now=60.0) is False  # 59.9s elapsed -> still OPEN
    # First check after the timeout transitions to HALF_OPEN and grants a probe.
    assert breaker.allowed(now=60.2) is True  # 60.1s elapsed
    assert breaker.state is CircuitState.HALF_OPEN
    # Probe is in flight: a concurrent caller is denied.
    assert breaker.allowed(now=60.3) is False


def test_probe_failure_reopens():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=5.0)
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.1)
    assert breaker.state is CircuitState.OPEN
    assert breaker.allowed(now=10.0) is True  # -> HALF_OPEN, probe allowed
    breaker.record_failure(now=10.1)  # probe fails -> back to OPEN
    assert breaker.state is CircuitState.OPEN
    assert breaker.allowed(now=10.2) is False


def test_probe_success_closes():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=5.0)
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.1)
    assert breaker.allowed(now=10.0) is True  # -> HALF_OPEN, probe allowed
    breaker.record_success(now=10.2)  # probe succeeds -> CLOSED
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allowed() is True
    # Failure count was reset: one failure no longer trips the breaker.
    breaker.record_failure(now=10.3)
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allowed() is True


def test_half_open_probe_disabled_allows_multiple():
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_s=5.0,
        half_open_probe=False,
    )
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.1)
    assert breaker.allowed(now=10.0) is True  # -> HALF_OPEN
    assert breaker.state is CircuitState.HALF_OPEN
    assert breaker.allowed(now=10.1) is True  # second caller also allowed
    assert breaker.allowed(now=10.2) is True


def test_reset():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=60.0)
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.1)
    assert breaker.state is CircuitState.OPEN
    breaker.reset()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allowed() is True
    assert breaker.record_failure(now=1.0) is None


def test_registry_tenant_isolation():
    registry = CircuitRegistry(failure_threshold=2, recovery_timeout_s=60.0)
    tenant_a = registry.get("anthropic", "tenant-a")
    tenant_b = registry.get("anthropic", "tenant-b")
    assert tenant_a is not tenant_b
    # Same key is cached -> same breaker instance.
    assert registry.get("anthropic", "tenant-a") is tenant_a

    tenant_a.record_failure(now=0.0)
    tenant_a.record_failure(now=0.1)
    assert tenant_a.state is CircuitState.OPEN
    assert tenant_a.allowed(now=1.0) is False
    # Tenant B is untouched by tenant A's failures.
    assert tenant_b.state is CircuitState.CLOSED
    assert tenant_b.allowed() is True


def test_registry_global_and_tenant_are_distinct():
    registry = CircuitRegistry(failure_threshold=2, recovery_timeout_s=60.0)
    global_breaker = registry.get("openai")  # tenant_id None -> global
    tenant_breaker = registry.get("openai", "t1")
    assert global_breaker is not tenant_breaker
    global_breaker.record_failure(now=0.0)
    global_breaker.record_failure(now=0.1)
    assert global_breaker.state is CircuitState.OPEN
    assert tenant_breaker.state is CircuitState.CLOSED
    assert tenant_breaker.allowed() is True


def test_registry_all_keys_deterministic():
    registry = CircuitRegistry()
    registry.get("openai")
    registry.get("openai", "t1")
    registry.get("anthropic")
    assert set(registry.all().keys()) == {"openai", "openai:t1", "anthropic"}
    # Deterministic keying is stable across lookups.
    assert registry.get("openai", "t1") is registry.all()["openai:t1"]


def test_registry_is_available_fail_closed():
    registry = CircuitRegistry(failure_threshold=2, recovery_timeout_s=60.0)
    # No breaker yet -> assumed available.
    assert registry.is_available("openai") is True
    breaker = registry.get("openai")
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.1)
    assert breaker.state is CircuitState.OPEN
    assert registry.is_available("openai") is False
    breaker.reset()
    assert registry.is_available("openai") is True
