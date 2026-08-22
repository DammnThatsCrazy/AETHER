"""Provider-neutral model runtime service.

Owns a provider registry, resolves a provider for a request, invokes it
through the AsyncModelProvider contract, enforces an optional per-tenant
token budget, and records metrics. This is the orchestration seam Noesis
(Commit 3) and later adapters (Commit 4+) plug into. No provider SDK,
credentials backend, or noesis package may be imported here.
"""

from __future__ import annotations

import time
import typing
from collections.abc import Mapping

from services.model_runtime.models import (
    ModelBudgetExceeded,
    ModelNotConfigured,
    ModelRequest,
    ModelResponse,
)
from services.model_runtime.provider import AsyncModelProvider
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.model_runtime")


class TokenBudget(typing.Protocol):
    """Per-tenant token budget hook (same shape as NoesisTokenBudget)."""

    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        """Reserve estimated_tokens atomically; True if within budget."""

    async def release(self, tenant_id: str, tokens: int) -> None:
        """Return previously reserved tokens (failure or over-estimate)."""

    async def charge(self, tenant_id: str, tokens: int) -> None:
        """Record spend beyond the upfront reservation."""


class ModelRuntimeService:
    """Provider registry, selection, budget enforcement, and metrics."""

    def __init__(
        self,
        providers: Mapping[str, AsyncModelProvider] | None = None,
        *,
        default_provider: str = "deterministic",
        budget: TokenBudget | None = None,
        estimated_request_tokens: int = 800,
    ) -> None:
        """Build the runtime; default_provider must exist in providers.

        providers: {provider_name: instance}. budget None = unlimited.
        """
        self._providers: dict[str, AsyncModelProvider] = dict(providers or {})
        self._default = default_provider
        self._budget = budget
        self._estimated_request_tokens = estimated_request_tokens

    def register(self, provider: AsyncModelProvider) -> None:
        """Add or replace a provider by its provider_name."""
        self._providers[provider.provider_name] = provider

    def provider_names(self) -> list[str]:
        """Sorted provider names available in the registry."""
        return sorted(self._providers)

    async def complete(
        self,
        tenant_id: str,
        request: ModelRequest,
        *,
        provider: str | None = None,
    ) -> ModelResponse:
        """Resolve provider, reserve budget, invoke, reconcile, and log."""
        name = provider or self._default
        impl = self._providers.get(name)
        if impl is None:
            raise ModelNotConfigured(f"unknown provider: {name}")
        if not impl.is_configured():
            raise ModelNotConfigured(f"provider not configured: {name}")

        if self._budget is not None:
            reserved = await self._budget.check_and_reserve(
                tenant_id, self._estimated_request_tokens
            )
            if not reserved:
                metrics.increment(
                    "model_runtime_budget_exceeded",
                    labels={"provider": name},
                )
                raise ModelBudgetExceeded(tenant_id)

        started = time.monotonic()
        try:
            resp = await impl.complete(request)
        except Exception:
            # Fail-open for telemetry: release the full reservation, log the
            # error metric, then re-raise so the call stays fail-closed.
            if self._budget is not None:
                await self._budget.release(tenant_id, self._estimated_request_tokens)
            metrics.increment(
                "model_runtime_invocation_error",
                labels={"provider": name},
            )
            logger.info(
                "model_runtime complete",
                extra={
                    "provider": name,
                    "model": request.model,
                    "latency_ms": (time.monotonic() - started) * 1000,
                    "status": "error",
                },
            )
            raise

        latency_ms = (time.monotonic() - started) * 1000

        # Reconcile the reservation with actual usage (mirrors Noesis).
        if self._budget is not None:
            actual = resp.usage.total_tokens
            if actual < self._estimated_request_tokens:
                await self._budget.release(
                    tenant_id, self._estimated_request_tokens - actual
                )
            elif actual > self._estimated_request_tokens:
                await self._budget.charge(
                    tenant_id, actual - self._estimated_request_tokens
                )

        metrics.increment(
            "model_runtime_invocation_success",
            labels={"provider": name, "model": request.model},
        )
        logger.info(
            "model_runtime complete",
            extra={
                "provider": name,
                "model": request.model,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "latency_ms": latency_ms,
                "status": "success",
            },
        )
        return resp
