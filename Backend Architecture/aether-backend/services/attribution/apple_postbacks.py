"""Apple AdAttributionKit / SKAdNetwork postback ingestion.

Apple postbacks are CAMPAIGN-LEVEL, PLATFORM-VERIFIED aggregate evidence.
They are explicitly SEPARATE from user-level deterministic acquisition
evidence: ingesting a postback never creates a touchpoint, never resolves a
user or install to a campaign, and never upgrades a Direct / Unknown install.
Rows are stored with proof_level "platform_verified" as campaign-level
measurement input only.

Signature honesty: Apple postbacks carry a P-256 attribution signature that
can only be verified against Apple's published per-version public keys. This
repository has no such verification utility, so signature handling here is
STRUCTURAL only and signature_status records the truth:

    "unverified" — a signature field is present but was not cryptographically
                   verified (no in-repo Apple key verification utility)
    "missing"    — the postback carried no signature field

No row is ever marked verified without real verification.

Route (registered in main.py like every other service router):
    POST /v1/attribution/apple-postbacks

Parsing is version-tolerant across AdAttributionKit (kebab-case) and older
SKAdNetwork payload spellings; idempotency is keyed on the postback /
transaction identifier so Apple's redelivery retries never double-store.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from repositories.repos import get_pool
from shared.auth.auth import Role, TenantContext
from shared.decorators import require_api_key

logger = logging.getLogger("aether.attribution.apple_postbacks")

router = APIRouter(prefix="/v1/attribution", tags=["apple-postbacks"])

PROOF_LEVEL = "platform_verified"

SIGNATURE_STATUS_UNVERIFIED = "unverified"
SIGNATURE_STATUS_MISSING = "missing"

_LOCAL_APPLE_POSTBACKS: dict[str, dict[str, Any]] = {}


async def _pool() -> Any:
    return await get_pool()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _first(payload: dict[str, Any], *keys: str) -> Any:
    """Version-tolerant field access across kebab-case / camelCase spellings."""

    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:255] or None


class MalformedPostbackError(ValueError):
    """Raised when a payload cannot be reduced to a storable postback."""


def reduce_postback(payload: Any) -> dict[str, Any]:
    """Reduce a raw postback JSON body to the stored row shape.

    Tolerates AdAttributionKit and SKAdNetwork 3/4 spellings; rejects payloads
    that lack any idempotency identifier or any campaign/source identity.
    """

    if not isinstance(payload, dict) or not payload:
        raise MalformedPostbackError("postback body must be a non-empty JSON object")

    idempotency_key = _as_str(
        _first(
            payload,
            "postback-id",
            "postbackId",
            "transaction-id",
            "transactionId",
            "attribution-report-id",
        )
    )
    if idempotency_key is None:
        raise MalformedPostbackError(
            "postback is missing an idempotency identifier "
            "(postback-id / transaction-id)"
        )

    campaign_identity = {
        "ad_network_id": _as_str(_first(payload, "ad-network-id", "adNetworkId")),
        # AdAttributionKit source-identifier supersedes SKAdNetwork campaign-id;
        # both spellings are accepted and stored under both names.
        "source_identifier": _as_str(
            _first(payload, "source-identifier", "sourceIdentifier", "campaign-id", "campaignId")
        ),
        "source_app_id": _as_str(_first(payload, "source-app-id", "sourceAppId")),
        "source_domain": _as_str(_first(payload, "source-domain", "sourceDomain")),
        "app_id": _as_str(_first(payload, "app-id", "appId")),
    }
    if not campaign_identity["ad_network_id"] and not campaign_identity["source_identifier"]:
        raise MalformedPostbackError(
            "postback is missing campaign identity (ad-network-id / source-identifier)"
        )

    environment = _as_str(
        _first(payload, "postback-environment", "environment")
    ) or "production"
    if environment not in {"production", "sandbox"}:
        environment = "production"

    signature = _first(
        payload, "attribution-signature", "attributionSignature", "signature"
    )
    signature_present = isinstance(signature, str) and len(signature.strip()) > 0
    signature_status = (
        SIGNATURE_STATUS_UNVERIFIED if signature_present else SIGNATURE_STATUS_MISSING
    )

    reduced_payload = {
        **campaign_identity,
        "version": _as_str(_first(payload, "version", "postback-version")),
        "postback_sequence_index": _as_int(
            _first(payload, "postback-sequence-index", "postbackSequenceIndex")
        ),
        "did_win": _first(payload, "did-win", "didWin"),
        "redownload": payload.get("redownload"),
        "country_or_region": _as_str(
            _first(payload, "country-or-region", "countryOrRegion")
        ),
    }

    return {
        "idempotency_key": idempotency_key,
        "reduced_payload": {k: v for k, v in reduced_payload.items() if v is not None},
        "coarse_conversion_value": _as_str(
            _first(payload, "coarse-conversion-value", "coarseConversionValue")
        ),
        "fine_conversion_value": _as_int(
            _first(payload, "fine-conversion-value", "conversion-value", "conversionValue")
        ),
        "environment": environment,
        "signature_status": signature_status,
        "proof_level": PROOF_LEVEL,
    }


class ApplePostbackRepository:
    """Idempotent, tenant-scoped storage of reduced Apple postback rows.

    Durable SQL (``apple_attribution_postbacks``, migration
    20260803_deferred_attribution) with the standard in-memory fallback when
    no pool is configured (local/test).
    """

    async def store(self, tenant_id: str, reduced: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(tenant_id).strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        now = _now()
        row = {
            "apple_postback_id": str(uuid4()),
            "tenant_id": tenant_id,
            "idempotency_key": reduced["idempotency_key"],
            "reduced_payload": reduced["reduced_payload"],
            "coarse_conversion_value": reduced["coarse_conversion_value"],
            "fine_conversion_value": reduced["fine_conversion_value"],
            "environment": reduced["environment"],
            "signature_status": reduced["signature_status"],
            "proof_level": reduced["proof_level"],
            "received_at": now,
        }

        pool = await _pool()
        if pool is None:
            local_key = f"{tenant_id}::{reduced['idempotency_key']}"
            existing = _LOCAL_APPLE_POSTBACKS.get(local_key)
            if existing is not None:
                return {**self._public(existing), "duplicate": True}
            _LOCAL_APPLE_POSTBACKS[local_key] = row
            return {**self._public(row), "duplicate": False}

        inserted = await pool.fetchrow(
            """
            INSERT INTO apple_attribution_postbacks (
                apple_postback_id, tenant_id, idempotency_key, reduced_payload,
                coarse_conversion_value, fine_conversion_value, environment,
                signature_status, proof_level, received_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            RETURNING *
            """,
            row["apple_postback_id"],
            tenant_id,
            row["idempotency_key"],
            json.dumps(row["reduced_payload"]),
            row["coarse_conversion_value"],
            row["fine_conversion_value"],
            row["environment"],
            row["signature_status"],
            row["proof_level"],
            now,
        )
        if inserted is None:
            existing_row = await pool.fetchrow(
                """
                SELECT * FROM apple_attribution_postbacks
                WHERE tenant_id = $1 AND idempotency_key = $2
                """,
                tenant_id,
                row["idempotency_key"],
            )
            return {**self._public(dict(existing_row)), "duplicate": True}
        return {**self._public(dict(inserted)), "duplicate": False}

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("reduced_payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        return {
            "apple_postback_id": str(row["apple_postback_id"]),
            "idempotency_key": row["idempotency_key"],
            "reduced_payload": payload or {},
            "coarse_conversion_value": row.get("coarse_conversion_value"),
            "fine_conversion_value": row.get("fine_conversion_value"),
            "environment": row.get("environment"),
            "signature_status": row.get("signature_status"),
            "proof_level": row.get("proof_level"),
            "received_at": (
                row["received_at"].isoformat()
                if isinstance(row.get("received_at"), datetime)
                else row.get("received_at")
            ),
        }


_repository = ApplePostbackRepository()


def reset_apple_postbacks_for_tests() -> None:
    """Clear only the local fallback; never mutates the database."""

    _LOCAL_APPLE_POSTBACKS.clear()


# =============================================================================
# RBAC — mirrors the _require_* pattern in services/traffic/routes.py.
# Postbacks arrive via the tenant's own forwarding endpoint or a service
# integration, so a write-capable credential is required.
# =============================================================================

def _postback_access_allowed(tenant: TenantContext, permission: str) -> bool:
    if tenant.role in {Role.ADMIN, Role.EDITOR, Role.SERVICE}:
        return True
    return tenant.has_permission(permission)


async def _require_apple_postback_write(
    tenant: TenantContext = Depends(require_api_key),
) -> TenantContext:
    if not _postback_access_allowed(tenant, "apple_postbacks:write"):
        raise HTTPException(status_code=403, detail="Apple-postback write access required")
    return tenant


class ApplePostbackRequest(BaseModel):
    """Raw postback body as forwarded from the tenant's postback endpoint."""

    postback: dict[str, Any] = Field(default_factory=dict)


@router.post("/apple-postbacks", status_code=201)
async def ingest_apple_postback(
    body: ApplePostbackRequest,
    tenant: TenantContext = Depends(_require_apple_postback_write),
) -> dict[str, Any]:
    """Ingest one AdAttributionKit/SKAdNetwork-style postback.

    Campaign-level platform evidence only: no touchpoint is created and no
    user-level attribution is derived. Redelivered postbacks (same
    postback/transaction id) are acknowledged as duplicates, not re-stored.
    """

    try:
        reduced = reduce_postback(body.postback)
    except MalformedPostbackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stored = await _repository.store(tenant.tenant_id, reduced)
    logger.info(
        "Apple postback %s tenant=%s duplicate=%s signature=%s",
        stored["idempotency_key"],
        tenant.tenant_id,
        stored["duplicate"],
        stored["signature_status"],
    )
    return {"postback": stored}
