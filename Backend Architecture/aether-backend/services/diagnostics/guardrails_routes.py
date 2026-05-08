"""
Aether Service — Diagnostics Guardrails

Operator surface over the agent-layer guardrails (Agent Layer/guardrails/).
The guardrails themselves run in-process; this router exposes:
  - Policies: configurable rules, persisted in a durable store
  - Decisions: append-only log of guardrail evaluations / violations
  - Status: a roll-up of the current configuration

Endpoints:
    GET    /v1/guardrails/policies                       List policies
    POST   /v1/guardrails/policies                       Create policy
    GET    /v1/guardrails/policies/{policy_id}           Get policy
    PATCH  /v1/guardrails/policies/{policy_id}           Update policy
    DELETE /v1/guardrails/policies/{policy_id}           Delete policy
    GET    /v1/guardrails/decisions                      Recent decisions
    POST   /v1/guardrails/decisions                      Record a decision
    GET    /v1/guardrails/status                         Roll-up summary
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.guardrails")
router = APIRouter(prefix="/v1/guardrails", tags=["Guardrails"])

_policy_store = get_store("guardrail_policies")
_decision_store = get_store("guardrail_decisions")


VALID_POLICY_KINDS = [
    "rate_limit", "pii_detector", "confidence_gate", "cost_monitor",
    "kill_switch", "policy_guard",
]
VALID_DECISION_OUTCOMES = ["allow", "deny", "warn", "throttle", "escalate"]


class PolicyCreate(BaseModel):
    kind: str = Field(..., description="One of " + "|".join(VALID_POLICY_KINDS))
    name: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class PolicyUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[dict[str, Any]] = None
    description: Optional[str] = None


class DecisionRecord(BaseModel):
    policy_id: str
    outcome: str = Field(..., description="One of " + "|".join(VALID_DECISION_OUTCOMES))
    actor_key: Optional[str] = None
    request_id: Optional[str] = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(tenant_id: str, policy_id: str) -> str:
    return f"{tenant_id}:{policy_id}"


def _decisions_key(tenant_id: str) -> str:
    return f"decisions:{tenant_id}"


@router.get("/policies")
async def list_policies(request: Request, kind: str = "", enabled: Optional[bool] = None):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    filters: dict[str, Any] = {"tenant_id": tenant.tenant_id}
    if kind:
        filters["kind"] = kind
    if enabled is not None:
        filters["enabled"] = enabled
    policies = await _policy_store.find(**filters)
    return APIResponse(data={"policies": policies, "count": len(policies)}).to_dict()


@router.post("/policies")
async def create_policy(body: PolicyCreate, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    if body.kind not in VALID_POLICY_KINDS:
        raise BadRequestError(f"Invalid kind '{body.kind}'. Valid: {VALID_POLICY_KINDS}")

    policy_id = str(uuid.uuid4())
    record = {
        "policy_id": policy_id,
        "tenant_id": tenant.tenant_id,
        "kind": body.kind,
        "name": body.name,
        "enabled": body.enabled,
        "config": body.config,
        "description": body.description,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await _policy_store.set(_key(tenant.tenant_id, policy_id), record)
    metrics.increment("guardrail_policies_created", labels={"kind": body.kind})
    return APIResponse(data=record).to_dict()


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    record = await _policy_store.get(_key(tenant.tenant_id, policy_id))
    if not record:
        raise NotFoundError(f"Policy not found: {policy_id}")
    return APIResponse(data=record).to_dict()


@router.patch("/policies/{policy_id}")
async def update_policy(policy_id: str, body: PolicyUpdate, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    record = await _policy_store.get(_key(tenant.tenant_id, policy_id))
    if not record:
        raise NotFoundError(f"Policy not found: {policy_id}")

    if body.enabled is not None:
        record["enabled"] = body.enabled
    if body.config is not None:
        record["config"] = {**record.get("config", {}), **body.config}
    if body.description is not None:
        record["description"] = body.description
    record["updated_at"] = _now()
    await _policy_store.set(_key(tenant.tenant_id, policy_id), record)
    return APIResponse(data=record).to_dict()


@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    deleted = await _policy_store.delete(_key(tenant.tenant_id, policy_id))
    if not deleted:
        raise NotFoundError(f"Policy not found: {policy_id}")
    return APIResponse(data={"policy_id": policy_id, "deleted": True}).to_dict()


@router.get("/decisions")
async def list_decisions(
    request: Request,
    policy_id: str = "",
    outcome: str = "",
    limit: int = 100,
):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    decisions = await _decision_store.get_list(_decisions_key(tenant.tenant_id), limit=limit)
    if policy_id:
        decisions = [d for d in decisions if d.get("policy_id") == policy_id]
    if outcome:
        decisions = [d for d in decisions if d.get("outcome") == outcome]
    return APIResponse(data={"decisions": decisions, "count": len(decisions)}).to_dict()


@router.post("/decisions")
async def record_decision(body: DecisionRecord, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    if body.outcome not in VALID_DECISION_OUTCOMES:
        raise BadRequestError(
            f"Invalid outcome '{body.outcome}'. Valid: {VALID_DECISION_OUTCOMES}"
        )
    if not await _policy_store.get(_key(tenant.tenant_id, body.policy_id)):
        raise NotFoundError(f"Policy not found: {body.policy_id}")

    record = body.model_dump()
    record["tenant_id"] = tenant.tenant_id
    await _decision_store.append_list(_decisions_key(tenant.tenant_id), record)
    metrics.increment("guardrail_decisions", labels={"outcome": body.outcome})
    return APIResponse(data=record).to_dict()


@router.get("/status")
async def status(request: Request):
    """Roll-up of guardrail posture for the current tenant."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    policies = await _policy_store.find(tenant_id=tenant.tenant_id)
    decisions = await _decision_store.get_list(_decisions_key(tenant.tenant_id), limit=1000)

    by_kind: dict[str, int] = {}
    enabled_by_kind: dict[str, int] = {}
    for p in policies:
        by_kind[p["kind"]] = by_kind.get(p["kind"], 0) + 1
        if p.get("enabled"):
            enabled_by_kind[p["kind"]] = enabled_by_kind.get(p["kind"], 0) + 1

    by_outcome: dict[str, int] = {}
    for d in decisions:
        by_outcome[d["outcome"]] = by_outcome.get(d["outcome"], 0) + 1

    return APIResponse(data={
        "policy_count": len(policies),
        "policies_by_kind": by_kind,
        "enabled_by_kind": enabled_by_kind,
        "decision_sample_size": len(decisions),
        "decisions_by_outcome": by_outcome,
    }).to_dict()
