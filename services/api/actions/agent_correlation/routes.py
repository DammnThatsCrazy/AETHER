"""Agent correlation routes (tenant-scoped; observation only).

* ``POST /v1/observability/agent/correlation/tasks`` — register a task, get a token.
* ``POST /v1/observability/agent/correlation/observations/{provider}/{kind}`` —
  ingest one vendor record through its mapper; returns the link decisions.
* ``PUT  /v1/observability/agent/correlation/account-bindings/{family}`` —
  declare the tenant's account for a provider family.
* ``GET  /v1/observability/agent/correlation/tasks/{task_ref}/chain`` and
  ``.../observations/{observation_id}/chain`` — the evidence-graded chain.
* ``GET  /v1/observability/agent/correlation/catalog`` — mapped providers and roles.
* ``POST /v1/observability/agent/correlation/mcp`` — the MCP endpoint for agents.
"""

from __future__ import annotations

import json
from datetime import timedelta
from functools import lru_cache
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from actions.agentic_observability.foundation import active_tenant_id, require_permission
from actions.agent_correlation.keys import CorrelationKeyError, configured_keyring
from actions.agent_correlation.mappers import MappingError, catalog
from actions.agent_correlation.mcp_server import handle_jsonrpc
from actions.agent_correlation.service import CorrelationService, CorrelationUnavailable
from config.settings import settings

PREFIX = "/v1/observability/agent/correlation"
router = APIRouter()


@lru_cache(maxsize=1)
def get_service() -> CorrelationService:
    try:
        keyring = configured_keyring()
    except CorrelationKeyError:
        # Misconfigured keys must not take the routes down; issuance reports
        # unavailable and observations still map and join on non-token keys.
        keyring = None
    window = timedelta(seconds=max(1, min(settings.agent_correlation.time_window_seconds, 3600)))
    return CorrelationService(keyring=keyring, time_window=window)


class RegisterTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_platform: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    agent_ref: Optional[str] = Field(default=None, max_length=128)
    principal_ref: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2000)


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record: dict[str, Any]
    account_bindings: Optional[dict[str, dict[str, str]]] = None


class AccountBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_account_key: str = Field(min_length=1, max_length=256)
    source_account_realm: str = Field(default="live", pattern=r"^(live|test)$")


@router.get(f"{PREFIX}/catalog")
async def correlation_catalog(request: Request) -> dict[str, Any]:
    require_permission(request, "read")
    active_tenant_id(request)
    return {"providers": catalog(), "token_issuance_available": get_service().keyring is not None}


@router.post(f"{PREFIX}/tasks", status_code=201)
async def register_task(req: RegisterTaskRequest, request: Request) -> dict[str, Any]:
    require_permission(request, "write")
    tenant_id = active_tenant_id(request)
    try:
        return await get_service().register_task(
            tenant_id,
            agent_platform=req.agent_platform,
            agent_ref=req.agent_ref,
            principal_ref=req.principal_ref,
            description=req.description,
        )
    except CorrelationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(f"{PREFIX}/observations/{{provider}}/{{kind}}", status_code=201)
async def ingest_observation(provider: str, kind: str, req: IngestRequest, request: Request) -> dict[str, Any]:
    require_permission(request, "write")
    tenant_id = active_tenant_id(request)
    if req.record.get("execution_by_aether") is True:
        raise HTTPException(status_code=422, detail="AETHER observes; it does not execute external actions.")
    try:
        results = await get_service().ingest_record(
            tenant_id, provider, kind, req.record, account_bindings=req.account_bindings
        )
    except MappingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"observations": results}


@router.put(f"{PREFIX}/account-bindings/{{family}}")
async def put_account_binding(family: str, req: AccountBindingRequest, request: Request) -> dict[str, Any]:
    require_permission(request, "write")
    tenant_id = active_tenant_id(request)
    if not family.isidentifier() or not family.islower():
        raise HTTPException(status_code=422, detail="family must be a lowercase identifier")
    await get_service().bindings.put(tenant_id, family, req.source_account_key, req.source_account_realm)
    return {"provider_family": family, "source_account_realm": req.source_account_realm}


@router.get(f"{PREFIX}/tasks/{{task_ref}}/chain")
async def task_chain(task_ref: str, request: Request) -> dict[str, Any]:
    require_permission(request, "read")
    chain = await get_service().chain_for_task(active_tenant_id(request), task_ref)
    if chain is None:
        raise HTTPException(status_code=404, detail="unknown task")
    return chain


@router.get(f"{PREFIX}/observations/{{observation_id:path}}/chain")
async def observation_chain(observation_id: str, request: Request) -> dict[str, Any]:
    require_permission(request, "read")
    chain = await get_service().chain_for_observation(active_tenant_id(request), observation_id)
    if chain is None:
        raise HTTPException(status_code=404, detail="unknown observation")
    return chain


@router.post(f"{PREFIX}/mcp")
async def mcp_endpoint(request: Request) -> Response:
    require_permission(request, "write")
    tenant_id = active_tenant_id(request)
    try:
        message = await request.json()
    except ValueError:
        return Response(
            content='{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}',
            media_type="application/json",
            status_code=400,
        )
    if isinstance(message, list):
        replies = [r for r in [await handle_jsonrpc(get_service(), tenant_id, m) for m in message[:50]] if r]
        if not replies:
            return Response(status_code=202)
        return Response(content=json.dumps(replies, default=str), media_type="application/json")
    reply = await handle_jsonrpc(get_service(), tenant_id, message)
    if reply is None:
        return Response(status_code=202)
    return Response(content=json.dumps(reply, default=str), media_type="application/json")
