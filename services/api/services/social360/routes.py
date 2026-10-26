"""Authenticated write routes for exact Social360 evidence assertions.

Read composition remains inside Social360/Risk360 providers so policy and
redaction continue to be applied by the 360 frame runtime.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from governance.security.request_context import tenant_actor
from shared.auth.auth import Permissions

from .evidence_authority import (
    SocialContagionEvidenceInput,
    SocialEvidenceAuthority,
    SocialEvidenceAuthorityError,
    SocialEvidenceConflict,
    SocialTrustEdgeInput,
)

router = APIRouter(prefix="/v1/social360/evidence", tags=["Social360 Evidence"])


class SocialTrustEdgeBody(BaseModel):
    """Operator assertion fields; tenant, actor, and source namespace are server-set."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_observation_id: str = Field(min_length=1, max_length=512)
    source_revision_id: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    source_entity_id: str = Field(min_length=1, max_length=512)
    target_entity_id: str = Field(min_length=1, max_length=512)
    observed_at: datetime
    effective_at: datetime
    risk_signal_ids: list[str] = Field(default_factory=list, max_length=100)
    assertion_note: str = Field(min_length=1, max_length=1000)

    @field_validator("observed_at", "effective_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value


class SocialContagionEvidenceBody(SocialContagionEvidenceInput):
    """Source evidence envelope without caller-controlled tenant or actor."""


@router.post("/trust-edges", status_code=201)
async def record_trust_edge(body: SocialTrustEdgeBody, request: Request) -> dict:
    tenant = request.state.tenant
    tenant.require_permission(Permissions.ADMIN)
    actor = tenant_actor(request)
    event = SocialTrustEdgeInput(
        source_id=f"aether.operator:{actor.actor_id}",
        source_observation_id=body.source_observation_id,
        source_revision_id=body.source_revision_id,
        source_event_id=body.source_event_id,
        source_entity_id=body.source_entity_id,
        target_entity_id=body.target_entity_id,
        observed_at=body.observed_at,
        effective_at=body.effective_at,
        risk_signal_ids=body.risk_signal_ids,
        assertion_note=body.assertion_note,
    )
    try:
        row = await SocialEvidenceAuthority().record_trust_edge(
            actor.tenant_id,
            event,
            actor_id=actor.actor_id,
            actor_type=str(actor.actor_type),
        )
    except SocialEvidenceConflict as exc:
        raise HTTPException(status_code=409, detail="social evidence event conflicts with an existing event") from exc
    except SocialEvidenceAuthorityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "record_id": row["record_id"],
        "assertion_kind": row["assertion_kind"],
        "subject_entity_id": row["subject_entity_id"],
        "assertion_state": row["assertion_state"],
    }


@router.post("/contagion", status_code=201)
async def record_social_contagion_evidence(
    body: SocialContagionEvidenceBody, request: Request
) -> dict:
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    actor = tenant_actor(request)
    try:
        row = await SocialEvidenceAuthority().record_social_contagion_evidence(
            actor.tenant_id,
            SocialContagionEvidenceInput.model_validate(body.model_dump()),
            actor_id=actor.actor_id,
            actor_type=str(actor.actor_type),
        )
    except SocialEvidenceConflict as exc:
        raise HTTPException(status_code=409, detail="social evidence event conflicts with an existing event") from exc
    except SocialEvidenceAuthorityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "record_id": row["record_id"],
        "assertion_kind": row["assertion_kind"],
        "subject_entity_id": row["subject_entity_id"],
        "claim_state": row.get("claim_state"),
        "causal_status": row.get("causal_status"),
    }


__all__ = ["router"]
