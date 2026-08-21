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
        return bool(self.api_key)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete a single request against the Anthropic Messages API."""
        if not self.api_key:
            raise ModelNotConfigured("anthropic adapter not configured")
        import anthropic  # lazy: module imports cleanly when the SDK is absent

        client = anthropic.AsyncAnthropic(api_key=self.api_key, max_retries=self.max_retries)
        kwargs: dict[str, object] = {
            "model": self.model,
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
            model=self.model,
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
