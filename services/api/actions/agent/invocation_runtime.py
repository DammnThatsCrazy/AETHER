"""Server-owned, bounded MCP tool invocation and immutable result receipts.

Only ``invoke_observed_mcp_tool`` may create these receipts. Observation ingest and
worker execution callbacks do not import or call this producer.
"""

from __future__ import annotations

import json
import hashlib
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from shared.common.common import ConflictError, ForbiddenError
from shared.security.ssrf import send_public_request
from shared.temporal.instant import parse_instant_strict
from repositories.repos import BaseRepository
from actions.agent_access_intelligence.models import capability_id_for
from actions.agent_access_intelligence.repositories import CapabilityCatalogRepository
from actions.agent_access_intelligence.authority import (
    CAPABILITY_RESOURCE_PREFIX,
    CapabilityAuthorizationRepository,
    server_ref_for,
    MCP_RESOURCE_PREFIX,
    RESOURCE_READ_ACTION,
)
from actions.agent_access_intelligence.models import resource_id_for
from actions.delegation.engine import DelegationEngine


class InvocationReceiptRepository(BaseRepository):
    """Create-only invocation evidence; IDs cannot be overwritten or replayed."""

    def __init__(self) -> None:
        super().__init__("agent_invocation_receipts")

    async def record_once(self, receipt: dict[str, Any]) -> dict[str, Any]:
        return await _insert_once(
            self, {**receipt, "id": receipt["receipt_id"]}, "agent_invocation_receipts"
        )

    async def for_execution(
        self, tenant_id: str, agent_id: str, execution_id: str
    ) -> list[dict[str, Any]]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id, "execution_id": execution_id},
            limit=101,
        )
        return rows if len(rows) <= 100 else []


class InvocationClaimRepository(BaseRepository):
    """Non-evidentiary durable dedupe key; a claim never proves tool completion."""

    def __init__(self) -> None:
        super().__init__("agent_invocation_claims")

    async def reserve(self, claim: dict[str, Any]) -> dict[str, Any]:
        return await _insert_once(self, claim, "agent_invocation_claims")


async def _insert_once(
    repository: BaseRepository, data: dict[str, Any], table: str
) -> dict[str, Any]:
    record_id = str(data["id"])
    tenant_id = str(data["tenant_id"])
    pool = await repository._ensure_pool()
    if pool is None:
        if record_id in repository._store:
            raise ConflictError("Invocation already exists")
        repository._store[record_id] = deepcopy(data)
        return deepcopy(data)
    await repository._ensure_table()
    status = await pool.execute(
        f"""INSERT INTO {table} (id, tenant_id, data, created_at, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW(), NOW()) ON CONFLICT (id) DO NOTHING""",
        record_id,
        tenant_id,
        json.dumps(data, default=str),
    )
    if status.endswith(" 0"):
        raise ConflictError("Invocation already exists")
    return dict(data)


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


async def invoke_observed_mcp_tool(
    *,
    tenant_id: str,
    agent_id: str,
    execution_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    config: dict[str, Any],
    workflow_run_id: str | None = None,
    workflow_definition_link: dict[str, Any] | None = None,
    engine: DelegationEngine,
    grants: CapabilityAuthorizationRepository | None = None,
    catalog: CapabilityCatalogRepository | None = None,
    receipts: InvocationReceiptRepository | None = None,
    initiating_principal_user_id: str,
) -> dict[str, Any]:
    """Invoke one exact catalogued MCP tool and write completion evidence.

    Supported scope is HTTPS Streamable HTTP MCP tools only. Resources and arbitrary
    provider actions remain unsupported. HTTP/provider errors produce failure receipts.
    """
    if any(
        not _exact_identifier(value)
        for value in (tenant_id, agent_id, execution_id, tool_name, initiating_principal_user_id)
    ):
        raise ForbiddenError("Exact authenticated invocation scope is required")
    if not isinstance(arguments, dict) or len(json.dumps(arguments, allow_nan=False)) > 64_000:
        raise ForbiddenError("Tool arguments are invalid or exceed the invocation limit")
    # This path intentionally requires explicit agent policy; observed inventory alone
    # does not make a tool callable.
    allowed_tools = config.get("tools")
    if not isinstance(allowed_tools, list) or tool_name not in allowed_tools:
        raise ForbiddenError("Tool is not enabled by the agent policy")
    catalog = catalog or CapabilityCatalogRepository()
    grants = grants or CapabilityAuthorizationRepository()
    receipts = receipts or InvocationReceiptRepository()
    rows = await catalog.list_capabilities(tenant_id, limit=1001)
    if len(rows) > 1000:
        raise ForbiddenError("Observed MCP tool inventory is truncated")
    matches = [
        r
        for r in rows
        if r.get("tenant_id") == tenant_id
        and r.get("tool_name") == tool_name
        and r.get("capability_kind") == "mcp_tool"
    ]
    if len(matches) != 1:
        raise ForbiddenError("Exact observed MCP tool identity is unavailable or ambiguous")
    target = matches[0]
    cap_id = target.get("capability_id")
    if not isinstance(cap_id, str) or cap_id != capability_id_for(
        tenant_id,
        target.get("provider"),
        target.get("server_name") or target.get("server_url"),
        tool_name,
    ):
        raise ForbiddenError("Observed capability identity is invalid")
    server_key = target.get("server_name") or target.get("server_url")
    if not isinstance(server_key, str) or not server_key:
        raise ForbiddenError("Observed MCP server identity is unavailable")
    exact_resources = {
        f"{CAPABILITY_RESOURCE_PREFIX}{cap_id}",
        f"capability-server:{server_ref_for(tenant_id, server_key)}",
    }
    now = datetime.now(timezone.utc)
    grants_list = await grants.find_many(
        filters={
            "tenant_id": tenant_id,
            "grantee_entity_id": agent_id,
            "authorization_kind": "capability",
        },
        limit=2001,
    )
    if len(grants_list) > 2000:
        raise ForbiddenError("Capability grant evidence is truncated")
    qualifying = []
    for grant in grants_list:
        scope = grant.get("scope") if isinstance(grant.get("scope"), dict) else {}
        start, end = grant.get("starts_at"), grant.get("ends_at")
        try:
            begin = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            finish = datetime.fromisoformat(str(end).replace("Z", "+00:00")) if end else None
        except (TypeError, ValueError):
            continue
        if begin.tzinfo is None or (finish is not None and finish.tzinfo is None):
            continue
        resources = scope.get("resources")
        if (
            grant.get("tenant_id") == tenant_id
            and grant.get("grantee_entity_id") == agent_id
            and grant.get("authorization_kind") == "capability"
            and isinstance(resources, list)
            and all(_exact_identifier(value) for value in resources)
            and grant.get("revoked_at") is None
            and begin <= now
            and (finish is None or now < finish)
            and scope.get("actions") == ["invoke"]
            and set(scope.get("resources") or []) & exact_resources
        ):
            qualifying.append(grant)
    if len(qualifying) != 1:
        raise ForbiddenError("One exact active capability grant is required")
    grant = qualifying[0]
    grant_resources = set((grant.get("scope") or {}).get("resources") or [])
    resource = f"{CAPABILITY_RESOURCE_PREFIX}{cap_id}"
    policy_resource = (
        resource if resource in grant_resources else next(iter(grant_resources & exact_resources))
    )
    decision = await engine.evaluate(
        grantee_entity_id=agent_id, action="invoke", resource=policy_resource, tenant_id=tenant_id
    )
    if not decision.allowed or decision.delegation_id != grant.get(
        "delegation_id", grant.get("id")
    ):
        raise ForbiddenError("Invocation policy denied or did not match the exact grant")
    url = target.get("server_url")
    if not _public_mcp_url(url):
        raise ForbiddenError("Only public HTTPS MCP endpoints are supported")
    from governance.security.policy_engine import evaluate_destination_safety

    unsafe, _ = await evaluate_destination_safety(url or "")
    if unsafe:
        raise ForbiddenError("Only public HTTPS MCP endpoints are supported")
    claim_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"aether:mcp-call:{tenant_id}:{agent_id}:{execution_id}:{tool_name}"
        )
    )
    await InvocationClaimRepository().reserve(
        {
            "id": claim_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "execution_id": execution_id,
            "tool_name": tool_name,
            "claimed_at": now.isoformat(),
        }
    )
    started = datetime.now(timezone.utc)
    result: dict[str, Any] = {}
    error: dict[str, Any] | None = None
    status = "succeeded"
    tool_call_attempted = False
    try:
        init = await send_public_request(
            "POST",
            url,
            max_redirects=0,
            json={
                "jsonrpc": "2.0",
                "id": f"{execution_id}:initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "aether-agent-runtime", "version": "1"},
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        if init.status_code < 200 or init.status_code >= 300:
            raise RuntimeError(f"provider_initialize_http_{init.status_code}")
        init_payload = init.json()
        if (
            not isinstance(init_payload, dict)
            or init_payload.get("id") != f"{execution_id}:initialize"
            or not isinstance((init_payload.get("result") or {}).get("protocolVersion"), str)
        ):
            raise RuntimeError("provider_initialize_invalid")
        protocol_version = init_payload["result"]["protocolVersion"]
        session = init.headers.get("mcp-session-id")
        init_headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        init_headers["MCP-Protocol-Version"] = protocol_version
        if session:
            init_headers["mcp-session-id"] = session
        initialized = await send_public_request(
            "POST",
            url,
            max_redirects=0,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=init_headers,
        )
        if initialized.status_code < 200 or initialized.status_code >= 300:
            raise RuntimeError(f"provider_initialized_http_{initialized.status_code}")
        current_grant = await grants.find_by_id(grant.get("delegation_id", grant.get("id")))
        if not current_grant or any(
            current_grant.get(key) != grant.get(key)
            for key in (
                "tenant_id",
                "grantee_entity_id",
                "authorization_kind",
                "scope",
                "starts_at",
                "ends_at",
                "revoked_at",
            )
        ):
            raise ForbiddenError("Capability grant changed before invocation")
        decision = await engine.evaluate(
            grantee_entity_id=agent_id,
            action="invoke",
            resource=policy_resource,
            tenant_id=tenant_id,
        )
        started = datetime.now(timezone.utc)
        if (
            not decision.allowed
            or decision.delegation_id != grant.get("delegation_id", grant.get("id"))
            or decision.matched_scope != grant.get("scope")
            or started < parse_instant_strict(grant["starts_at"])
            or (grant.get("ends_at") and started >= parse_instant_strict(grant["ends_at"]))
        ):
            raise ForbiddenError("Capability grant is not effective at invocation")
        tool_call_attempted = True
        response = await send_public_request(
            "POST",
            url,
            max_redirects=0,
            json={
                "jsonrpc": "2.0",
                "id": execution_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            headers=init_headers,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"provider_http_{response.status_code}")
        if len(response.content) > 1_000_000:
            raise RuntimeError("provider_response_too_large")
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or payload.get("jsonrpc") != "2.0"
            or payload.get("id") != execution_id
        ):
            raise RuntimeError("provider_response_invalid")
        if payload.get("error") is not None:
            raise RuntimeError("provider_tool_error")
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            raise RuntimeError("provider_result_invalid")
    except Exception as exc:  # completion of the real provider attempt is the evidence point
        status = "failed"
        error = {"code": str(exc)[:256], "type": type(exc).__name__}
    ended = datetime.now(timezone.utc)
    from actions.agent.runtime_repository import sanitize_payload

    result_json = (
        json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
        if status == "succeeded"
        else None
    )
    result_digest = (
        __import__("hashlib").sha256(result_json.encode()).hexdigest() if result_json else None
    )
    safe_result = sanitize_payload(result) if status == "succeeded" else None
    safe_result_json = json.dumps(safe_result, default=str) if safe_result is not None else ""
    result_complete = bool(status == "succeeded" and len(safe_result_json) <= 64_000)
    receipt = {
        "receipt_id": claim_id,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "execution_id": execution_id,
        "workflow_run_id": workflow_run_id,
        "workflow_definition_link": workflow_definition_link,
        "tool_name": tool_name,
        "capability_id": cap_id,
        "resource": resource,
        "policy_resource": policy_resource,
        "provider": target.get("provider"),
        "provider_url": url,
        "server_key": server_key,
        "initiating_principal_user_id": initiating_principal_user_id,
        "policy_decision": decision.to_dict(),
        "grant_scope": dict(grant.get("scope") or {}),
        "grant_id": grant.get("delegation_id", grant.get("id")),
        "grant_starts_at": grant["starts_at"],
        "grant_ends_at": grant.get("ends_at"),
        "invoked_at": started.isoformat(),
        "completed_at": ended.isoformat(),
        "result_status": status,
        "tool_call_attempted": tool_call_attempted,
        "provider_result": safe_result if result_complete else None,
        "provider_result_digest": result_digest,
        "provider_result_complete": result_complete,
        "provider_error": error,
        "arguments_digest": __import__("hashlib")
        .sha256(json.dumps(arguments, sort_keys=True, default=str).encode())
        .hexdigest(),
        "evidence_version": 1,
        "agent_policy_version": config.get("policy_version"),
        "action": "invoke",
    }
    return await receipts.record_once(receipt)


async def read_observed_mcp_resource(
    *, tenant_id: str, agent_id: str, execution_id: str, resource_uri: str,
    config: dict[str, Any], engine: DelegationEngine,
    initiating_principal_user_id: str, workflow_run_id: str | None = None,
    workflow_definition_link: dict[str, Any] | None = None,
    grants: CapabilityAuthorizationRepository | None = None,
    catalog: CapabilityCatalogRepository | None = None,
    receipts: InvocationReceiptRepository | None = None,
) -> dict[str, Any]:
    """Read one exact observed MCP resource under a dedicated resource-read grant."""
    if any(not _exact_identifier(value) for value in
           (tenant_id, agent_id, execution_id, resource_uri, initiating_principal_user_id)):
        raise ForbiddenError("Exact authenticated resource-read scope is required")
    if resource_uri not in (config.get("resource_uris") or []):
        raise ForbiddenError("Resource URI is not enabled by agent policy")
    catalog, grants, receipts = catalog or CapabilityCatalogRepository(), grants or CapabilityAuthorizationRepository(), receipts or InvocationReceiptRepository()
    rows = await catalog.list_capabilities(tenant_id, limit=1001)
    if len(rows) > 1000:
        raise ForbiddenError("Observed MCP resource inventory is truncated")
    matches = [row for row in rows if row.get("tenant_id") == tenant_id
               and row.get("capability_kind") == "resource" and row.get("resource_uri") == resource_uri
               and row.get("capability_id") == resource_id_for(
                   tenant_id, row.get("provider"), row.get("server_name") or row.get("server_url"), resource_uri)]
    if len(matches) != 1:
        raise ForbiddenError("Exact observed MCP resource is unavailable or ambiguous")
    target = matches[0]
    server_key = target.get("server_name") or target.get("server_url")
    url = target.get("server_url")
    resource = f"{MCP_RESOURCE_PREFIX}{target['capability_id']}"
    now = datetime.now(timezone.utc)
    grant_rows = await grants.find_many(filters={"tenant_id": tenant_id, "grantee_entity_id": agent_id,
        "authorization_kind": "capability"}, limit=2001)
    if len(grant_rows) > 2000:
        raise ForbiddenError("Capability grant evidence is truncated")
    qualifying = []
    for grant in grant_rows:
        scope = grant.get("scope") if isinstance(grant.get("scope"), dict) else {}
        try:
            start = parse_instant_strict(grant.get("starts_at"))
            end = parse_instant_strict(grant["ends_at"]) if grant.get("ends_at") else None
        except (TypeError, ValueError):
            continue
        if (grant.get("tenant_id") == tenant_id and grant.get("grantee_entity_id") == agent_id
            and grant.get("authorization_kind") == "capability" and grant.get("revoked_at") is None
            and scope == {"actions": [RESOURCE_READ_ACTION], "resources": [resource]}
            and start <= now and (end is None or now < end)):
            qualifying.append(grant)
    if len(qualifying) != 1:
        raise ForbiddenError("One exact active resource-read grant is required")
    grant = qualifying[0]
    decision = await engine.evaluate(grantee_entity_id=agent_id, action=RESOURCE_READ_ACTION,
                                     resource=resource, tenant_id=tenant_id)
    if not decision.allowed or decision.delegation_id != grant.get("delegation_id", grant.get("id")):
        raise ForbiddenError("Resource-read policy denied or did not match the exact grant")
    if not _public_mcp_url(url):
        raise ForbiddenError("Only public HTTPS MCP endpoints are supported")
    from governance.security.policy_engine import evaluate_destination_safety
    unsafe, _ = await evaluate_destination_safety(url)
    if unsafe:
        raise ForbiddenError("Only public HTTPS MCP endpoints are supported")
    claim_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
        f"aether:mcp-resource-read:{tenant_id}:{agent_id}:{execution_id}:{target['capability_id']}"))
    await InvocationClaimRepository().reserve({"id": claim_id, "tenant_id": tenant_id, "agent_id": agent_id,
        "execution_id": execution_id, "resource_id": target["capability_id"], "claimed_at": now.isoformat()})
    started = datetime.now(timezone.utc)
    payload: dict[str, Any] | None = None
    status, error = "succeeded", None
    resource_read_attempted = False
    try:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        init_id = f"{execution_id}:initialize"
        init = await send_public_request("POST", url, max_redirects=0, json={"jsonrpc":"2.0", "id":init_id,
            "method":"initialize", "params":{"protocolVersion":"2025-03-26", "capabilities":{},
            "clientInfo":{"name":"aether-agent-runtime", "version":"1"}}}, headers=headers)
        if init.status_code < 200 or init.status_code >= 300:
            raise RuntimeError("provider_initialize_failed")
        init_body = init.json()
        if not isinstance(init_body, dict) or init_body.get("id") != init_id or not isinstance((init_body.get("result") or {}).get("protocolVersion"), str):
            raise RuntimeError("provider_initialize_invalid")
        headers["MCP-Protocol-Version"] = init_body["result"]["protocolVersion"]
        session = init.headers.get("mcp-session-id")
        if session: headers["mcp-session-id"] = session
        ack = await send_public_request("POST", url, max_redirects=0,
            json={"jsonrpc":"2.0", "method":"notifications/initialized"}, headers=headers)
        if ack.status_code < 200 or ack.status_code >= 300: raise RuntimeError("provider_initialize_ack_failed")
        list_id = f"{execution_id}:resources-list"
        listing = await send_public_request("POST", url, max_redirects=0,
            json={"jsonrpc":"2.0", "id":list_id, "method":"resources/list", "params":{}}, headers=headers)
        if listing.status_code < 200 or listing.status_code >= 300 or len(listing.content) > 1_000_000:
            raise RuntimeError("provider_resource_list_failed")
        listing_body = listing.json()
        listed = (listing_body.get("result") or {}).get("resources") if isinstance(listing_body, dict) else None
        if (not isinstance(listing_body, dict) or listing_body.get("jsonrpc") != "2.0"
            or listing_body.get("id") != list_id or listing_body.get("error") is not None
            or not isinstance(listed, list) or not all(isinstance(item, dict) for item in listed)
            or sum(item.get("uri") == resource_uri for item in listed) != 1):
            raise RuntimeError("provider_resource_not_exactly_observed")
        listing_digest = hashlib.sha256(json.dumps(listed, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        latest = await grants.find_by_id(grant.get("delegation_id", grant.get("id")))
        if latest is None or any(latest.get(key) != grant.get(key) for key in
            ("tenant_id", "grantee_entity_id", "agent_id", "authorization_kind", "scope", "starts_at", "ends_at", "revoked_at")):
            raise ForbiddenError("Resource-read grant changed before operation")
        decision = await engine.evaluate(grantee_entity_id=agent_id, action=RESOURCE_READ_ACTION, resource=resource, tenant_id=tenant_id)
        started = datetime.now(timezone.utc)
        grant_start = parse_instant_strict(grant.get("starts_at"))
        grant_end = parse_instant_strict(grant["ends_at"]) if grant.get("ends_at") else None
        decision_time = parse_instant_strict(decision.evaluated_at)
        if (not decision.allowed or decision.delegation_id != grant.get("delegation_id", grant.get("id"))
            or decision.matched_scope != grant.get("scope") or started < grant_start
            or (grant_end is not None and started >= grant_end)
            or not grant_start <= decision_time <= started):
            raise ForbiddenError("Resource-read grant is not effective at operation time")
        resource_read_attempted = True
        response = await send_public_request("POST", url, max_redirects=0,
            json={"jsonrpc":"2.0", "id":execution_id, "method":"resources/read", "params":{"uri":resource_uri}}, headers=headers)
        if response.status_code < 200 or response.status_code >= 300 or len(response.content) > 1_000_000: raise RuntimeError("provider_resource_read_failed")
        body = response.json()
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or body.get("id") != execution_id or body.get("error") is not None or not isinstance(body.get("result"), dict):
            raise RuntimeError("provider_resource_result_invalid")
        payload = body["result"]
        if not _exact_resource_contents(payload, resource_uri):
            raise RuntimeError("provider_resource_contents_mismatch")
    except Exception as exc:
        status, error = "failed", {"code": str(exc)[:256], "type": type(exc).__name__}
    ended = datetime.now(timezone.utc)
    from actions.agent.runtime_repository import sanitize_payload
    safe = sanitize_payload(payload) if status == "succeeded" else None
    encoded = json.dumps(safe, sort_keys=True, separators=(",",":"), default=str) if safe is not None else ""
    digest = __import__("hashlib").sha256(encoded.encode()).hexdigest() if safe is not None else None
    return await receipts.record_once({"id":claim_id, "receipt_id":claim_id, "tenant_id":tenant_id, "agent_id":agent_id,
        "execution_id":execution_id, "workflow_run_id":workflow_run_id, "workflow_definition_link":workflow_definition_link,
        "action":RESOURCE_READ_ACTION, "resource_operation":"read", "resource_uri":resource_uri,
        "resource_id":target["capability_id"], "resource":resource, "policy_resource":resource,
        "provider":target.get("provider"), "provider_url":url, "server_key":server_key,
        "initiating_principal_user_id":initiating_principal_user_id, "policy_decision":decision.to_dict(),
        "grant_scope":dict(grant["scope"]), "grant_id":grant.get("delegation_id", grant.get("id")),
        "grant_starts_at":grant["starts_at"], "grant_ends_at":grant.get("ends_at"),
        "invoked_at":started.isoformat(), "completed_at":ended.isoformat(), "result_status":status,
        "tool_call_attempted":False, "resource_read_attempted":resource_read_attempted, "provider_result":safe if len(encoded) <= 64000 else None,
        "provider_result_digest":digest, "provider_result_complete":bool(status == "succeeded" and len(encoded) <= 64000),
        "provider_resource_listing_digest":listing_digest if status == "succeeded" else None,
        "provider_error":error, "evidence_version":1})
