"""Agent Access Intelligence — capability reconciliation API (PR 3).

``GET /v1/capability-reconciliation``                    missing / orphan / mismatch report.
``GET /v1/capability-reconciliation/pipeline-health``    agentic pipeline health counters.
``GET /v1/capability-reconciliation/lineage/{id}``       end-to-end lineage for one event.

Mirrors ``authority_routes.py`` / ``risk_routes.py``: read ``request.state.tenant``, call
``require_permission(...)``, scope every query by ``tenant.tenant_id``, return
``APIResponse``.

**Every route requires ``read`` and only ``read``.** Reconciliation is a derivation over
stores that already exist — it writes no row, publishes no event, and registers no event
type, so there is no ``event-registry.json`` change and no migration. Gating a *report* on
``write`` would lock out exactly the read-only governance and audit callers it is for.

The report answers ``reconciliation_known: false`` with ``null`` counts rather than a 404
or a zero when the provider side reports nothing. "0 mismatches" reads as "everything
reconciles"; see ``reconciliation_service`` for why that distinction is the point of the
endpoint.

``pipeline-health`` and ``lineage`` surface ``AgenticReconciliationService``, which had no
live caller anywhere in the product before this router. Both are wrapped, not
reimplemented, and both carry a ``verdict_basis`` disclosure stating what their numbers do
and do not mean.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.agent_access_intelligence.reconciliation_service import (
    FINDING_KINDS,
    capability_reconciliation_service,
)

logger = get_logger("aether.service.agent_access_intelligence.reconciliation_routes")

capability_reconciliation_router = APIRouter(
    prefix="/v1/capability-reconciliation",
    tags=["Agent Access Intelligence"],
)


@capability_reconciliation_router.get("")
async def read_reconciliation_report(
    request: Request,
    provider_id: Optional[str] = Query(
        default=None, description="Restrict the comparison to one provider."
    ),
    kind: Optional[str] = Query(
        default=None,
        description=f"Show only one finding kind: {' | '.join(FINDING_KINDS)}.",
    ),
    limit: int = Query(100, ge=1, le=500),
):
    """Observed capability inventory reconciled against provider-reported state.

    ``counts`` describes the whole comparison, not the returned page or the ``kind``
    filter — a filtered view must never make the other kinds read as zero. Observed
    capabilities whose provider reports no evidence at all are counted under
    ``counts.orphan_not_comparable`` and are deliberately not findings."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_reconciliation_service.report(
        tenant.tenant_id, provider_id=provider_id, kind=kind, limit=limit
    )
    metrics.increment(
        "capability_reconciliation_reports",
        labels={
            "known": "true" if data.get("reconciliation_known") else "false",
            "filtered": "true" if (provider_id or kind) else "false",
        },
    )
    return APIResponse(data=data).to_dict()


@capability_reconciliation_router.get("/pipeline-health")
async def read_pipeline_health(request: Request):
    """Agentic observability pipeline counters for this tenant.

    Wraps ``AgenticReconciliationService.pipeline_health`` verbatim under ``pipeline`` and
    adds ``verdict_basis``: its ``health`` verdict is derived from failure counters alone,
    so all-zero counts mean nothing was recorded, not that the pipeline is working."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_reconciliation_service.pipeline_health(tenant.tenant_id)
    metrics.increment(
        "capability_reconciliation_pipeline_health_reads",
        labels={"health": str((data.get("pipeline") or {}).get("health"))},
    )
    return APIResponse(data=data).to_dict()


@capability_reconciliation_router.get("/lineage/{source_event_id}")
async def read_event_lineage(source_event_id: str, request: Request):
    """Bronze → Silver → canonical lineage for one source event.

    Tenant-scoped inside the wrapped service, so an event id from another tenant returns
    an empty lineage with gaps — identical to an id that never existed, and therefore not
    an existence oracle."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_reconciliation_service.lineage(tenant.tenant_id, source_event_id)
    metrics.increment(
        "capability_reconciliation_lineage_reads",
        labels={
            "complete": "true" if (data.get("lineage") or {}).get("complete") else "false",
        },
    )
    return APIResponse(data=data).to_dict()
