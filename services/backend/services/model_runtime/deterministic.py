"""Deterministic offline model provider.

Returns a FIXED response with computed usage and latency. Requires no network,
no SDK, and no credentials — safe for tests, local dev without API keys, and
as a controlled fallback in CI.
"""

from __future__ import annotations

import os

from services.model_runtime.models import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    TokenUsage,
)
from services.model_runtime.provider import AsyncModelProvider

_DEFAULT_RESPONSE_TEMPLATE = "deterministic model response for {model}"


class DeterministicModelProvider(AsyncModelProvider):
    """Fixed-response provider for tests, local dev, and controlled fallback.

    Reads MODEL_RUNTIME_DETERMINISTIC_RESPONSE (fixed completion text) and
    MODEL_RUNTIME_DETERMINISTIC_MODEL (model id to report) at construction,
    with constructor overrides taking precedence for test injection.
    """

    provider_name = "deterministic"

    def __init__(
        self,
        *,
        response_override: str | None = None,
        model_id: str | None = None,
        latency_ms: float = 1.0,
        input_tokens: int = 10,
        output_tokens: int = 20,
        raise_error: BaseException | None = None,
    ) -> None:
        self._response_override = (
            response_override
            if response_override is not None
            else os.getenv("MODEL_RUNTIME_DETERMINISTIC_RESPONSE")
        )
        self._model_id_override = (
            model_id
            if model_id is not None
            else os.getenv("MODEL_RUNTIME_DETERMINISTIC_MODEL")
        )
        self._latency_ms = latency_ms
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._raise_error = raise_error

    def is_configured(self) -> bool:
        return True

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Return the fixed response. If raise_error is set, raise it (for
        error-path tests). Never touches the network."""
        if self._raise_error is not None:
            raise self._raise_error
        model = self._model_id_override or request.model
        if self._response_override is not None:
            content = self._response_override
        else:
            content = _DEFAULT_RESPONSE_TEMPLATE.format(model=model)
        return ModelResponse(
            content=content,
            model=model,
            provider=ModelProvider.DETERMINISTIC,
            usage=TokenUsage(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                total_tokens=self._input_tokens + self._output_tokens,
            ),
            latency_ms=self._latency_ms,
            finish_reason="stop",
            raw={},
        )
