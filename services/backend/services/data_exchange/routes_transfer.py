"""Data Exchange Plane — signed transfer routes (/v1/data-exchange/transfers).

M2 tenant-facing surface over ``ObjectTransferService`` (see
``docs/plans/data-exchange-api.md`` M2).  Three thin, tenant-scoped verbs:

  - ``POST /transfers/{artifact_id}/upload-url``      issue a signed PUT
  - ``POST /transfers/{artifact_id}/upload-complete`` server-side verify
  - ``GET  /transfers/{artifact_id}/download-url``    issue a signed GET

Every handler resolves ``request.state.tenant`` and re-asserts the caller holds
the relevant ``data_exchange`` grant at the envelope edge.  The router is
mounted in ``main.py`` only when ``settings.data_exchange.
signed_transfers_enabled`` is ON (the coordinator lands that include at M2
integration); availability flags switch surface availability only, never
semantics.

Grant names: the Data Exchange RBAC domain is registered by the coordinator at
M3 (``services/security/contracts.py`` ``GovernanceDomain`` + ``ROLE_SPECS`` +
``packages/shared/security-governance.ts``) from the grant list declared in
``services/data_exchange/policy.py``.  M2 reuses the declared ingress/egress
grants and additionally references two proposed transfer-scoped grants the
coordinator should register alongside them; ``admin`` is retained so an admin
role short-circuits (``TenantContext.require_any_permission`` treats the
``ADMIN`` role as holding every grant).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from services.data_exchange.authz import require_data_exchange
from services.data_exchange.transfers import get_object_transfer_service
from shared.privacy.ip_hmac import audit_ip_token

router = APIRouter(prefix="/v1/data-exchange/transfers", tags=["Data Exchange Transfers"])

# ── RBAC grants ─────────────────────────────────────────────────────────────
# Declared data_exchange grants (policy.py — now the full registered catalog
# incl. transfer.upload / transfer.download).  ``admin`` covers legacy admin
# API keys/roles; dotted grants resolve *or* their legacy parity alias via
# ``require_data_exchange`` (authz.py).

UPLOAD_REQUIRED_GRANTS: tuple[str, ...] = (
    "data_exchange.transfer.upload",
    "data_exchange.import.create",
    "admin",
)
DOWNLOAD_REQUIRED_GRANTS: tuple[str, ...] = (
    "data_exchange.transfer.download",
    "data_exchange.export.download",
    "admin",
)


def _require_tenant(request: Request, *grants: str):
    """Resolve the authenticated tenant and require any of ``grants`` (dotted
    data_exchange grant id or its legacy parity alias, via authz)."""
    tenant = request.state.tenant
    require_data_exchange(tenant, *grants)
    return tenant


class UploadCompleteBody(BaseModel):
    """Optional client-declared expectations the server-side verify checks."""

    declared_size_bytes: Optional[int] = Field(default=None, ge=0)
    declared_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)


@router.post("/{artifact_id}/upload-url")
async def upload_url(artifact_id: str, request: Request) -> dict:
    """Issue a short-TTL presigned PUT for a tenant-owned pre-upload artifact."""
    tenant = _require_tenant(request, *UPLOAD_REQUIRED_GRANTS)
    service = get_object_transfer_service()
    return await service.issue_upload_url(tenant.tenant_id, artifact_id)


@router.post("/{artifact_id}/upload-complete")
async def upload_complete(
    artifact_id: str, body: UploadCompleteBody, request: Request
) -> dict:
    """Server-side verify the signed upload, then flip the artifact to uploaded."""
    tenant = _require_tenant(request, *UPLOAD_REQUIRED_GRANTS)
    service = get_object_transfer_service()
    return await service.verify_upload_complete(
        tenant.tenant_id,
        artifact_id,
        declared_size_bytes=body.declared_size_bytes,
        declared_sha256=body.declared_sha256,
    )


@router.get("/{artifact_id}/download-url")
async def download_url(artifact_id: str, request: Request) -> dict:
    """Issue a short-TTL presigned GET for an available/committed artifact.

    Mirrors the canonical ``/v1/exports/{artifact_id}/download`` audit/event
    behavior (actor + tenant-scoped IP token, allowed-outcome ledger record,
    EXPORT_DOWNLOADED emission) for a download-URL issuance.
    """
    tenant = _require_tenant(request, *DOWNLOAD_REQUIRED_GRANTS)
    actor_id = getattr(tenant, "user_id", None) or tenant.tenant_id
    ip_token = audit_ip_token(
        request.client.host if request.client else None, tenant.tenant_id
    )
    service = get_object_transfer_service()
    return await service.issue_download_url(
        tenant.tenant_id,
        artifact_id,
        actor_id=actor_id,
        ip_address=ip_token,
    )
