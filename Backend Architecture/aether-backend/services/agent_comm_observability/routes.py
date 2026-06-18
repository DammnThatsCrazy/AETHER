"""
Agent Communication Observability Routes.

INVARIANT: These routes never send emails, manage inboxes, or reply to messages.
They observe and record agent communication from external providers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Literal, Optional

from repositories.agentic_observability_repos import (
    AgentInboxRepository, AgentMessageRepository,
    AgentAttachmentRepository, ExtractedEntityRepository,
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


class AttachmentObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    message_obs_id: Optional[str] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    observed_at: Optional[str] = None


class ExtractionObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    message_obs_id: Optional[str] = None
    attachment_obs_id: Optional[str] = None
    entity_type: str = "other"
    confidence: Optional[float] = None
    observed_at: Optional[str] = None


class CommObsResponse(BaseModel):
    observation_id: str
    received_at: str
    graph_mutations_queued: int = 0
    tenant_id: str


@router.post("/v1/observability/agent-comm/inboxes", response_model=CommObsResponse, status_code=201)
async def observe_agent_inbox(req: InboxObsRequest) -> CommObsResponse:
    """Observe an agent inbox from an external communication provider."""
    obs_id = _new_id()
    record = AgentInboxObservedRecord(
        inbox_obs_id=obs_id,
        agent_id=req.agent_id,
        provider=req.provider,
        email_address=req.email_address,
        custom_domain=req.custom_domain,
        tenant_id=req.tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = AgentInboxRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_inbox_mutations(req.tenant_id, obs_id, req.agent_id)
    return CommObsResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/agent-comm/messages", response_model=CommObsResponse, status_code=201)
async def observe_agent_message(req: MessageObsRequest) -> CommObsResponse:
    """Observe an agent message (inbound or outbound, as observed by AETHER)."""
    if req.raw_provider_payload:
        record = normalize_agentmail_message(req.raw_provider_payload, req.tenant_id)
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
            tenant_id=req.tenant_id,
            observed_at=req.observed_at or _utc_now(),
        )
    repo = AgentMessageRepository()
    await repo.insert(record.message_obs_id, record.model_dump(mode="json"))
    mutations = build_message_mutations(req.tenant_id, record.message_obs_id, req.thread_obs_id)
    return CommObsResponse(
        observation_id=record.message_obs_id, received_at=_utc_now(),
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/agent-comm/attachments", response_model=CommObsResponse, status_code=201)
async def observe_agent_attachment(req: AttachmentObsRequest) -> CommObsResponse:
    """Observe an agent message attachment."""
    obs_id = _new_id()
    record = AgentAttachmentObservedRecord(
        attachment_obs_id=obs_id,
        message_obs_id=req.message_obs_id,
        filename=req.filename,
        mime_type=req.mime_type,
        size_bytes=req.size_bytes,
        tenant_id=req.tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = AgentAttachmentRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    return CommObsResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=0, tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/agent-comm/extractions", response_model=CommObsResponse, status_code=201)
async def observe_agent_extraction(req: ExtractionObsRequest) -> CommObsResponse:
    """Observe an entity extracted from an agent message or attachment."""
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
        tenant_id=req.tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = ExtractedEntityRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_extraction_mutations(req.tenant_id, obs_id, req.message_obs_id)
    return CommObsResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.get("/v1/admin/kyber/agentic-observability/inboxes")
async def kyber_inboxes_overview() -> dict:
    """Kyber operator: agent inbox observability overview."""
    return {"status": "ok", "inboxes": []}
