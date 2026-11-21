"""Read-only validation of historical agent tool/resource invocation receipts.

Aether is observation-only (ADR-012): it no longer invokes MCP tools or reads
MCP resources on an agent's behalf, so nothing produces new receipts. Receipts
written before that change stay readable as historical evidence, and Agent 360,
Execution 360 and workflow authorities validate them exactly as before.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from shared.temporal.instant import parse_instant_strict
from repositories.repos import BaseRepository
from actions.agent_access_intelligence.models import capability_id_for
from actions.agent_access_intelligence.authority import (
    CAPABILITY_RESOURCE_PREFIX,
    server_ref_for,
    MCP_RESOURCE_PREFIX,
    RESOURCE_READ_ACTION,
)
from actions.agent_access_intelligence.models import resource_id_for


class InvocationReceiptRepository(BaseRepository):
    """Historical invocation evidence. Read-only: no producer remains."""

    def __init__(self) -> None:
        super().__init__("agent_invocation_receipts")

    async def for_execution(
        self, tenant_id: str, agent_id: str, execution_id: str
    ) -> list[dict[str, Any]]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id, "execution_id": execution_id},
            limit=101,
        )
        return rows if len(rows) <= 100 else []


async def validated_agent_receipt(
    *,
    tenant_id: str,
    agent_id: str,
    execution: dict[str, Any],
    expected_workflow_run_id: str | None = None,
) -> dict[str, Any] | None:
    """Resolve one exact complete provider receipt for an Agent360 execution row."""
    execution_id = execution.get("execution_id") or execution.get("id")
    if (
        not _exact_identifier(execution_id)
        or execution.get("tenant_id") != tenant_id
        or (
            expected_workflow_run_id is not None
            and execution.get("workflow_run_id") != expected_workflow_run_id
        )
        or execution.get("agent_id") != agent_id
    ):
        return None
    rows = await InvocationReceiptRepository().for_execution(tenant_id, agent_id, execution_id)
    if len(rows) != 1:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        return None
    if row.get("action") == RESOURCE_READ_ACTION:
        return await _validated_resource_receipt(row, tenant_id, agent_id, execution, execution_id)
    try:
        invoked = datetime.fromisoformat(str(row["invoked_at"]).replace("Z", "+00:00"))
        completed = datetime.fromisoformat(str(row["completed_at"]).replace("Z", "+00:00"))
        started = datetime.fromisoformat(str(execution["started_at"]).replace("Z", "+00:00"))
        ended = datetime.fromisoformat(str(execution["ended_at"]).replace("Z", "+00:00"))
        grant_start = datetime.fromisoformat(str(row["grant_starts_at"]).replace("Z", "+00:00"))
        grant_end = (
            datetime.fromisoformat(str(row["grant_ends_at"]).replace("Z", "+00:00"))
            if row.get("grant_ends_at")
            else None
        )
        evaluated = parse_instant_strict(row["policy_decision"]["evaluated_at"])
    except (KeyError, TypeError, ValueError):
        return None
    policy = row.get("policy_decision")
    grant_scope = row.get("grant_scope")
    scoped_resources = grant_scope.get("resources") if isinstance(grant_scope, dict) else None
    if (
        not isinstance(scoped_resources, list)
        or not all(_exact_identifier(value) for value in scoped_resources)
        or any(
            not _exact_identifier(row.get(key))
            for key in (
                "receipt_id",
                "tool_name",
                "capability_id",
                "grant_id",
                "provider",
                "server_key",
            )
        )
    ):
        return None
    if (
        any(value.tzinfo is None for value in (invoked, completed, started, ended, grant_start))
        or (grant_end is not None and grant_end.tzinfo is None)
        or row.get("tenant_id") != tenant_id
        or row.get("agent_id") != agent_id
        or row.get("execution_id") != execution_id
        or row.get("action") != "invoke"
        or row.get("id") != row.get("receipt_id")
        or row.get("workflow_run_id") != execution.get("workflow_run_id")
        or row.get("workflow_definition_link") != execution.get("workflow_definition_link")
        or row.get("evidence_version") != 1
        or not row.get("receipt_id")
        or row.get("tool_call_attempted") is not True
        or not row.get("tool_name")
        or not row.get("capability_id")
        or not row.get("grant_id")
        or not isinstance(policy, dict)
        or policy.get("allowed") is not True
        or policy.get("delegation_id") != row.get("grant_id")
        or not isinstance(grant_scope, dict)
        or grant_scope.get("actions") != ["invoke"]
        or not isinstance(scoped_resources, list)
        or row.get("policy_resource") not in scoped_resources
        or policy.get("matched_scope") != grant_scope
        or not _exact_identifier(row.get("initiating_principal_user_id"))
        or not _public_mcp_url(row.get("provider_url"))
        or not _exact_identifier(row.get("provider"))
        or not _exact_identifier(row.get("server_key"))
        or row.get("capability_id")
        != capability_id_for(
            tenant_id, row.get("provider"), row.get("server_key"), row.get("tool_name")
        )
        or row.get("resource") != f"{CAPABILITY_RESOURCE_PREFIX}{row.get('capability_id')}"
        or row.get("policy_resource")
        not in {
            row.get("resource"),
            f"capability-server:{server_ref_for(tenant_id, row['server_key'])}",
        }
        or row.get("result_status") not in {"succeeded", "failed"}
        or (
            row.get("result_status") == "succeeded"
            and (
                not isinstance(row.get("provider_result_digest"), str)
                or len(row["provider_result_digest"]) != 64
                or not isinstance(row.get("provider_result_complete"), bool)
            )
        )
        or not started <= invoked <= completed <= ended
        or not grant_start <= evaluated <= invoked
        or completed > datetime.now(timezone.utc)
        or invoked < grant_start
        or (grant_end is not None and invoked >= grant_end)
    ):
        return None
    return {
        "state": "provider_invocation_succeeded"
        if row["result_status"] == "succeeded"
        else "provider_invocation_failed",
        "receiptId": row["receipt_id"],
        "toolName": row["tool_name"],
        "capabilityId": row["capability_id"],
        "action": row["action"],
        "resource": row.get("resource"),
        "policyResource": row.get("policy_resource"),
        "policyDecision": policy,
        "grantId": row["grant_id"],
        "invokedAt": invoked.isoformat(),
        "completedAt": completed.isoformat(),
        "resultStatus": row["result_status"],
        "providerResult": row.get("provider_result"),
        "providerResultDigest": row.get("provider_result_digest"),
        "providerResultComplete": row.get("provider_result_complete"),
        "providerError": row.get("provider_error"),
        "resourceOperation": "unknown",
    }


async def _validated_resource_receipt(row: dict[str, Any], tenant_id: str, agent_id: str,
                                execution: dict[str, Any], execution_id: str) -> dict[str, Any] | None:
    try:
        invoked = parse_instant_strict(row.get("invoked_at"))
        completed = parse_instant_strict(row.get("completed_at"))
        started = parse_instant_strict(execution.get("started_at"))
        ended = parse_instant_strict(execution.get("ended_at"))
        grant_start = parse_instant_strict(row.get("grant_starts_at"))
        grant_end = parse_instant_strict(row["grant_ends_at"]) if row.get("grant_ends_at") else None
        decision_at = parse_instant_strict((row.get("policy_decision") or {}).get("evaluated_at"))
    except (TypeError, ValueError):
        return None
    scope, policy = row.get("grant_scope"), row.get("policy_decision")
    if (row.get("tenant_id") != tenant_id or row.get("agent_id") != agent_id
        or row.get("execution_id") != execution_id or row.get("workflow_run_id") != execution.get("workflow_run_id")
        or row.get("action") != RESOURCE_READ_ACTION or row.get("resource_operation") != "read"
        or row.get("workflow_definition_link") != execution.get("workflow_definition_link")
        or row.get("resource_id") != resource_id_for(tenant_id, row.get("provider"), row.get("server_key"), row.get("resource_uri"))
        or row.get("id") != row.get("receipt_id") or row.get("evidence_version") != 1
        or not all(_exact_identifier(row.get(k)) for k in ("receipt_id", "resource_id", "provider", "server_key", "grant_id", "initiating_principal_user_id"))
        or not _exact_identifier(row.get("resource_uri")) or not _public_mcp_url(row.get("provider_url"))
        or row.get("resource") != f"{MCP_RESOURCE_PREFIX}{row.get('resource_id')}"
        or row.get("policy_resource") != row.get("resource")
        or scope != {"actions": [RESOURCE_READ_ACTION], "resources": [row.get("resource")]}
        or not isinstance(policy, dict) or policy.get("allowed") is not True
        or policy.get("delegation_id") != row.get("grant_id") or policy.get("matched_scope") != scope
        or row.get("resource_read_attempted") is not True or row.get("tool_call_attempted") is not False
        or row.get("result_status") not in {"succeeded", "failed"}
        or (row.get("result_status") == "succeeded" and (not isinstance(row.get("provider_result_digest"), str) or re.fullmatch(r"[0-9a-f]{64}", row["provider_result_digest"]) is None))
        or (row.get("provider_result_complete") is True and not _exact_resource_contents(row.get("provider_result"), row.get("resource_uri")))
        or not started <= invoked <= completed <= ended or not grant_start <= decision_at <= invoked
        or (grant_end is not None and (grant_end.tzinfo is None or invoked >= grant_end))
        or (row.get("provider_result_complete") is True and hashlib.sha256(
            json.dumps(row.get("provider_result"), sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest() != row.get("provider_result_digest"))
        or (row.get("result_status") == "succeeded" and (not isinstance(row.get("provider_resource_listing_digest"), str)
            or len(row["provider_resource_listing_digest"]) != 64))
        or completed > datetime.now(timezone.utc)):
        return None
    from actions.agent_access_intelligence.repositories import CapabilityCatalogRepository
    canonical = await CapabilityCatalogRepository().find_by_id(row["resource_id"])
    if (not isinstance(canonical, dict) or canonical.get("tenant_id") != tenant_id
        or canonical.get("capability_kind") != "resource"
        or canonical.get("resource_uri") != row.get("resource_uri")
        or canonical.get("provider") != row.get("provider")
        or (canonical.get("server_name") or canonical.get("server_url")) != row.get("server_key")
        or canonical.get("server_url") != row.get("provider_url")):
        return None
    state = ("provider_resource_read_succeeded" if row["result_status"] == "succeeded"
             else "provider_resource_read_failed" if row.get("resource_read_attempted") is True
             else "provider_resource_read_not_attempted")
    return {"state": state,
        "receiptId": row["receipt_id"], "resourceId": row["resource_id"], "resourceUri": row["resource_uri"],
        "resourceOperation": "read", "action": row["action"], "policyDecision": policy, "grantId": row["grant_id"],
        "initiatingPrincipalUserId": row["initiating_principal_user_id"],
        "invokedAt": invoked.isoformat(), "completedAt": completed.isoformat(), "resultStatus": row["result_status"],
        "providerResult": row.get("provider_result"), "providerResultDigest": row.get("provider_result_digest"),
        "providerResultComplete": row.get("provider_result_complete"), "providerError": row.get("provider_error"),
        "externalEffect": "unknown"}


def _exact_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and "*" not in value


def _exact_resource_contents(result: Any, resource_uri: str) -> bool:
    contents = result.get("contents") if isinstance(result, dict) else None
    return (
        isinstance(contents, list)
        and bool(contents)
        and all(
            isinstance(item, dict)
            and item.get("uri") == resource_uri
            and (isinstance(item.get("text"), str) or isinstance(item.get("blob"), str))
            for item in contents
        )
    )


def _public_mcp_url(value: Any) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
        )
    except ValueError:
        return False
