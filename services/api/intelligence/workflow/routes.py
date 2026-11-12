"""Authenticated tenant routes for explicit workflow definition registration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from governance.security.request_context import tenant_actor
from shared.common.common import APIResponse, NotFoundError, UnauthorizedError
from intelligence.semantic_intelligence.routes import require_read_access, require_write_access

from .definitions import (
    WorkflowDefinitionRepository,
    WorkflowDefinitionRevision,
    WorkflowStepDefinition,
    WorkflowTriggerDefinition,
)

router = APIRouter(prefix="/v1/workflows", tags=["Workflow Definitions"])


class WorkflowDefinitionRegistration(BaseModel):
    """User-supplied definition payload; tenant and actor come from auth context."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1, le=999_999_999_999)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Literal["active", "paused", "retired"] = "active"
    triggers: list[WorkflowTriggerDefinition] = Field(default_factory=list, max_length=32)
    steps: list[WorkflowStepDefinition] = Field(default_factory=list, max_length=100)
    effective_at: Optional[datetime] = None


def _authenticated_tenant_and_actor(request: Request) -> tuple[str, str]:
    actor = tenant_actor(request)
    if not actor.tenant_id:
        raise UnauthorizedError("authenticated tenant required")
    return actor.tenant_id, actor.actor_id


@router.post("/definitions")
async def register_workflow_definition(
    body: WorkflowDefinitionRegistration, request: Request
) -> dict:
    """Register one immutable revision using authenticated tenant actor data."""
    require_write_access(request)
    scoped_tenant_id, actor_ref = _authenticated_tenant_and_actor(request)
    definition = WorkflowDefinitionRevision(
        **body.model_dump(),
        tenant_id=scoped_tenant_id,
        actor_ref=actor_ref,
        created_at=datetime.now(timezone.utc),
    )
    stored = await WorkflowDefinitionRepository().register(definition)
    return APIResponse(data=stored.model_dump(mode="json")).to_dict()


@router.get("/definitions/{workflow_id}")
async def get_latest_workflow_definition(workflow_id: str, request: Request) -> dict:
    """Read only the latest exact-tenant revision for one workflow ID."""
    require_read_access(request)
    scoped_tenant_id, _actor_ref = _authenticated_tenant_and_actor(request)
    result = await WorkflowDefinitionRepository().read_latest(scoped_tenant_id, workflow_id)
    if not result.available:
        raise HTTPException(status_code=503, detail="workflow definition authority unavailable")
    if not result.complete:
        raise HTTPException(status_code=503, detail="workflow definition read incomplete")
    if not result.rows:
        raise NotFoundError("WorkflowDefinition")
    return APIResponse(data=result.rows[0]).to_dict()


__all__ = ["router"]
