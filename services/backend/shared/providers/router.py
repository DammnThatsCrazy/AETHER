"""
Aether Shared -- Adaptive Router

Health-aware failover routing across provider instances.
Composes with the existing ErrorRegistry circuit breakers so provider
failures automatically surface in ``/v1/diagnostics/circuit-breakers``.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from shared.diagnostics.error_registry import error_registry
from shared.logger.logger import get_logger, metrics
from shared.providers.base import Provider, ProviderResult, ProviderStatus
from shared.providers.categories import ProviderCategory
from shared.providers.meter import UsageMeter
from shared.providers.registry import ProviderRegistry

logger = get_logger("aether.providers.router")


class AdaptiveRouter:
    """
    Routes provider calls through the priority chain:

        1. Tenant BYOK key  →  (not found or circuit OPEN)
        2. System default    →  (circuit OPEN)
        3. Fallback(s)       →  (all exhausted)
        4. ServiceUnavailableError

    Each call is metered and circuit-breaker states are managed via
    ``ErrorRegistry`` so they appear in the diagnostics dashboard.
    """

    BREAKER_PREFIX = "provider_gateway"

    def __init__(
        self,
        registry: ProviderRegistry,
        meter: UsageMeter,
        max_retries: int = 2,
    ) -> None:
        self._registry = registry
        self._meter = meter
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(
        self,
        category: ProviderCategory,
        method: str,
        params: dict[str, Any],
        tenant_id: Optional[str] = None,
        preferred_provider: Optional[str] = None,
    ) -> ProviderResult:
        """
        Route a call to the best available provider for *category*.

        Returns the first successful ``ProviderResult``.  If every provider
        fails or has an open circuit, returns a failure result.
        """
        providers = await self._registry.get_all_providers(category, tenant_id)

        if preferred_provider:
            # Move preferred to front, keeping remaining order
            providers.sort(key=lambda p: 0 if p.name == preferred_provider else 1)

        if not providers:
            metrics.increment("provider_route_exhausted", labels={
                "category": category.value,
            })
            return ProviderResult(
                success=False,
                error=f"No providers available for category '{category.value}'",
                provider_name="none",
            )

        last_error: Optional[str] = None

        for provider in providers:
            breaker_key = self._breaker_key(category, provider.name)

            # Skip providers with open circuit breakers
            if error_registry.is_circuit_open(self.BREAKER_PREFIX, breaker_key):
                logger.debug(
                    f"Skipping provider {provider.name} — circuit breaker open"
                )
                continue

            # Check provider health
            health = await provider.health_check()
            if health == ProviderStatus.UNAVAILABLE:
                continue

            # Attempt the call (with retries)
            result = await self._attempt(
                provider, category, method, params, tenant_id or "system",
            )

            if result.success:
                error_registry.record_success(self.BREAKER_PREFIX, breaker_key)
                metrics.increment("provider_route_success", labels={
                    "category": category.value,
                    "provider": provider.name,
                })

                # Flag failover if this wasn't the first provider tried
                if providers.index(provider) > 0:
                    result.failover_used = True

                return result

            # Record failure in circuit breaker
            last_error = result.error
            try:
                raise RuntimeError(result.error or "provider call failed")
            except RuntimeError as exc:
                error_registry.register(
                    error=exc,
                    service=self.BREAKER_PREFIX,
                    operation=breaker_key,
                    context={
                        "category": category.value,
                        "provider": provider.name,
                        "method": method,
                    },
                )

            metrics.increment("provider_route_failure", labels={
                "category": category.value,
                "provider": provider.name,
            })

        # All providers exhausted
        metrics.increment("provider_route_exhausted", labels={
            "category": category.value,
        })
        logger.error(
            f"All providers exhausted for {category.value}: {last_error}"
        )
        return ProviderResult(
            success=False,
            error=f"All providers exhausted for '{category.value}': {last_error}",
            provider_name="none",
        )

    async def health(self) -> dict:
        """Provider health including circuit breaker state per provider."""
        registry_health = await self._registry.health_check()
        categories = self._registry.get_categories()

        result: dict[str, Any] = {}
        for cat_name, provider_names in categories.items():
            cat_info: dict[str, Any] = {}
            for name in provider_names:
                breaker_key = self._breaker_key_raw(cat_name, name)
                cb_state = "closed"
                if error_registry.is_circuit_open(self.BREAKER_PREFIX, breaker_key):
                    cb_state = "open"
                elif hasattr(error_registry, "_circuit_breakers"):
                    full_key = f"{self.BREAKER_PREFIX}.{breaker_key}"
                    cb = error_registry._circuit_breakers.get(full_key)
                    if cb and cb.state == "half_open":
                        cb_state = "half_open"

                provider_status = (
                    registry_health.get(cat_name, {}).get(name, "unknown")
                )
                cat_info[name] = {
                    "status": provider_status,
                    "circuit_breaker": cb_state,
                }
            result[cat_name] = cat_info

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _attempt(
        self,
        provider: Provider,
        category: ProviderCategory,
        method: str,
        params: dict[str, Any],
        tenant_id: str,
    ) -> ProviderResult:
        """Execute with retries and metering."""
        last_result: Optional[ProviderResult] = None

        for attempt in range(1, self._max_retries + 1):
            start = time.perf_counter()
            result = await provider.execute(method, params)
            elapsed_ms = (time.perf_counter() - start) * 1000
            result.latency_ms = elapsed_ms

            await self._meter.record(
                tenant_id=tenant_id,
                category=category.value,
                provider_name=provider.name,
                method=method,
                latency_ms=elapsed_ms,
                success=result.success,
            )

            if result.success:
                return result

            last_result = result
            logger.warning(
                f"Provider {provider.name} attempt {attempt}/{self._max_retries} "
                f"failed: {result.error}"
            )

        return last_result or ProviderResult(
            success=False,
            error="No attempts made",
            provider_name=provider.name,
        )

    @staticmethod
    def _breaker_key(category: ProviderCategory, provider_name: str) -> str:
        return f"{category.value}.{provider_name}"

    @staticmethod
    def _breaker_key_raw(category_value: str, provider_name: str) -> str:
        return f"{category_value}.{provider_name}"
