"""Provider-neutral runtime data models for the Aether model-runtime.

These models describe model invocations, token usage, and normalized
responses without binding to any specific LLM SDK (anthropic/openai), so
they import with zero side effects. ``metadata`` and ``raw`` are opaque
context buckets: they must NEVER carry secrets, authorization headers, API
keys, or tenant-restricted request content.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field


class ModelProvider(str, enum.Enum):
    """Supported model providers for the model-runtime."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DETERMINISTIC = "deterministic"
    # NOTE: values must match the generated model-registry providers where
    # applicable (anthropic, openai); DETERMINISTIC is the local test fallback.


class ModelRequest(BaseModel):
    """A provider-neutral model invocation request."""

    model_config = ConfigDict(extra="forbid")

    model: str  # provider model id, e.g. "claude-haiku-4-5-20251001"
    messages: list[dict[str, str]]  # [{"role": ..., "content": ...}] turns
    system_prompt: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    response_format: str | None = None  # e.g. "json_object" | "text" | None
    metadata: dict[str, object] = Field(default_factory=dict)


class TokenUsage(BaseModel, frozen=True):
    """Token counts consumed by a single model invocation."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ModelResponse(BaseModel, frozen=True):
    """A provider-normalized model invocation response."""

    content: str
    model: str
    provider: ModelProvider
    usage: TokenUsage
    latency_ms: float
    finish_reason: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)  # provider-raw only


class ModelInvocationError(Exception):
    """Base error for model-runtime invocation failures."""


class ModelProviderError(ModelInvocationError):
    """Raised when a provider returns an error for a model call."""


class ModelTimeoutError(ModelInvocationError):
    """Raised when a provider call times out."""


class ModelBudgetExceeded(ModelInvocationError):
    """Raised when a token budget blocks a model call."""


class ModelNotConfigured(ModelInvocationError):
    """Raised when a provider is not configured or disabled."""
