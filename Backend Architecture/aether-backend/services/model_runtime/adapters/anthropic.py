"""Anthropic transport adapter for the model-runtime (real SDK call).

Real Anthropic SDK transport behind the provider-neutral
``AsyncModelProvider`` contract. The anthropic package is lazy-imported
inside ``complete()`` so this module imports with zero side effects even
when the SDK is not installed.
"""

from __future__ import annotations

import asyncio
import os
import time

from services.model_runtime.models import (
    ModelNotConfigured,
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
    TokenUsage,
)
from services.model_runtime.provider import BaseModelProvider


class AnthropicModelProvider(BaseModelProvider):
    """Real Anthropic SDK transport behind the AsyncModelProvider contract.

    Reads ANTHROPIC_API_KEY, NOESIS_LLM_MODEL at construction; constructor
    kwargs take precedence. timeout_s/max_tokens/max_retries are constructor
    kwargs (defaults 5.0/512/1). Lazy-imports the anthropic SDK inside
    complete() so this module imports with zero side effects. Capability-driven:
    never sends temperature/top_p/top_k (newer Anthropic models reject them
    with 400) — only model, max_tokens, system, messages.

    The adapter honors the routed request model: ``complete()`` sends
    ``request.model`` when it is set and falls back to the configured
    ``self.model`` only when the request model is absent/unset, so an explicit
    or policy-required selection is the model actually invoked.
    """

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float = 5.0,
        max_tokens: int = 512,
        max_retries: int = 1,
    ) -> None:
        """api_key/model override env; defaults mirror the legacy Noesis provider."""
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("NOESIS_LLM_MODEL", "claude-haiku-4-5-20251001")
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.max_retries = max_retries

    def is_configured(self) -> bool:
        # A tenant-bound provider is configured only when its tenant credential
        # can be materialized — never when it would silently reuse the
        # process-wide key.
        if getattr(self, "_bound_resolution", None) is not None:
            try:
                return bool(self._effective_api_key())
            except ModelNotConfigured:
                return False
        return bool(self.api_key)

    def bind_credential(self, resolution) -> "AnthropicModelProvider":
        """Return a per-tenant-bound copy of this provider (ADR-008 D5).

        The returned provider serves a single tenant's invocation: at call time
        it materializes the per-tenant API key from the resolved credential and
        fails closed (``ModelNotConfigured`` — never the process-wide key) when
        the tenant credential cannot be materialized.
        """
        import copy

        bound = copy.copy(self)
        bound._bound_resolution = resolution
        return bound

    def _effective_api_key(self) -> str:
        """The API key for this invocation, honoring a bound tenant credential.

        A bound resolution makes the provider serve a specific tenant: an
        env-source credential uses its per-tenant env ref; any other source
        requires backend materialization, which the adapter cannot perform — it
        fails closed (``ModelNotConfigured``) rather than reuse the process-wide
        key for the tenant.
        """
        bound = getattr(self, "_bound_resolution", None)
        if bound is None:
            return self.api_key
        if bound.source == "env" and bound.ref:
            key = os.getenv(bound.ref)
            if key:
                return key
            raise ModelNotConfigured(
                "anthropic: tenant credential env ref not set"
            )
        raise ModelNotConfigured(
            "anthropic: tenant credential requires backend materialization"
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete a single request against the Anthropic Messages API."""
        api_key = self._effective_api_key()
        if not api_key:
            raise ModelNotConfigured("anthropic adapter not configured")
        model = request.model if request.model else self.model
        import anthropic  # lazy: module imports cleanly when the SDK is absent

        client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=self.max_retries)
        kwargs: dict[str, object] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": request.messages,
        }
        if request.system_prompt:
            kwargs["system"] = request.system_prompt
        started = time.monotonic()
        try:
            response = await asyncio.wait_for(
                client.messages.create(**kwargs),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            raise ModelTimeoutError("anthropic request timed out") from None
        except Exception as exc:  # noqa: BLE001 — covers anthropic.APIStatusError
            raise ModelProviderError(f"anthropic API error: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000
        text = response.content[0].text if response.content else ""
        input_tokens = (response.usage.input_tokens or 0) if response.usage else 0
        output_tokens = (response.usage.output_tokens or 0) if response.usage else 0
        return ModelResponse(
            content=text,
            model=model,
            provider=ModelProvider.ANTHROPIC,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            latency_ms=latency_ms,
            finish_reason="stop",
            raw={},
        )
