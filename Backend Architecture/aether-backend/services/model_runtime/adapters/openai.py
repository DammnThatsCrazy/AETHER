"""OpenAI chat-completions transport adapter.

Real OpenAI transport behind the provider-neutral contract, implemented
directly on httpx (no openai SDK). Reads credentials/config from env at
construction; constructor kwargs take precedence. httpx is imported lazily
inside complete() so this module imports with zero side effects even when
httpx is absent.
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


class OpenAIModelProvider(BaseModelProvider):
    """Real OpenAI chat-completions transport via httpx behind the contract.

    Reads OPENAI_API_KEY, NOESIS_LLM_MODEL, OPENAI_API_BASE at construction;
    constructor kwargs take precedence. timeout_s/max_tokens/max_retries are
    constructor kwargs (defaults 5.0/512/1). Lazy-imports httpx inside
    complete(). Emits response_format json_object when the request asks for it.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 5.0,
        max_tokens: int = 512,
        max_retries: int = 1,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("NOESIS_LLM_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv(
            "OPENAI_API_BASE", "https://api.openai.com/v1"
        )
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

    def bind_credential(self, resolution) -> "OpenAIModelProvider":
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
            raise ModelNotConfigured("openai: tenant credential env ref not set")
        raise ModelNotConfigured(
            "openai: tenant credential requires backend materialization"
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete one request against the OpenAI chat-completions API.

        Lazy-imports httpx. Raises ModelNotConfigured when no API key is set,
        ModelTimeoutError on timeout, ModelProviderError on API/transport
        errors. Sends ``request.model`` when set (falling back to the
        configured ``self.model`` only when the request model is absent/unset),
        so a routed selection is the model actually invoked. Never logs request
        content, prompts, or credentials.
        """
        api_key = self._effective_api_key()
        if not api_key:
            raise ModelNotConfigured("openai adapter not configured")

        import httpx

        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)

        model = request.model if request.model else self.model
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        async def _post() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                return await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

        started = time.monotonic()
        try:
            resp = await asyncio.wait_for(_post(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            raise ModelTimeoutError("openai request timed out") from None

        try:
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise ModelProviderError(f"openai API error: {exc}") from exc
        except Exception as exc:
            raise ModelProviderError(f"openai transport error: {exc}") from exc

        latency_ms = (time.monotonic() - started) * 1000

        choices = body.get("choices") or []
        message = (choices[0] if choices else {}).get("message") or {}
        text = message.get("content") or ""
        usage = body.get("usage") or {}
        input_tokens = usage.get("prompt_tokens") or 0
        output_tokens = usage.get("completion_tokens") or 0

        return ModelResponse(
            content=text,
            model=model,
            provider=ModelProvider.OPENAI,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            latency_ms=latency_ms,
            finish_reason="stop",
            raw={},  # never secrets / never request content
        )
