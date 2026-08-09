"""Provider-neutral health/readiness probes for the model runtime (ADR-008 D8).

Health and readiness endpoints for the runtime and each provider adapter. A
provider adapter is healthy when it is configured and able to serve requests;
an unhealthy or misconfigured adapter must NEVER report healthy.

The probes are deliberately liveness-light: they never invoke ``complete`` and
never block on the network. For the local ``DeterministicModelProvider`` a real
call would be safe, but the same probe is used uniformly for network-backed
providers, so it stays configured-based only.

Security: these models and probes hold no credentials, API keys, request
bodies, or tenant-restricted content — provider names only. ``describe``
renders an audit-safe one-liner (status + provider counts) for logs and
dashboards.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from services.model_runtime.provider import AsyncModelProvider


class ProviderHealth(BaseModel, frozen=True):
    """Health snapshot for a single provider adapter."""

    provider: str  # provider name only — never credentials or config values
    configured: bool
    healthy: bool
    reason: str  # controlled audit string, e.g. "configured" | "not configured"


class RuntimeHealth(BaseModel, frozen=True):
    """Aggregate runtime health snapshot."""

    status: Literal["ok", "degraded", "unhealthy"]
    providers: tuple[ProviderHealth, ...]
    checks: dict[str, bool]  # per-provider booleans merged with extra checks


class ProviderHealthCheck:
    """Liveness probe across provider adapters.

    A provider is healthy exactly when it is configured. ``check`` returns one
    :class:`ProviderHealth` per adapter in mapping iteration order. It never
    calls ``complete`` and never touches the network, so it is safe to run on
    every request or interval regardless of provider kind.
    """

    def __init__(self, providers: Mapping[str, AsyncModelProvider]) -> None:
        self._providers = providers

    def check(self) -> tuple[ProviderHealth, ...]:
        return tuple(self._check_one(name, impl) for name, impl in self._providers.items())

    def _check_one(self, name: str, impl: AsyncModelProvider) -> ProviderHealth:
        configured = impl.is_configured()
        return ProviderHealth(
            provider=getattr(impl, "provider_name", name),
            configured=configured,
            healthy=configured,
            reason="configured" if configured else "not configured",
        )


class RuntimeHealthProbe:
    """Aggregate runtime status probe over provider health plus extra checks.

    Status resolution: ``ok`` when every provider is healthy; ``degraded`` when
    at least one provider is healthy but at least one is not; ``unhealthy``
    when zero providers are healthy (including an empty provider set).
    """

    def __init__(
        self,
        health_check: ProviderHealthCheck,
        *,
        extra_checks: Mapping[str, bool] | None = None,
    ) -> None:
        self._health_check = health_check
        self._extra_checks = dict(extra_checks) if extra_checks else {}

    def status(self) -> RuntimeHealth:
        provider_healths = self._health_check.check()
        healthy_count = sum(1 for p in provider_healths if p.healthy)

        if not provider_healths or healthy_count == 0:
            status: Literal["ok", "degraded", "unhealthy"] = "unhealthy"
        elif healthy_count == len(provider_healths):
            status = "ok"
        else:
            status = "degraded"

        checks: dict[str, bool] = {p.provider: p.healthy for p in provider_healths}
        checks.update(self._extra_checks)

        return RuntimeHealth(
            status=status,
            providers=provider_healths,
            checks=checks,
        )


def describe(health: RuntimeHealth) -> str:
    """Audit-safe one-line summary: status + provider counts + names only.

    Contains no credentials, config values, request bodies, or reasons beyond
    the controlled health data — safe for logs and dashboards.
    """
    total = len(health.providers)
    healthy_count = sum(1 for p in health.providers if p.healthy)
    summary = f"model-runtime status={health.status} providers={healthy_count}/{total} healthy"
    unhealthy = sorted(p.provider for p in health.providers if not p.healthy)
    if unhealthy:
        summary += f" unhealthy=[{', '.join(unhealthy)}]"
    return summary
