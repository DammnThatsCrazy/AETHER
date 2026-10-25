"""Authenticated tenant ingress for provider-observed support case lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from governance.security.request_context import tenant_actor
from shared.auth.auth import Permissions
from shared.common.common import APIResponse
from journeys.support360.cases import (
    SupportCaseAuthorityError,
    SupportCaseEventInput,
    SupportCaseEventType,
    SupportCaseIngestionService,
    SupportCaseNotFound,
    SupportCaseTransitionError,
)
from journeys.support360.callbacks import (
    SupportCallbackAuthorityError,
    SupportCallbackEventInput,
    SupportCallbackEventType,
    SupportCallbackIngestionService,
    SupportCallbackNotFound,
    SupportCallbackTransitionError,
)
from journeys.support360.assignments import (
    SupportAgentAssignmentAuthorityError,
    SupportAgentAssignmentEventInput,
    SupportAgentAssignmentEventType,
    SupportAgentAssignmentIngestionService,
    SupportAgentAssignmentNotFound,
)
from journeys.support360.context_authorities import (
    SupportCaseContextAuthorityError,
    SupportCaseContextIngestionService,
    SupportCaseContextNotFound,
    SupportJourneyLinkEventInput,
    SupportSLAEventInput,
)

router = APIRouter(prefix="/v1/support/cases", tags=["Support Cases"])


class SupportCaseIngestBody(BaseModel):
    """Minimal allow-listed case event input; content and arbitrary payloads are barred."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    connection_id: str = Field(min_length=1, max_length=256)
    source_case_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    event_type: SupportCaseEventType
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class SupportCallbackIngestBody(BaseModel):
    """Minimal callback schedule/execution event input without raw payloads."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    connection_id: str = Field(min_length=1, max_length=256)
    case_id: str = Field(min_length=1, max_length=64)
    source_callback_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    event_type: SupportCallbackEventType
    occurred_at: datetime
    scheduled_for: datetime | None = None

    @field_validator("occurred_at", "scheduled_for")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("callback timestamps must include a timezone")
        return value


class SupportAgentAssignmentIngestBody(BaseModel):
    """Allow-listed assignment revision without tenant or actor claims."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    connection_id: str = Field(min_length=1, max_length=256)
    source_assignment_id: str = Field(min_length=1, max_length=256)
    source_revision_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    event_type: SupportAgentAssignmentEventType
    agent_entity_id: str | None = Field(default=None, max_length=256)
    previous_agent_entity_id: str | None = Field(default=None, max_length=256)
    source_observed_at: datetime
    effective_at: datetime

    @field_validator("source_observed_at", "effective_at")
    @classmethod
    def _require_assignment_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("assignment timestamps must include a timezone")
        return value


class SupportContextIngestBody(BaseModel):
    """Typed context event envelope without tenant or actor claims."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    connection_id: str = Field(min_length=1, max_length=256)
    event: SupportSLAEventInput | SupportJourneyLinkEventInput


@router.post("/ingest")
async def ingest_support_case_event(request: Request, body: SupportCaseIngestBody) -> dict[str, Any]:
    """Accept one tenant-authorized, verified-connection case event.

    Lifecycle fields remain observed source assertions and the exact source
    event ID is retained for idempotent replay. The request has no arbitrary
    metadata, title, description, or message-body field.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    event = SupportCaseEventInput(
        source_case_id=body.source_case_id,
        source_event_id=body.source_event_id,
        event_type=body.event_type,
        occurred_at=body.occurred_at,
    )
    try:
        record = await SupportCaseIngestionService().ingest(
            tenant.tenant_id,
            body.connection_id,
            event,
        )
    except SupportCaseNotFound as exc:
        raise HTTPException(status_code=409, detail="support case must be created before updates") from exc
    except SupportCaseTransitionError as exc:
        raise HTTPException(status_code=409, detail="support case lifecycle transition is invalid") from exc
    except SupportCaseAuthorityError as exc:
        raise HTTPException(status_code=403, detail="verified tenant provider connection is required") from exc
    return APIResponse(
        data={
            "accepted": True,
            "case_id": record["case_id"],
            "lifecycle_state": record["lifecycle_state"],
            "claim_state": "observed",
            "last_observed_at": record["last_observed_at"],
            "retention_expires_at": record["retention_expires_at"],
        }
    ).to_dict()


@router.post("/callbacks/ingest")
async def ingest_support_callback_event(
    request: Request, body: SupportCallbackIngestBody
) -> dict[str, Any]:
    """Accept one typed callback event for the exact tenant-owned support case.

    The connection and case must belong to the same verified provider. Callback
    IDs remain scoped source identifiers; the authority creates the canonical ID.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    event = SupportCallbackEventInput(
        case_id=body.case_id,
        source_callback_id=body.source_callback_id,
        source_event_id=body.source_event_id,
        event_type=body.event_type,
        occurred_at=body.occurred_at,
        scheduled_for=body.scheduled_for,
    )
    try:
        record = await SupportCallbackIngestionService().ingest(
            tenant.tenant_id,
            body.connection_id,
            event,
        )
    except SupportCallbackNotFound as exc:
        raise HTTPException(status_code=409, detail="support callback must be scheduled before updates") from exc
    except SupportCallbackTransitionError as exc:
        raise HTTPException(status_code=409, detail="support callback transition is invalid") from exc
    except SupportCallbackAuthorityError as exc:
        raise HTTPException(status_code=403, detail="verified tenant case/provider binding is required") from exc
    return APIResponse(
        data={
            "accepted": True,
            "callback_id": record["callback_id"],
            "case_id": record["case_id"],
            "callback_state": record["callback_state"],
            "scheduled_for": record["scheduled_for"],
            "last_observed_at": record["last_observed_at"],
            "retention_expires_at": record["retention_expires_at"],
        }
    ).to_dict()


@router.post("/{case_id}/assignments/ingest")
async def ingest_support_agent_assignment_event(
    case_id: str,
    request: Request,
    body: SupportAgentAssignmentIngestBody,
) -> dict[str, Any]:
    """Record one authenticated, source-observed assignment or handoff event.

    Tenant and assigning-principal IDs are taken only from authenticated request
    context. The named agent IDs are accepted only after exact canonical entity
    resolution within that tenant and do not imply an execution or outcome.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    actor = tenant_actor(request)
    if actor.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=403, detail="authenticated support principal is unavailable")
    event = SupportAgentAssignmentEventInput(
        case_id=case_id,
        source_assignment_id=body.source_assignment_id,
        source_revision_id=body.source_revision_id,
        source_event_id=body.source_event_id,
        event_type=body.event_type,
        agent_entity_id=body.agent_entity_id,
        previous_agent_entity_id=body.previous_agent_entity_id,
        source_observed_at=body.source_observed_at,
        effective_at=body.effective_at,
    )
    try:
        record = await SupportAgentAssignmentIngestionService().ingest(
            tenant.tenant_id,
            body.connection_id,
            event,
            assigning_principal_id=actor.actor_id,
            assigning_principal_type=str(actor.actor_type),
        )
    except SupportAgentAssignmentNotFound as exc:
        raise HTTPException(status_code=409, detail="exact tenant-owned support case is unavailable") from exc
    except SupportAgentAssignmentAuthorityError as exc:
        raise HTTPException(
            status_code=403,
            detail="verified provider connection and canonical tenant-owned agent are required",
        ) from exc
    return APIResponse(
        data={
            "accepted": True,
            "assignment_event_id": record["assignment_event_id"],
            "case_id": record["case_id"],
            "source_assignment_id": record["source_assignment_id"],
            "source_revision_id": record["source_revision_id"],
            "event_type": record["event_type"],
            "agent_entity_id": record.get("agent_entity_id"),
            "previous_agent_entity_id": record.get("previous_agent_entity_id"),
            "source_observed_at": record["source_observed_at"],
            "effective_at": record["effective_at"],
            "received_at": record["received_at"],
        }
    ).to_dict()


async def _ingest_support_case_context(
    *,
    kind: str,
    case_id: str,
    request: Request,
    body: SupportContextIngestBody,
) -> dict[str, Any]:
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    actor = tenant_actor(request)
    if actor.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=403, detail="authenticated support principal is unavailable")
    if body.event.case_id != case_id:
        raise HTTPException(status_code=422, detail="event case_id must match the canonical route case")
    try:
        record = await SupportCaseContextIngestionService().ingest(
            kind,
            tenant.tenant_id,
            body.connection_id,
            body.event,
            actor_id=actor.actor_id,
            actor_type=str(actor.actor_type),
        )
    except SupportCaseContextNotFound as exc:
        raise HTTPException(status_code=409, detail="exact tenant-owned support case is unavailable") from exc
    except SupportCaseContextAuthorityError as exc:
        raise HTTPException(
            status_code=403,
            detail="verified provider scope and canonical reference are required",
        ) from exc
    return APIResponse(
        data={
            "accepted": True,
            "context_event_id": record["context_event_id"],
            "case_id": record["case_id"],
            "context_kind": record["context_kind"],
            "event_type": record["event_type"],
            "source_event_id": record["source_event_id"],
            "source_observed_at": record["source_observed_at"],
            "effective_at": record["effective_at"],
            "received_at": record["received_at"],
        }
    ).to_dict()


@router.post("/{case_id}/sla/ingest")
async def ingest_support_case_sla_event(
    case_id: str,
    request: Request,
    body: SupportContextIngestBody,
) -> dict[str, Any]:
    if not isinstance(body.event, SupportSLAEventInput):
        raise HTTPException(status_code=422, detail="SLA event contract is required")
    return await _ingest_support_case_context(
        kind="sla", case_id=case_id, request=request, body=body
    )


@router.post("/{case_id}/journey-links/ingest")
async def ingest_support_case_journey_link_event(
    case_id: str,
    request: Request,
    body: SupportContextIngestBody,
) -> dict[str, Any]:
    if not isinstance(body.event, SupportJourneyLinkEventInput):
        raise HTTPException(status_code=422, detail="journey link event contract is required")
    return await _ingest_support_case_context(
        kind="journey_links", case_id=case_id, request=request, body=body
    )


__all__ = ["router"]
