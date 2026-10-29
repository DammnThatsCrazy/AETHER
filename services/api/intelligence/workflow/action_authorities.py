"""Bounded workflow execution result and approved resource evidence.

A recorded executor callback is an execution-level result, not a tool-result or
an external-effect receipt. A current protected resource is not historical
resource state or proof of a resource operation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from shared.temporal.instant import parse_instant_strict


def execution_result(*, tenant_id: str, workflow_run_id: str, execution: dict[str, Any],
                     called_at: str) -> dict[str, Any] | None:
    execution_id = execution.get("execution_id")
    status = execution.get("status")
    if (execution.get("tenant_id") != tenant_id or execution.get("workflow_run_id") != workflow_run_id
            or not isinstance(execution_id, str) or not execution_id or status not in {"completed", "failed"}
            or execution.get("id") != execution_id
            or execution.get("outcome_event_published") is not True):
        return None
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aether:agent-execution:{tenant_id}:{execution_id}:{status}"))
    if execution.get("outcome_event_id") != expected:
        return None
    try:
        created = parse_instant_strict(execution.get("created_at"))
        called = parse_instant_strict(called_at)
        ended = parse_instant_strict(execution.get("ended_at"))
    except (TypeError, ValueError):
        return None
    if not created <= called <= ended or ended > datetime.now(timezone.utc):
        return None
    return {"state": "recorded_executor_completion" if status == "completed" else "recorded_executor_failure",
            "endedAt": ended.isoformat(), "recordedEventId": expected,
            "toolResult": "unknown", "externalEffect": "unknown"}


async def approved_resources(*, tenant_id: str, workflow_run_id: str,
                             access_rows: list[dict[str, Any]], store: Any = None) -> list[dict[str, str]]:
    if store is None:
        from value.x402.commerce_store import get_commerce_store
        store = get_commerce_store()
    result: list[dict[str, str]] = []
    for row in access_rows[:200]:
        resource_id = row.get("requested_resource")
        if (row.get("tenant_id") != tenant_id or row.get("workflow_run_id") != workflow_run_id
                or not isinstance(resource_id, str) or not resource_id.strip()
                or not isinstance(row.get("execution_id"), str)):
            continue
        try:
            resource = await store.get_resource(tenant_id, resource_id)
            data = resource.model_dump(mode="json") if hasattr(resource, "model_dump") else resource
            if (not isinstance(data, dict) or data.get("tenant_id") != tenant_id
                    or data.get("resource_id") != resource_id or data.get("active") is not True):
                continue
            registered = parse_instant_strict(data.get("registered_at"))
            evaluated = parse_instant_strict(row.get("evaluated_at"))
            if registered > evaluated:
                continue
        except Exception:  # noqa: BLE001 - missing or malformed resource evidence stays unknown
            continue
        result.append({"execution_id": row["execution_id"], "resource_id": resource_id,
                       "approval_id": row["approval_id"], "decision_id": row["decision_id"],
                       "delegation_id": row["delegation_id"], "registered_at": registered.isoformat()})
    return result
