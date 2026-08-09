"""Health/readiness probes for the model runtime (ADR-008 D8).

A provider adapter is healthy when configured and able to serve; unhealthy or
misconfigured providers must never report healthy. Probes never call
``complete`` and never touch the network.
"""

from __future__ import annotations

from services.model_runtime.observability.health import (
    ProviderHealth,
    ProviderHealthCheck,
    RuntimeHealth,
    RuntimeHealthProbe,
    describe,
)

_SECRET_MARKER = "sk-super-secret-12345"


class FakeProvider:
    """Minimal AsyncModelProvider-compatible stand-in for health probes."""

    def __init__(self, name: str, configured: bool) -> None:
        self.provider_name = name
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    async def complete(self, request):  # pragma: no cover - never called
        raise AssertionError("health probe must not call complete()")


class _ProbeTrackingProvider(FakeProvider):
    """Records whether ``complete`` is ever invoked during a probe."""

    def __init__(self, name: str, configured: bool) -> None:
        super().__init__(name, configured)
        self.complete_calls = 0

    async def complete(self, request):  # pragma: no cover - never called
        self.complete_calls += 1
        raise AssertionError("health probe must not call complete()")


class _SecretHoldingProvider(FakeProvider):
    """Holds a fake credential internally; health output must never leak it."""

    def __init__(self, name: str, configured: bool) -> None:
        super().__init__(name, configured)
        self.api_key = _SECRET_MARKER


def test_provider_health_fields():
    ph = ProviderHealth(
        provider="anthropic",
        configured=True,
        healthy=True,
        reason="configured",
    )
    assert ph.provider == "anthropic"
    assert ph.configured is True
    assert ph.healthy is True
    assert ph.reason == "configured"


def test_provider_health_is_frozen():
    ph = ProviderHealth(
        provider="anthropic",
        configured=True,
        healthy=True,
        reason="configured",
    )
    raised = False
    try:
        ph.configured = False
    except Exception:
        raised = True
    assert raised


def test_provider_health_reasons():
    healths = ProviderHealthCheck(
        {"ok": FakeProvider("ok", True), "bad": FakeProvider("bad", False)}
    ).check()
    by_name = {h.provider: h for h in healths}
    assert by_name["ok"].reason == "configured"
    assert by_name["ok"].configured is True
    assert by_name["ok"].healthy is True
    assert by_name["bad"].reason == "not configured"
    assert by_name["bad"].configured is False
    assert by_name["bad"].healthy is False


def test_all_configured_reports_ok():
    providers = {
        "anthropic": FakeProvider("anthropic", True),
        "openai": FakeProvider("openai", True),
    }
    health = RuntimeHealthProbe(ProviderHealthCheck(providers)).status()
    assert health.status == "ok"
    assert health.providers == (
        ProviderHealth(provider="anthropic", configured=True, healthy=True, reason="configured"),
        ProviderHealth(provider="openai", configured=True, healthy=True, reason="configured"),
    )
    assert health.checks == {"anthropic": True, "openai": True}


def test_one_misconfigured_reports_degraded():
    providers = {
        "anthropic": FakeProvider("anthropic", True),
        "openai": FakeProvider("openai", False),
    }
    health = RuntimeHealthProbe(ProviderHealthCheck(providers)).status()
    assert health.status == "degraded"
    healthy = [p for p in health.providers if p.healthy]
    unhealthy = [p for p in health.providers if not p.healthy]
    assert len(healthy) == 1
    assert len(unhealthy) == 1
    assert unhealthy[0].provider == "openai"
    assert health.checks == {"anthropic": True, "openai": False}


def test_all_misconfigured_reports_unhealthy():
    providers = {
        "anthropic": FakeProvider("anthropic", False),
        "openai": FakeProvider("openai", False),
    }
    health = RuntimeHealthProbe(ProviderHealthCheck(providers)).status()
    assert health.status == "unhealthy"
    assert not any(p.healthy for p in health.providers)
    assert health.checks == {"anthropic": False, "openai": False}


def test_no_providers_reports_unhealthy():
    health = RuntimeHealthProbe(ProviderHealthCheck({})).status()
    assert health.status == "unhealthy"
    assert health.providers == ()


def test_runtime_health_fields_and_extra_checks():
    providers = {
        "anthropic": FakeProvider("anthropic", True),
        "openai": FakeProvider("openai", True),
    }
    probe = RuntimeHealthProbe(
        ProviderHealthCheck(providers),
        extra_checks={"runtime.config.loaded": True, "runtime.registry": False},
    )
    health = probe.status()
    assert isinstance(health, RuntimeHealth)
    assert health.status == "ok"
    assert len(health.providers) == 2
    # extra_checks are merged into checks without clobbering provider entries.
    assert health.checks == {
        "anthropic": True,
        "openai": True,
        "runtime.config.loaded": True,
        "runtime.registry": False,
    }


def test_describe_contains_status():
    probe = RuntimeHealthProbe(ProviderHealthCheck({"anthropic": FakeProvider("anthropic", True)}))
    text = describe(probe.status())
    assert "ok" in text
    assert "1/1" in text
    text = describe(
        RuntimeHealthProbe(
            ProviderHealthCheck(
                {
                    "anthropic": FakeProvider("anthropic", True),
                    "openai": FakeProvider("openai", False),
                }
            )
        ).status()
    )
    assert "degraded" in text
    assert "openai" in text


def test_no_secrets_in_any_health_string():
    providers = {
        "good": _SecretHoldingProvider("good", True),
        "bad": _SecretHoldingProvider("bad", False),
    }
    health = RuntimeHealthProbe(ProviderHealthCheck(providers)).status()
    healths = ProviderHealthCheck(providers).check()
    rendered = "\n".join(
        [
            str(ProviderHealth(provider="p", configured=True, healthy=True, reason="configured")),
            str(healths[0]),
            str(healths[1]),
            str(health),
            describe(health),
        ]
    )
    assert _SECRET_MARKER not in rendered
    assert "configured" in rendered
    assert "not configured" in rendered


def test_health_probe_never_calls_complete():
    providers = {
        "anthropic": _ProbeTrackingProvider("anthropic", True),
        "openai": _ProbeTrackingProvider("openai", False),
    }
    check = ProviderHealthCheck(providers)
    health = RuntimeHealthProbe(check).status()
    assert health.status == "degraded"
    assert providers["anthropic"].complete_calls == 0
    assert providers["openai"].complete_calls == 0
