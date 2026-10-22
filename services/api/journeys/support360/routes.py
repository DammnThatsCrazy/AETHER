"""Authenticated tenant ingress for provider-observed support case lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


__all__ = ["router"]
