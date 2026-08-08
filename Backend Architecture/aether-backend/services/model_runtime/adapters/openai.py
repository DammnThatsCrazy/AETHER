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
        return bool(self.api_key)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete one request against the OpenAI chat-completions API.

        Lazy-imports httpx. Raises ModelNotConfigured when no API key is set,
        ModelTimeoutError on timeout, ModelProviderError on API/transport
        errors. Never logs request content, prompts, or credentials.
        """
        if not self.api_key:
            raise ModelNotConfigured("openai adapter not configured")

        import httpx

        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)

        payload: dict[str, object] = {
            "model": self.model,
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
                        "Authorization": f"Bearer {self.api_key}",
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
            model=self.model,
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
