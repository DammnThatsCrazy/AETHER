"""Staging-only authenticated identity continuity evidence capture endpoint."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from shared.common.common import APIResponse, utc_now
from identity.identity.staging_capture import capture_staging_identity_state
from identity.identity.hashing import hash_value
from identity.identity.scenario_evidence import (
    IdentityScenarioEvidenceRepository,
    ScenarioExecutionRequest,
)

router = APIRouter(prefix="/v1/admin/identity", tags=["Identity Staging Proof"])


def _staging_deployment_id() -> str:
    deployment_id = os.getenv("AETHER_DEPLOYMENT_ID", "").strip()
    if not deployment_id or len(deployment_id) > 128 or any(char in deployment_id for char in "\r\n\x00"):
        raise HTTPException(status_code=503, detail="staging deployment identity is not configured")
    return deployment_id


@router.post("/staging-proof-scenarios")
async def record_staging_identity_scenario(
    body: ScenarioExecutionRequest, request: Request
) -> dict:
    """Record an explicit runner result without creating or inferring outcomes."""
    from config.settings import settings

    if settings.env.value != "staging":
        raise HTTPException(status_code=404, detail="staging proof capture is unavailable")
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise HTTPException(status_code=401, detail="authenticated tenant context required")
    tenant.require_permission("admin")
    deployment_id = _staging_deployment_id()
    if not getattr(tenant, "tenant_id", None):
        raise HTTPException(status_code=401, detail="authenticated tenant context required")

    now = datetime.now(timezone.utc)
    if (now - body.started_at).total_seconds() > 24 * 60 * 60:
        raise HTTPException(status_code=422, detail="scenario result is outside the accepted execution window")
    actor_id = str(getattr(tenant, "entity_id", "") or "authenticated-admin")
    actor_ref = hash_value(actor_id, scope=f"staging-scenario-actor:{tenant.tenant_id}")
    repository = IdentityScenarioEvidenceRepository()
    try:
        row = await repository.record(
            tenant_id=tenant.tenant_id,
            deployment_id=deployment_id,
            execution_id=body.execution_id.lower(),
            scenario_id=body.scenario_id,
            outcome=body.outcome,
            evidence_sha256=body.evidence_sha256,
            assertions_passed=body.assertions_passed,
            assertions_failed=body.assertions_failed,
            started_at=body.started_at,
            actor_ref=actor_ref,
        )
    except ValueError as error:
        status = 409 if "immutable" in str(error) else 422
        raise HTTPException(status_code=status, detail=str(error)) from None
    except Exception:
        raise HTTPException(status_code=503, detail="scenario evidence could not be durably recorded") from None
    return APIResponse(data={
        "execution_ref": hash_value(
            f"{tenant.tenant_id}:{deployment_id}:{row['execution_id']}",
            scope="staging-identity-scenario-execution",
        )[:24],
        "scenario_id": row["scenario_id"],
        "outcome": row["outcome"],
        "evidence_sha256": row["evidence_sha256"],
        "assertions_passed": row["assertions_passed"],
        "assertions_failed": row["assertions_failed"],
        "executed_at": row["executed_at"].isoformat() if hasattr(row["executed_at"], "isoformat") else str(row["executed_at"]),
    }).to_dict()


@router.get("/staging-proof-capture")
async def staging_identity_proof_capture(request: Request) -> dict:
    """Read current tenant-owned persisted evidence for the proof-pack runner.

    This endpoint never executes a scenario or mutates identity state. It
    includes only explicit results previously recorded through the authenticated
    runner endpoint; missing records remain absent for downstream validation.
    """
    from config.settings import settings

    if settings.env.value != "staging":
        raise HTTPException(status_code=404, detail="staging proof capture is unavailable")
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise HTTPException(status_code=401, detail="authenticated tenant context required")
    tenant.require_permission("admin")
    deployment_id = _staging_deployment_id()

    capture = await capture_staging_identity_state(tenant.tenant_id, deployment_id=deployment_id)
    return APIResponse(data={
        "environment": "staging",
        "deployment_id": deployment_id,
        "observed_at": utc_now().isoformat(),
        "capture": capture,
    }).to_dict()
