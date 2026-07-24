"""Agent Access Intelligence — capability risk API (PR 2, Phase C, monoprompt §9.5).

``/v1/capability-risk/findings``       scan findings + declared-vs-observed identity drift.
``/v1/capability-risk/blast-radius``   bounded exposure for one agent or one capability.

Mirrors ``authority_routes.py``: read ``request.state.tenant``, call
``require_permission(...)``, scope every query by ``tenant.tenant_id``, return
``APIResponse``. Both routes require ``read`` and only ``read`` — they compute over
existing stores, write no row, and publish no event, so there is no new event type and
no ``event-registry.json`` change.

``blast-radius`` reports ``exposure_known: false`` with ``null`` counts rather than a
404 or a zero when the inputs it needs were never observed. See ``risk_service`` for why
that distinction is the whole point of the endpoint.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.agent_access_intelligence.risk_service import capability_risk_service

logger = get_logger("aether.service.agent_access_intelligence.risk_routes")

capability_risk_router = APIRouter(
    prefix="/v1/capability-risk",
    tags=["Agent Access Intelligence"],
)


@capability_risk_router.get("/findings")
async def list_risk_findings(
    request: Request,
    code: Optional[str] = Query(
        default=None,
        description="Filter to a single finding code (case-insensitive).",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Risk findings for the tenant's observed capabilities.

    ``counts`` summarizes every matching finding, not just the returned page — a
    page-scoped total would understate risk for exactly the tenants that have the most
    of it. Undeclared capabilities are counted under ``identity.observed_only`` and are
    deliberately not findings."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_risk_service.findings(
        tenant.tenant_id, code=code, limit=limit, offset=offset
    )
    metrics.increment(
        "capability_risk_findings_listed",
        labels={"filtered": "true" if code else "false"},
    )
    return APIResponse(data=data).to_dict()


@capability_risk_router.get("/blast-radius")
async def read_blast_radius(
    request: Request,
    agent_id: Optional[str] = Query(
        default=None, description="What this agent has been observed reaching."
    ),
    capability_id: Optional[str] = Query(
        default=None, description="Which agents have been observed reaching this capability."
    ),
):
    """Observed exposure for exactly one of ``agent_id`` / ``capability_id``.

    When an input is missing the response carries ``exposure_known: false``, ``null``
    counts and a ``missing_inputs`` list. It never reports unknown exposure as zero."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_risk_service.blast_radius(
        tenant.tenant_id, agent_id=agent_id, capability_id=capability_id
    )
    metrics.increment(
        "capability_blast_radius_reads",
        labels={
            "subject": str(data.get("subject", {}).get("kind")),
            "exposure_known": "true" if data.get("exposure_known") else "false",
        },
    )
    return APIResponse(data=data).to_dict()
