"""Provider-neutral async contract for the model harness.

Every real provider (Anthropic, OpenAI, OpenAI-compatible, Bedrock, self-hosted)
and the deterministic test provider implements ``AsyncModelProvider``. Noesis and
future orchestrators depend ONLY on this Protocol plus the models in
``services.model_runtime.models`` — never on provider SDKs.

This module is SDK-free: it imports no provider libraries and holds no
credentials or secrets. Adapters read their own env/config in ``__init__``.
"""

from __future__ import annotations

import typing

from services.model_runtime.models import ModelRequest, ModelResponse, ModelNotConfigured


class AsyncModelProvider(typing.Protocol):
    """Provider-neutral async contract every harness provider implements."""

    provider_name: str

    # Deliberately synchronous: a plain bool check, matching how adapters read
    # env in __init__. Only ``complete`` is async. Providers that need async
    # setup override ``is_configured`` (must stay awaitable-compatible).
    def is_configured(self) -> bool:
        """True when the provider can serve requests (credentials/config present)."""
        ...

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete a single request. Raises ModelInvocationError subclasses on failure."""
        ...


class BaseModelProvider:
    """Default ``is_configured`` (env-gated) + provider_name helper for adapters."""

    provider_name = "base"

    def __init__(self, enabled: bool | None = None) -> None:
        self._enabled = enabled

    def is_configured(self) -> bool:
        # Synchronous; providers that need async setup override it.
        return self._enabled if self._enabled is not None else False

    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise ModelNotConfigured(f"{self.provider_name} is not configured")
