"""Shared factories for AI economics tests. No network, no prompt content."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from services.economic.ai_models import AIInvocationObserved


def new_tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def observed_payload(**overrides: Any) -> dict[str, Any]:
    """A valid canonical ai_invocation_observed payload (unique ids per call)."""
    payload: dict[str, Any] = {
        "invocation_id": f"inv-{uuid.uuid4().hex[:12]}",
        "tenant_id": f"t-{uuid.uuid4().hex[:8]}",
        "observed_at": utc_now_iso(),
        "task_type": "unit_test_task",
        "provider": f"prov-{uuid.uuid4().hex[:6]}",
        "model": f"model-{uuid.uuid4().hex[:6]}",
        "status": "succeeded",
        "currency": "USD",
        "input_tokens": 1000,
        "output_tokens": 200,
        "latency_ms": 120.0,
        "provenance": {
            "source": "unit_test",
            "raw_event_hash": uuid.uuid4().hex,
            "schema_version": "ai.execution.v1",
        },
    }
    payload.update(overrides)
    return payload


def make_observed(**overrides: Any) -> AIInvocationObserved:
    return AIInvocationObserved.model_validate(observed_payload(**overrides))


def fact_record(**overrides: Any) -> dict[str, Any]:
    """A crafted AIExecutionFact-shaped dict for detector/aggregation tests."""
    now = utc_now_iso()
    record = observed_payload()
    record.update({
        "selected_cost": 1.0,
        "cost_basis": "billed",
        "received_at": now,
        "computed_at": now,
        "data_quality_status": "complete",
        "retry_count": 0,
    })
    record.update(overrides)
    return record


def bronze_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a canonical payload in a Bronze event envelope."""
    return {
        "type": "ai_invocation_observed",
        "messageId": f"msg-{uuid.uuid4().hex[:12]}",
        "timestamp": payload.get("observed_at") or utc_now_iso(),
        "properties": payload,
        "context": {"tenantId": payload.get("tenant_id", "")},
    }
