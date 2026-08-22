"""LEDGER M3 -- Bronze truth-chain verification status endpoint (dashboard).

Mounted under the known ``/v1/security`` prefix (``config/route_registry.yaml``):
tamper-evidence of the Bronze ledger is a security/operator concern and the
cross-tenant "which tenants are verified / which are failing" view is operator
data. The handlers are thin -- all logic lives in
``services/integrity/chain_verifier.py`` -- and reuse the same
``request.state.tenant`` + ``require_permission`` gate the other operator/ops
routes use.

Routes:
  GET /v1/security/ledger/chain-verification
      Without ``tenant_id``: the aggregate snapshot recorded by the scheduled
      verifier worker ("tenants currently verified" / "verification failures").
      With ``?tenant_id=...``: verify that tenant's chain live, record and return
      its status.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from shared.common.common import utc_now
from services.integrity.chain_verifier import (
    get_verification_dashboard,
    record_tenant_status,
    verify_tenant_chain,
)
from services.security.request_context import require_kyber_operator

router = APIRouter(prefix="/v1/security/ledger", tags=["Ledger Integrity"])


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get(
        "X-Correlation-ID", ""
    )


def _envelope(data: object, request: Request) -> dict:
    return {
        "data": data,
        "status": "success",
        "timestamp": utc_now().isoformat(),
        "meta": {"request_id": _request_id(request)},
    }


@router.get("/chain-verification")
async def get_chain_verification(request: Request, tenant_id: Optional[str] = None):
    """Bronze truth-chain verification status for the dashboard.

    Aggregate view by default; a live per-tenant re-verification when
    ``tenant_id`` is supplied.

    This is CROSS-TENANT operator data: the aggregate exposes every tenant's id
    and integrity-failure detail, and ``?tenant_id=`` verifies (and records the
    status of) an ARBITRARY tenant's chain. A legacy ``admin`` permission is a
    tenant-scoped grant that any tenant admin holds, so it must not gate this
    surface. Require an Olympus operator -- the same ``require_kyber_operator``
    gate the Kyber security control plane uses (services/security/admin_routes.py)
    -- so no Aether tenant, even a role admin, can read or overwrite another
    tenant's verification status.
    """
    require_kyber_operator(request)
    if tenant_id:
        result = await verify_tenant_chain(tenant_id)
        await record_tenant_status(result)
        return _envelope(result.to_status(), request)
    return _envelope(await get_verification_dashboard(), request)
