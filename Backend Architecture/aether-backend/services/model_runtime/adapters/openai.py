"""OpenAI chat-completions transport adapter.

Real OpenAI transport behind the provider-neutral contract, implemented
directly on httpx (no openai SDK). Reads credentials/config from env at
construction; constructor kwargs take precedence. httpx is imported lazily
inside complete() so this module imports with zero side effects even when
httpx is absent.
"""

from __future__ import annotations

import asyncio
import inspect
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
        # ``None`` means use the process environment; an explicit empty key
        # intentionally disables process-wide credentials for deterministic,
        # fail-closed construction and tenant-bound adapter tests.
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("NOESIS_LLM_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv(
            "OPENAI_API_BASE", "https://api.openai.com/v1"
        )
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        # Just-in-time secret-backend materializer attached by the service at
        # dispatch time (never through the secret-free resolution metadata).
        self._credential_materializer = None

    def is_configured(self) -> bool:
        # A tenant-bound provider is configured only when its tenant credential
        # can be materialized — never when it would silently reuse the
        # process-wide key.
        if getattr(self, "_bound_resolution", None) is not None:
            try:
                return self._can_materialize()
            except ModelNotConfigured:
                return False
        return bool(self.api_key)

    def bind_credential(self, resolution, *, materializer=None) -> "OpenAIModelProvider":
        """Return a per-tenant-bound copy of this provider (ADR-008 D5).

        The returned provider serves a single tenant's invocation: at call time
        it materializes the per-tenant API key from the resolved credential and
        fails closed (``ModelNotConfigured`` — never the process-wide key) when
        the tenant credential cannot be materialized.

        ``materializer`` is an optional just-in-time secret-backend hook,
        ``(tenant_id, ref) -> str | None`` (sync or async). It is used only for
        a ``secret_backend`` resolution and is supplied by the service at
        dispatch time; the fetched key is bound to this per-request adapter and
        never passes through the (secret-free) resolution metadata or any log.
        """
        import copy

        bound = copy.copy(self)
        bound._bound_resolution = resolution
        bound._credential_materializer = materializer
        return bound

    def _can_materialize(self) -> bool:
        """Synchronous, secret-free capability check for a bound tenant credential.

        env-source: the per-tenant env ref must be set. secret_backend-source:
        a just-in-time materializer must be attached (the resolver has already
        validated the credential as configured; the key itself is fetched at
        call time). Any other source cannot be served by the adapter.
        """
        bound = self._bound_resolution
        if bound.source == "env" and bound.ref:
            return bool(os.getenv(bound.ref))
        if bound.source == "secret_backend":
            return callable(getattr(self, "_credential_materializer", None))
        return False

    def _effective_api_key(self) -> str:
        """The API key for this invocation, honoring a bound tenant credential.

        Synchronous fast path for unbound/env-source credentials. A bound
        resolution makes the provider serve a specific tenant: an env-source
        credential uses its per-tenant env ref. A secret-backend credential
        requires async backend materialization and is handled by
        :meth:`_resolve_api_key` at call time — this path fails closed
        (``ModelNotConfigured``) rather than reuse the process-wide key.
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

    async def _resolve_api_key(self) -> str:
        """Resolve the API key for an invocation, including just-in-time
        secret-backend materialization.

        Fails closed (``ModelNotConfigured``) when the tenant credential cannot
        be materialized — the process-wide key is never reused for a tenant.
        """
        bound = getattr(self, "_bound_resolution", None)
        if bound is not None and bound.source == "secret_backend":
            return await self._materialize_secret(bound)
        return self._effective_api_key()

    async def _materialize_secret(self, resolution) -> str:
        """Fetch the tenant's raw key from the secret backend (just-in-time).

        The value is bound to this per-request adapter copy only; it is never
        written to the resolution, metadata, metrics, or logs. Fails closed
        when no materializer is attached or the backend returns nothing.
        """
        materializer = getattr(self, "_credential_materializer", None)
        if not callable(materializer):
            raise ModelNotConfigured(
                "openai: tenant secret-backend credential requires backend "
                "materialization"
            )
        try:
            result = materializer(resolution.tenant_id, resolution.ref)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 — fail closed on backend errors
            raise ModelNotConfigured(
                "openai: tenant secret-backend credential not materializable"
            ) from exc
        if isinstance(result, str) and result:
            return result
        raise ModelNotConfigured(
            "openai: tenant secret-backend credential not materializable"
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
        api_key = await self._resolve_api_key()
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
