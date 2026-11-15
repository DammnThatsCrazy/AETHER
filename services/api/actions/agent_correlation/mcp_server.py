"""Aether correlation MCP server (JSON-RPC 2.0 over streamable HTTP, JSON responses).

Agent platforms that accept a custom MCP server (a Grok Team Bot, an OpenAI
Agent Builder workflow, Claude, Cursor) point at
``POST /v1/observability/agent/correlation/mcp`` with the tenant's API
credentials. The agent registers its task, carries the returned token into the
systems it touches, reports its tool calls and outcome, and can read back the
evidence-graded chain Aether reconstructed.

Every tool observes; none executes anything in a provider system.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from actions.agent_correlation.mappers import MappingError
from actions.agent_correlation.service import CorrelationService, CorrelationUnavailable, now_utc

SERVER_NAME = "aether-correlation"
SERVER_VERSION = "1"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

_PLATFORM = {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,31}$",
             "description": "Your agent platform, e.g. xai_grok, openai, anthropic, cursor, custom."}
_TOKEN = {"type": "string", "description": "The correlation_token aether_register_task returned."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "aether_register_task",
        "description": (
            "Register the task you are starting. Returns a correlation_token. Write the token into the "
            "systems you act in (payment metadata, order notes, PR bodies) so Aether can link your task "
            "to the records they keep. Call once per task, before acting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_platform": _PLATFORM,
                "agent_ref": {"type": "string", "description": "Your stable agent or bot identifier."},
                "principal_ref": {"type": "string", "description": "Who asked for the task, as you know them."},
                "description": {"type": "string", "description": "What the task is."},
            },
            "required": ["agent_platform"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aether_report_tool_call",
        "description": (
            "Report a call you made to another system for a registered task. Include the call's input and "
            "output so object IDs (a Shopify GID, a Stripe pi_ ID) can be matched to that system's records."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "correlation_token": _TOKEN,
                "agent_platform": _PLATFORM,
                "call_id": {"type": "string"},
                "tool_name": {"type": "string"},
                "input": {},
                "output": {},
                "occurred_at": {"type": "string", "description": "ISO-8601 with timezone; defaults to now."},
                "signature_nonce": {"type": "string", "description": "Nonce of your HTTP message signature, if signed."},
            },
            "required": ["correlation_token", "agent_platform", "call_id", "tool_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aether_report_outcome",
        "description": "Report what came of a registered task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "correlation_token": _TOKEN,
                "agent_platform": _PLATFORM,
                "outcome_id": {"type": "string"},
                "status": {"type": "string", "enum": ["succeeded", "failed", "partial", "cancelled"]},
                "summary": {"type": "string"},
                "evidence": {},
                "occurred_at": {"type": "string"},
            },
            "required": ["correlation_token", "agent_platform", "outcome_id", "status"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aether_get_task_chain",
        "description": (
            "Read the chain Aether reconstructed for a task: linked observations ordered in time, each link's "
            "evidence class, unproven candidates, and the gaps where nothing was observed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"task_ref": {"type": "string"}},
            "required": ["task_ref"],
            "additionalProperties": False,
        },
    },
]
_TOOL_NAMES = {t["name"] for t in TOOLS}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if isinstance(payload, dict):
        out["structuredContent"] = payload
    return out


async def _call_tool(service: CorrelationService, tenant_id: str, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    if name == "aether_register_task":
        return await service.register_task(
            tenant_id,
            agent_platform=str(args.get("agent_platform") or ""),
            agent_ref=args.get("agent_ref"),
            principal_ref=args.get("principal_ref"),
            description=args.get("description"),
        )
    if name == "aether_report_tool_call":
        record = {**args, "occurred_at": args.get("occurred_at") or now_utc().isoformat()}
        record.pop("tool_name", None)
        record["input"] = {"tool_name": args.get("tool_name"), "arguments": args.get("input")}
        return {"observations": await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", record)}
    if name == "aether_report_outcome":
        record = {**args, "occurred_at": args.get("occurred_at") or now_utc().isoformat()}
        return {"observations": await service.ingest_record(tenant_id, "aether_mcp", "outcome_reported", record)}
    if name == "aether_get_task_chain":
        chain = await service.chain_for_task(tenant_id, str(args.get("task_ref") or ""))
        return chain if chain is not None else {"error": "unknown task_ref"}
    raise KeyError(name)


async def handle_jsonrpc(service: CorrelationService, tenant_id: str, message: Any) -> Optional[dict[str, Any]]:
    """Handle one JSON-RPC message; ``None`` for a notification (no response)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "invalid request")
    method = message["method"]
    req_id = message.get("id")
    params = message.get("params") or {}
    if "id" not in message:
        return None  # notifications (e.g. notifications/initialized) need no reply
    if not isinstance(params, dict):
        return _error(req_id, -32602, "params must be an object")

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        return _result(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Register each task with aether_register_task before acting, carry the returned "
                "correlation_token into the systems you touch, and report tool calls and outcomes."
            ),
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in _TOOL_NAMES:
            return _error(req_id, -32602, f"unknown tool {name!r}")
        if not isinstance(args, dict):
            return _error(req_id, -32602, "arguments must be an object")
        try:
            return _result(req_id, _tool_result(await _call_tool(service, tenant_id, str(name), args)))
        except (MappingError, CorrelationUnavailable, ValueError) as exc:
            return _result(req_id, _tool_result(str(exc), is_error=True))
    return _error(req_id, -32601, f"method not found: {method}")
