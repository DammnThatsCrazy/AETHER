"""Pydantic mirrors of the canonical AI execution contracts.

Source of truth: ``packages/shared/ai-execution.ts`` (schema version
``ai.execution.v1``). Records carry identity, usage, model, provider, cost,
latency, quality, and outcome correlation — NEVER raw prompt or completion
content. Payloads carrying prompt/completion-shaped fields are rejected at
validation time.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AI_EXECUTION_SCHEMA_VERSION = "ai.execution.v1"

CostBasis = Literal["billed", "provider_reported", "calculated", "estimated", "unknown"]
COST_BASES: tuple[str, ...] = ("billed", "provider_reported", "calculated", "estimated", "unknown")

AIInvocationStatus = Literal["succeeded", "failed", "cancelled", "timeout"]
AI_INVOCATION_STATUSES: tuple[str, ...] = ("succeeded", "failed", "cancelled", "timeout")

AIDataQualityStatus = Literal["complete", "partial", "estimated", "suspect"]
AI_DATA_QUALITY_STATUSES: tuple[str, ...] = ("complete", "partial", "estimated", "suspect")

# Field names that indicate raw prompt/completion content. Any payload that
# carries one of these keys — at any nesting depth — is rejected outright.
BANNED_CONTENT_KEYS: frozenset[str] = frozenset({
    "prompt_text",
    "completion_text",
    "prompt",
    "completion",
    "messages",
    "chain_of_thought",
})

# The ten priced usage dimensions of an invocation.
USAGE_DIMENSIONS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "embedding_tokens",
    "image_units",
    "audio_seconds",
    "video_seconds",
    "tool_call_count",
    "retrieval_count",
)

_MAX_FREE_TEXT = 256


def _scan_banned_keys(value: Any, path: str = "") -> None:
    """Recursively reject prompt/completion-content field names anywhere in a payload."""
    if isinstance(value, dict):
        for key, nested in value.items():
            key_str = str(key)
            if key_str.lower() in BANNED_CONTENT_KEYS:
                raise ValueError(
                    f"payload contains forbidden prompt/completion content field "
                    f"{key_str!r} at {path or '<root>'}"
                )
            _scan_banned_keys(nested, f"{path}.{key_str}" if path else key_str)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_banned_keys(item, f"{path}[{index}]")


class AIInvocationProvenance(BaseModel):
    """Emitting source + replay identity of an observed invocation."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    provider_request_id: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    raw_event_hash: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    schema_version: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)


class AIInvocationObserved(BaseModel):
    """Canonical ``ai_invocation_observed`` event payload (ai.execution.v1)."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)

    trace_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    task_id: Optional[str] = None
    action_id: Optional[str] = None
    recommendation_id: Optional[str] = None
    suggestion_id: Optional[str] = None
    outcome_id: Optional[str] = None
    entity_id: Optional[str] = None
    agent_id: Optional[str] = None
    campaign_id: Optional[str] = None

    task_type: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    use_case: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    business_unit: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    environment: Optional[Literal["development", "staging", "production"]] = None

    provider: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    model: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    model_version: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    deployment_id: Optional[str] = None
    region: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)

    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None
    prompt_hash: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    configuration_hash: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)

    input_tokens: Optional[float] = Field(default=None, ge=0)
    output_tokens: Optional[float] = Field(default=None, ge=0)
    cached_input_tokens: Optional[float] = Field(default=None, ge=0)
    reasoning_tokens: Optional[float] = Field(default=None, ge=0)
    embedding_tokens: Optional[float] = Field(default=None, ge=0)
    image_units: Optional[float] = Field(default=None, ge=0)
    audio_seconds: Optional[float] = Field(default=None, ge=0)
    video_seconds: Optional[float] = Field(default=None, ge=0)
    tool_call_count: Optional[float] = Field(default=None, ge=0)
    retrieval_count: Optional[float] = Field(default=None, ge=0)

    latency_ms: Optional[float] = Field(default=None, ge=0)
    time_to_first_token_ms: Optional[float] = Field(default=None, ge=0)
    retry_count: Optional[int] = Field(default=None, ge=0)

    status: AIInvocationStatus
    error_code: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)

    estimated_cost: Optional[float] = Field(default=None, ge=0)
    actual_cost: Optional[float] = Field(default=None, ge=0)
    billed_cost: Optional[float] = Field(default=None, ge=0)
    currency: str = Field(min_length=1, max_length=16)
    pricing_version: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    customer_managed_key: Optional[bool] = None

    quality_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evaluation_id: Optional[str] = None
    human_reviewed: Optional[bool] = None
    human_corrected: Optional[bool] = None

    contains_prompt_content: bool = False
    contains_completion_content: bool = False
    data_classification: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)

    provenance: AIInvocationProvenance

    @model_validator(mode="before")
    @classmethod
    def _reject_prompt_content_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            _scan_banned_keys(data)
        return data

    @field_validator("task_type", "provider", "model", "tenant_id", "invocation_id")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    def usage_present(self) -> bool:
        """True when at least one of the ten usage dimensions was reported."""
        return any(getattr(self, dim) is not None for dim in USAGE_DIMENSIONS)


class AIExecutionFact(AIInvocationObserved):
    """Silver projection ``ai_execution_facts`` — one row per (tenant, invocation).

    ``selected_cost`` is chosen by the hierarchy billed → provider_reported →
    calculated → estimated → unknown. Unknown cost stays ``None`` — it never
    silently becomes zero.
    """

    selected_cost: Optional[float] = None
    cost_basis: CostBasis
    received_at: str
    computed_at: str
    data_quality_status: AIDataQualityStatus


class AIPriceCardRates(BaseModel):
    """Rates for the ten priced usage dimensions. All rates are non-negative."""

    model_config = ConfigDict(extra="forbid")

    input_tokens_per_1k: Optional[float] = Field(default=None, ge=0)
    output_tokens_per_1k: Optional[float] = Field(default=None, ge=0)
    cached_input_tokens_per_1k: Optional[float] = Field(default=None, ge=0)
    reasoning_tokens_per_1k: Optional[float] = Field(default=None, ge=0)
    embedding_tokens_per_1k: Optional[float] = Field(default=None, ge=0)
    image_unit: Optional[float] = Field(default=None, ge=0)
    audio_second: Optional[float] = Field(default=None, ge=0)
    video_second: Optional[float] = Field(default=None, ge=0)
    tool_call: Optional[float] = Field(default=None, ge=0)
    retrieval: Optional[float] = Field(default=None, ge=0)


class AIPriceCard(BaseModel):
    """Effective-dated price card for provider/model/region/service tier."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    provider: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    model: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    region: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    service_tier: Optional[str] = Field(default=None, max_length=_MAX_FREE_TEXT)
    currency: str = Field(min_length=1, max_length=16)
    pricing_version: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    rates: AIPriceCardRates
    effective_from: str = Field(min_length=1)
    effective_to: Optional[str] = None
    source: str = Field(min_length=1, max_length=_MAX_FREE_TEXT)
    created_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_effective_window(self) -> "AIPriceCard":
        if self.effective_to is not None and not (self.effective_from < self.effective_to):
            raise ValueError("effective_from must be strictly before effective_to")
        return self


class AIWorkflowEconomics(BaseModel):
    """Workflow-level economics aggregated by (tenant_id, workflow_run_id).

    Workflow IDs are never fabricated — invocations without a workflow_run_id
    are excluded from workflow aggregation.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    workflow_run_id: str = Field(min_length=1)

    total_invocations: int = Field(ge=0)
    successful_invocations: int = Field(ge=0)
    failed_invocations: int = Field(ge=0)
    total_retries: int = Field(ge=0)
    total_latency_ms: float = Field(ge=0)

    total_model_cost: Optional[float] = None
    tool_cost: Optional[float] = None
    retrieval_cost: Optional[float] = None
    fully_loaded_cost: Optional[float] = None
    currency: str
    cost_coverage: float = Field(ge=0.0, le=1.0)

    quality_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    human_reviewed: bool = False
    human_corrected: bool = False
    technical_success: bool = False

    qualified_outcome_count: int = Field(ge=0)
    attributed_value: Optional[float] = None

    first_observed_at: str
    last_observed_at: str
    computed_at: str


AI_EFFICIENCY_DETECTORS: tuple[str, ...] = (
    "retry_waste",
    "model_overqualification",
    "deterministic_replacement_candidate",
    "cache_opportunity",
    "failed_workflow_concentration",
)

AI_OUTCOME_EFFICIENCY_FAMILY = "ai_outcome_efficiency"
