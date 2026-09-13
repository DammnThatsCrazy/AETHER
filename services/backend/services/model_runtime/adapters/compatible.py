"""Generic OpenAI-compatible endpoint adapter for the model-runtime.

Drives any provider exposing an OpenAI-compatible ``/chat/completions``
endpoint (Kimi-family, DeepSeek, vLLM, self-hosted gateways, etc.) by reusing
the ``OpenAIModelProvider`` httpx transport. Config is read from the dedicated
``MODEL_RUNTIME_COMPAT_*`` env surface at construction so many compatible
providers can coexist in the runtime registry under distinct ``provider_name``
values. Imports with zero side effects (no httpx at top level).
"""

from __future__ import annotations

import os

from services.model_runtime.adapters.openai import OpenAIModelProvider


class OpenAICompatibleModelProvider(OpenAIModelProvider):
    """Generic OpenAI-compatible endpoint adapter (Kimi-family, self-hosted, etc.).

    Reuses the OpenAIModelProvider httpx chat-completions transport but reads its
    config from the dedicated MODEL_RUNTIME_*_COMPAT env surface so many compatible
    providers can coexist in the runtime registry. ``provider_name`` is an instance
    attribute (defaults "openai_compatible") so each constructed provider can
    register under its own name.

    Config precedence (highest first): explicit constructor kwargs, then the
    ``MODEL_RUNTIME_COMPAT_*`` env vars, then the OpenAIModelProvider defaults
    (``OPENAI_API_KEY`` / ``NOESIS_LLM_MODEL`` / ``OPENAI_API_BASE``). A
    deployment that sets only the ``MODEL_RUNTIME_COMPAT_*`` vars can drive a
    compatible endpoint without touching the OpenAI env surface at all.

    Env surface:
      MODEL_RUNTIME_COMPAT_API_KEY         -> api_key
      MODEL_RUNTIME_COMPAT_MODEL           -> model
      MODEL_RUNTIME_COMPAT_BASE_URL        -> base_url
      MODEL_RUNTIME_COMPAT_PROVIDER_NAME   -> provider_name ("openai_compatible")

    ``is_configured`` and ``complete`` are inherited from OpenAIModelProvider
    unchanged; credentials and request content are never logged.
    """

    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        provider_name: str | None = None,
        timeout_s: float = 5.0,
        max_tokens: int = 512,
        max_retries: int = 1,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        self.provider_name = provider_name or os.getenv(
            "MODEL_RUNTIME_COMPAT_PROVIDER_NAME", "openai_compatible"
        )
        if not api_key:
            compat_key = os.getenv("MODEL_RUNTIME_COMPAT_API_KEY")
            if compat_key:
                self.api_key = compat_key
        if not model:
            compat_model = os.getenv("MODEL_RUNTIME_COMPAT_MODEL")
            if compat_model:
                self.model = compat_model
        if not base_url:
            compat_url = os.getenv("MODEL_RUNTIME_COMPAT_BASE_URL")
            if compat_url:
                self.base_url = compat_url
