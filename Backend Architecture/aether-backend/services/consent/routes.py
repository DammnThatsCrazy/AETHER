"""
Aether Service — Consent
GDPR consent records, data subject requests (DSR), and audit logs.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, utc_now
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_producer
from repositories.repos import ConsentRepository

logger = get_logger("aether.service.consent")
router = APIRouter(prefix="/v1/consent", tags=["Consent"])

_repo = ConsentRepository()
DSR_TYPES = ["access", "rectification", "erasure", "portability", "restriction", "objection"]

_REGISTRY_PATH = pathlib.Path(__file__).resolve().parents[4] / "packages" / "shared" / "contracts" / "consent-registry.json"

def _load_registry() -> dict:
    try:
        return json.loads(_REGISTRY_PATH.read_text())
    except Exception:
        return {}

_CONSENT_REGISTRY: dict = _load_registry()


class ConsentRecord(BaseModel):
    user_id: str
    purposes: list[str] = Field(..., description="e.g. analytics, marketing, personalization")
    granted: bool = True
    source: str = Field(default="sdk", description="How consent was collected")
    snapshot_id: Optional[str] = Field(default=None, description="Opaque snapshot ID for this consent state")
    mode: Optional[Literal["opt_in", "opt_out", "jurisdiction_managed"]] = Field(default=None)
    jurisdiction: Optional[str] = Field(default=None, description="e.g. GDPR, CCPA, LGPD")
    gpc_observed: Optional[bool] = Field(default=None, description="Global Privacy Control signal")
    dnt_observed: Optional[bool] = Field(default=None, description="Do Not Track signal")


class DataSubjectRequest(BaseModel):
    user_id: str
    request_type: str = Field(..., description="access, rectification, erasure, portability, restriction, objection")
    details: str = ""


@router.post("/records")
async def record_consent(
    body: ConsentRecord,
    request: Request,
    producer: EventProducer = Depends(get_producer),
    gdprMode: Optional[bool] = None,
):
    """Record a user's consent preferences."""
    tenant = request.state.tenant

    # gdprMode backward-compat: map to mode field
    effective_mode = body.mode
    if gdprMode is not None and effective_mode is None:
        effective_mode = "opt_in" if gdprMode else "opt_out"

    record = await _repo.insert(str(uuid.uuid4()), {
        "tenant_id": tenant.tenant_id,
        "user_id": body.user_id,
        "purposes": body.purposes,
        "granted": body.granted,
        "source": body.source,
        "snapshot_id": body.snapshot_id,
        "mode": effective_mode,
        "jurisdiction": body.jurisdiction,
        "gpc_observed": body.gpc_observed,
        "dnt_observed": body.dnt_observed,
        "recorded_at": utc_now().isoformat(),
    })

    await producer.publish(Event(
        topic=Topic.CONSENT_UPDATED,
        tenant_id=tenant.tenant_id,
        source_service="consent",
        payload={"user_id": body.user_id, "granted": body.granted, "purposes": body.purposes},
    ))

    return APIResponse(data=record).to_dict()


@router.get("/records/{user_id}")
async def get_consent(user_id: str, request: Request):
    """Get current consent status for a user."""
    tenant = request.state.tenant
    record = await _repo.get_consent(tenant.tenant_id, user_id)
    return APIResponse(data=record or {"user_id": user_id, "consent": None}).to_dict()


@router.post("/dsr")
async def submit_dsr(
    body: DataSubjectRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Submit a GDPR data subject request."""
    tenant = request.state.tenant
    tenant.require_permission("consent:manage")

    if body.request_type not in DSR_TYPES:
        raise BadRequestError(f"Invalid DSR type. Allowed: {DSR_TYPES}")

    dsr_id = str(uuid.uuid4())
    dsr = await _repo.insert(f"dsr_{dsr_id}", {
        "tenant_id": tenant.tenant_id,
        "dsr_id": dsr_id,
        "user_id": body.user_id,
        "request_type": body.request_type,
        "details": body.details,
        "status": "pending",
        "submitted_at": utc_now().isoformat(),
        "deadline": None,
    })

    await producer.publish(Event(
        topic=Topic.DATA_SUBJECT_REQUEST,
        tenant_id=tenant.tenant_id,
        source_service="consent",
        payload={"dsr_id": dsr_id, "type": body.request_type, "user_id": body.user_id},
    ))

    return APIResponse(data=dsr).to_dict()


@router.get("/dsr")
async def list_dsrs(request: Request, status: Optional[str] = None):
    """List all data subject requests for the tenant."""
    tenant = request.state.tenant
    tenant.require_permission("consent:manage")
    filters: dict = {"tenant_id": tenant.tenant_id}
    if status:
        filters["status"] = status
    dsrs = await _repo.find_many(filters=filters)
    return APIResponse(data=dsrs).to_dict()


@router.get("/retention-manifest")
async def retention_manifest(request: Request):
    """Return per-purpose retention windows, DSR scopes, and opt-in requirements from the consent registry."""
    request.state.tenant  # validates auth
    purposes = _CONSENT_REGISTRY.get("purposes", [])
    manifest = [
        {
            "key": p.get("key"),
            "label": p.get("label"),
            "retentionDays": p.get("retentionDays"),
            "dsrDeleteScope": p.get("dsrDeleteScope", []),
            "dsrDeleteNote": p.get("dsrDeleteNote"),
            "explicitOptInRequired": p.get("explicitOptInRequired", False),
            "revocationBehavior": p.get("revocationBehavior"),
        }
        for p in purposes
    ]
    return APIResponse(data={"purposes": manifest, "schema_version": _CONSENT_REGISTRY.get("schemaVersion")}).to_dict()
