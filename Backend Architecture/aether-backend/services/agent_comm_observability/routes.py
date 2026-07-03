"""
Agent Communication Observability Routes.

INVARIANT: These routes never send emails, manage inboxes, or reply to messages.
They observe and record agent communication from external providers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Literal, Optional

from repositories.agentic_observability_repos import (
    AgentInboxRepository, AgentMessageRepository,
    AgentAttachmentRepository, ExtractedEntityRepository,
)
from services.agentic_observability.foundation import (
    active_tenant_id as _tenant_id,
    check_no_execution as _check_no_execution,
    persist_mutations as _persist_mutations,
    require_permission as _require_perm,
    validate_payload_tenant,
)
from services.agent_comm_observability.graph_mutations import (
    build_inbox_mutations, build_message_mutations, build_extraction_mutations,
)
from services.agent_comm_observability.inbox_models import AgentInboxObservedRecord
from services.agent_comm_observability.message_models import AgentMessageObservedRecord, AgentAttachmentObservedRecord
from services.agent_comm_observability.extraction_models import ExtractedEntityObservedRecord, ExtractedEntityType
from services.agent_comm_observability.provider_events import normalize_agentmail_message

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class InboxObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    agent_id: Optional[str] = None
    provider: str = "unknown"
    email_address: Optional[str] = None
    custom_domain: Optional[str] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class MessageObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    thread_obs_id: Optional[str] = None
    inbox_obs_id: Optional[str] = None
    direction: str = "inbound"
    from_address: Optional[str] = None
    to_addresses: list[str] = Field(default_factory=list)
    subject: Optional[str] = None
    has_attachments: bool = False
    raw_provider_payload: Optional[dict] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class AttachmentObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    message_obs_id: Optional[str] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class ExtractionObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    message_obs_id: Optional[str] = None
    attachment_obs_id: Optional[str] = None
    entity_type: str = "other"
    confidence: Optional[float] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class CommObsResponse(BaseModel):
    observation_id: str
    received_at: str
    graph_mutations_queued: int = 0
    tenant_id: str


@router.post("/v1/observability/agent-comm/inboxes", response_model=CommObsResponse, status_code=201)
async def observe_agent_inbox(req: InboxObsRequest, request: Request) -> CommObsResponse:
    """Observe an agent inbox from an external communication provider."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = AgentInboxObservedRecord(
        inbox_obs_id=obs_id,
        agent_id=req.agent_id,
        provider=req.provider,
        email_address=req.email_address,
        custom_domain=req.custom_domain,
        tenant_id=tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = AgentInboxRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_inbox_mutations(tenant_id, obs_id, req.agent_id)
    projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=obs_id)
    return CommObsResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=projection.graph_mutations_persisted, tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent-comm/messages", response_model=CommObsResponse, status_code=201)
async def observe_agent_message(req: MessageObsRequest, request: Request) -> CommObsResponse:
    """Observe an agent message (inbound or outbound, as observed by AETHER)."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    if req.raw_provider_payload:
        record = normalize_agentmail_message(req.raw_provider_payload, tenant_id)
    else:
        obs_id = _new_id()
        record = AgentMessageObservedRecord(
            message_obs_id=obs_id,
            thread_obs_id=req.thread_obs_id,
            inbox_obs_id=req.inbox_obs_id,
            direction=req.direction,
            from_address=req.from_address,
            to_addresses=req.to_addresses,
            subject=req.subject,
            has_attachments=req.has_attachments,
            tenant_id=tenant_id,
            observed_at=req.observed_at or _utc_now(),
        )
    repo = AgentMessageRepository()
    await repo.insert(record.message_obs_id, record.model_dump(mode="json"))
    # Use record.thread_obs_id so provider-normalized messages link correctly
    mutations = build_message_mutations(tenant_id, record.message_obs_id, record.thread_obs_id)
    projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=record.message_obs_id)
    return CommObsResponse(
        observation_id=record.message_obs_id, received_at=_utc_now(),
        graph_mutations_queued=projection.graph_mutations_persisted, tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent-comm/attachments", response_model=CommObsResponse, status_code=201)
async def observe_agent_attachment(req: AttachmentObsRequest, request: Request) -> CommObsResponse:
    """Observe an agent message attachment."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = AgentAttachmentObservedRecord(
        attachment_obs_id=obs_id,
        message_obs_id=req.message_obs_id,
        filename=req.filename,
        mime_type=req.mime_type,
        size_bytes=req.size_bytes,
        tenant_id=tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = AgentAttachmentRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    return CommObsResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=0, tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent-comm/extractions", response_model=CommObsResponse, status_code=201)
async def observe_agent_extraction(req: ExtractionObsRequest, request: Request) -> CommObsResponse:
    """Observe an entity extracted from an agent message or attachment."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    try:
        etype = ExtractedEntityType(req.entity_type)
    except ValueError:
        etype = ExtractedEntityType.OTHER
    record = ExtractedEntityObservedRecord(
        entity_obs_id=obs_id,
        message_obs_id=req.message_obs_id,
        attachment_obs_id=req.attachment_obs_id,
        entity_type=etype,
        confidence=req.confidence,
        tenant_id=tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = ExtractedEntityRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_extraction_mutations(tenant_id, obs_id, req.message_obs_id)
    projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=obs_id)
    return CommObsResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=projection.graph_mutations_persisted, tenant_id=tenant_id,
    )


@router.get("/v1/admin/kyber/agentic-observability/inboxes")
async def kyber_inboxes_overview(request: Request) -> dict:
    """Kyber operator: agent inbox observability overview."""
    _require_perm(request, "admin")
    repo = AgentInboxRepository()
    items = await repo.find_many(limit=100)
    return {"status": "ok", "inboxes": items, "count": len(items)}
