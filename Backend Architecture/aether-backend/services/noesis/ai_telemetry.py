"""Noesis → AI execution fact telemetry.

Records each Noesis LLM invocation as a canonical AI execution fact through
the same projector seam the Silver path uses (direct function call — no HTTP,
no bus). Carries usage/latency/cost dimensions ONLY: never prompt text,
completion text, or chain of thought.

Fail-open by design: telemetry must NEVER break planning. Every failure is
swallowed (logged at debug) and the caller proceeds unaffected.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.ai_telemetry")

_VALID_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timeout"})

NOESIS_TASK_TYPE = "noesis_plan"
NOESIS_SOURCE = "noesis"
SCHEMA_VERSION = "ai.execution.v1"


def _stable_hash(
    provider: str,
    model: str,
    input_tokens: Optional[float],
    output_tokens: Optional[float],
    observed_at: str,
) -> str:
    raw = f"{NOESIS_SOURCE}|{provider}|{model}|{input_tokens}|{output_tokens}|{observed_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def record_noesis_invocation(
    *,
    tenant_id: str,
    provider: str,
    model: str,
    status: str = "succeeded",
    input_tokens: Optional[float] = None,
    output_tokens: Optional[float] = None,
    latency_ms: Optional[float] = None,
    retry_count: int = 0,
    error_code: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    """Record one Noesis LLM invocation as an AI execution fact.

    Flag-gated on ``settings.ai_economics.execution_facts_enabled`` and
    fail-open: any error is swallowed so telemetry can never break planning.
    """
    try:
        from config.settings import settings

        if not settings.ai_economics.execution_facts_enabled:
            return
        if not tenant_id or not provider or not model:
            return

        from services.economic.ai_models import AIInvocationObserved
        from services.silver.projectors.ai_invocation_projector import write_execution_fact

        observed_at = datetime.now(timezone.utc).isoformat()
        observed = AIInvocationObserved(
            invocation_id=f"noesis-{uuid.uuid4().hex}",
            tenant_id=tenant_id,
            observed_at=observed_at,
            trace_id=trace_id,
            task_type=NOESIS_TASK_TYPE,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            retry_count=max(int(retry_count), 0),
            status=status if status in _VALID_STATUSES else "failed",
            error_code=error_code,
            currency="USD",
            contains_prompt_content=False,
            contains_completion_content=False,
            provenance={
                "source": NOESIS_SOURCE,
                "raw_event_hash": _stable_hash(
                    provider, model, input_tokens, output_tokens, observed_at
                ),
                "schema_version": SCHEMA_VERSION,
            },
        )
        await write_execution_fact(observed)
    except Exception as exc:  # noqa: BLE001 — telemetry must never break planning
        logger.debug("noesis ai telemetry dropped: %s", exc)
