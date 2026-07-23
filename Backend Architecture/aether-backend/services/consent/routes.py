"""
Aether Service — Consent
GDPR consent records, data subject requests (DSR), and audit logs.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from services.consent.authority import record_consent_receipt_envelope
from services.consent.control_plane import CanonicalConsentReceiptInput
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
_CONSENT_PURPOSES = {
    str(item.get("key"))
    for item in _CONSENT_REGISTRY.get("purposes", [])
    if item.get("key")
}


class ConsentRecord(BaseModel):
    user_id: Optional[str] = None
    subject_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    purposes: list[str] = Field(
        default_factory=list,
        description="e.g. analytics, marketing, personalization",
    )
    granted: bool = True
    source: str = Field(default="sdk", description="How consent was collected")
    snapshot_id: Optional[str] = Field(default=None, description="Opaque snapshot ID for this consent state")
    mode: Optional[Literal["opt_in", "opt_out", "jurisdiction_managed"]] = Field(default=None)
    jurisdiction: Optional[str] = Field(default=None, description="e.g. GDPR, CCPA, LGPD")
    gpc_observed: Optional[bool] = Field(default=None, description="Global Privacy Control signal")
    dnt_observed: Optional[bool] = Field(default=None, description="Do Not Track signal")
    idempotency_key: Optional[str] = None
    canonical_receipt: Optional[CanonicalConsentReceiptInput] = None


_CANONICAL_HASH_FIELDS = (
    "tenant_id",
    "subject_id",
    "anonymous_id",
    "purposes",
    "state",
    "source",
    "provider",
    "policy_version",
    "jurisdiction_context",
    "mode",
    "lawful_basis",
    "granted_at",
    "denied_at",
    "revoked_at",
    "expires_at",
    "gpc_observed",
    "dnt_observed",
    "provider_consent_id",
    "metadata",
)


def _canonical_hash_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "\x1f".join(sorted({str(item) for item in value}))
    if isinstance(value, dict):
        if not value:
            return ""
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return str(value)


def _canonical_receipt_hash(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(b"aether-consent-receipt/v1\n")
    for field in _CANONICAL_HASH_FIELDS:
        value = _canonical_hash_value(payload.get(field))
        value_bytes = value.encode("utf-8")
        digest.update(f"{field}={len(value_bytes)}:".encode("utf-8"))
        digest.update(value_bytes)
        digest.update(b"\n")
    return digest.hexdigest()


def _canonical_integrity_hash(payload: dict[str, Any]) -> str:
    return f"sha256:{_canonical_receipt_hash(payload)}"


def _canonical_receipt_id(hex_digest: str) -> str:
    return f"ccr_{hex_digest[:32]}"


def _canonical_idempotency_key(hex_digest: str) -> str:
    return f"consent-receipt:{hex_digest}"


def _normalize_receipt(
    body: ConsentRecord,
    *,
    tenant_id: str,
    effective_mode: Optional[str],
) -> CanonicalConsentReceiptInput:
    canonical = body.canonical_receipt
    if canonical is not None:
        if canonical.tenant_id != tenant_id:
            raise BadRequestError(
                "canonical_receipt.tenant_id must match the authenticated tenant"
            )
        if body.user_id and canonical.subject_id not in (None, body.user_id):
            raise BadRequestError(
                "canonical_receipt.subject_id conflicts with legacy user_id"
            )
        receipt = canonical
    else:
        subject_id = body.subject_id or body.user_id
        if not subject_id and not body.anonymous_id:
            raise BadRequestError(
                "user_id, subject_id, or anonymous_id is required"
            )
        if not body.purposes:
            raise BadRequestError("at least one consent purpose is required")
        now = utc_now().isoformat()
        state = "granted" if body.granted else "denied"
        hash_payload = {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "anonymous_id": body.anonymous_id,
            "purposes": sorted(set(body.purposes)),
            "state": state,
            "source": body.source,
            "provider": None,
            "policy_version": _CONSENT_REGISTRY.get(
                "contractVersion",
                _CONSENT_REGISTRY.get("schemaVersion", "unknown"),
            ),
            "jurisdiction_context": body.jurisdiction,
            "mode": effective_mode,
            "lawful_basis": None,
            "granted_at": now if body.granted else None,
            "denied_at": None if body.granted else now,
            "revoked_at": None,
            "expires_at": None,
            "gpc_observed": body.gpc_observed,
            "dnt_observed": body.dnt_observed,
            "provider_consent_id": None,
            "metadata": {},
        }
        digest = _canonical_receipt_hash(hash_payload)
        receipt = CanonicalConsentReceiptInput(
            **hash_payload,
            receipt_id=_canonical_receipt_id(digest),
            integrity_hash=f"sha256:{digest}",
            idempotency_key=_canonical_idempotency_key(digest),
        )

    if not receipt.subject_id and not receipt.anonymous_id:
        raise BadRequestError(
            "canonical receipt requires subject_id or anonymous_id"
        )
    unknown = set(receipt.purposes) - _CONSENT_PURPOSES
    if unknown:
        raise BadRequestError(
            f"Unknown consent purpose(s): {', '.join(sorted(unknown))}"
        )
    if not receipt.integrity_hash.strip():
        raise BadRequestError("canonical_receipt.integrity_hash is required")
    if not receipt.idempotency_key.strip():
        raise BadRequestError("canonical_receipt.idempotency_key is required")
    receipt_payload = receipt.model_dump(
        exclude={"receipt_id", "integrity_hash", "idempotency_key"}
    )
    expected_hex = _canonical_receipt_hash(receipt_payload)
    expected_integrity_hash = f"sha256:{expected_hex}"
    if receipt.integrity_hash != expected_integrity_hash:
        raise BadRequestError("canonical_receipt.integrity_hash is invalid")
    expected_receipt_id = _canonical_receipt_id(expected_hex)
    if receipt.receipt_id != expected_receipt_id:
        raise BadRequestError("canonical_receipt.receipt_id is invalid")
    expected_idempotency_key = _canonical_idempotency_key(expected_hex)
    if receipt.idempotency_key != expected_idempotency_key:
        raise BadRequestError("canonical_receipt.idempotency_key is invalid")
    return receipt


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
    """Record legacy consent plus the authoritative per-purpose receipt rows."""
    tenant = request.state.tenant

    # gdprMode backward-compat: map to mode field
    effective_mode = body.mode
    if gdprMode is not None and effective_mode is None:
        effective_mode = "opt_in" if gdprMode else "opt_out"

    receipt = _normalize_receipt(
        body,
        tenant_id=tenant.tenant_id,
        effective_mode=effective_mode,
    )
    legacy_record_id = "consent_record_" + hashlib.sha256(
        f"{tenant.tenant_id}\0{receipt.idempotency_key}".encode("utf-8")
    ).hexdigest()
    existing = await _repo.find_by_id(legacy_record_id)
    if existing is not None:
        existing_receipt = existing.get("canonical_receipt") or {}
        if (
            existing_receipt.get("integrity_hash")
            and existing_receipt.get("integrity_hash") != receipt.integrity_hash
        ):
            raise BadRequestError(
                "idempotency_key was already used for different consent evidence"
            )
        return APIResponse(data=existing).to_dict()

    authoritative_rows = await record_consent_receipt_envelope(receipt)
    record = await _repo.insert(legacy_record_id, {
        "tenant_id": tenant.tenant_id,
        "user_id": receipt.subject_id or body.user_id,
        "subject_id": receipt.subject_id,
        "anonymous_id": receipt.anonymous_id,
        "purposes": receipt.purposes,
        "granted": receipt.state == "granted",
        "state": receipt.state,
        "source": receipt.source,
        "snapshot_id": body.snapshot_id or receipt.receipt_id,
        "mode": receipt.mode or effective_mode,
        "jurisdiction": receipt.jurisdiction_context,
        "gpc_observed": receipt.gpc_observed,
        "dnt_observed": receipt.dnt_observed,
        "idempotency_key": receipt.idempotency_key,
        "canonical_receipt": receipt.model_dump(),
        "authoritative_receipt_ids": [row["id"] for row in authoritative_rows],
        "recorded_at": utc_now().isoformat(),
    })

    await producer.publish(Event(
        topic=Topic.CONSENT_UPDATED,
        tenant_id=tenant.tenant_id,
        source_service="consent",
        payload={
            "user_id": receipt.subject_id,
            "anonymous_id": receipt.anonymous_id,
            "granted": receipt.state == "granted",
            "state": receipt.state,
            "purposes": receipt.purposes,
            "receipt_id": receipt.receipt_id,
        },
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
    import asyncio
    from services.measurement.privacy import handle_erasure_background

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

    if body.request_type == "erasure":
        asyncio.create_task(
            handle_erasure_background(tenant.tenant_id, body.user_id)
        )

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
