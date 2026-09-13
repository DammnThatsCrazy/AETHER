"""Agent Access Intelligence — capability alerts + export API (PR 4).

``/v1/capability-alerts/evaluate``  apply the default alert rule set to current findings.
``/v1/capability-alerts/export``    bounded export of one access-intelligence dataset.

Mirrors ``authority_routes.py`` / ``risk_routes.py``: read ``request.state.tenant``, call
``require_permission(...)``, scope every query by ``tenant.tenant_id``, return
``APIResponse``.

Both routes require ``read`` and only ``read``. ``evaluate`` is a *report* — it derives
over stores that already exist, writes no row, publishes no event, and blocks nothing, so
there is no new event type and no ``event-registry.json`` change. Gating a report on
``write`` would stop exactly the read-only reviewers who need it, and would imply the
endpoint changes something. It does not.

Neither route sends a notification. The rule set is an Aether default, not a control any
policy source in this repo defines; paging an operator off an invented threshold is the
fabricated-control failure ``services/security/policy_engine.py`` documents at length.
Delivery, if a tenant wants it, belongs behind a rule set the tenant authored.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.agent_access_intelligence.alerts import (
    EXPORT_DATASETS,
    capability_alert_service,
)

logger = get_logger("aether.service.agent_access_intelligence.alert_routes")

capability_alerts_router = APIRouter(
    prefix="/v1/capability-alerts",
    tags=["Agent Access Intelligence"],
)


@capability_alerts_router.get("/evaluate")
async def evaluate_capability_alerts(
    request: Request,
    limit: int = Query(
        500,
        ge=1,
        le=1000,
        description="Bounds every read this evaluation makes. Hitting it is disclosed, "
                    "never silently absorbed.",
    ),
):
    """Triggered alerts, with the rule and observed value that produced each one.

    The whole rule set — including rules that did not fire — travels in the response
    with ``is_default: true``, so no threshold is ever presented as enforced policy.

    When any rule could not be decided (a truncated or unavailable input), the response
    carries ``alerts_known: false``, names the rules in ``undecidable_rules``, and every
    count in ``counts`` is ``null``. It never reports unknown as "0 alerts": zero reads
    as all-clear, and a partial window does not entitle anyone to say it. Alerts that did
    fire are still listed — incompleteness suppresses the totals, not the evidence."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_alert_service.evaluate(tenant.tenant_id, limit=limit)
    metrics.increment(
        "capability_alerts_evaluated",
        labels={
            "known": "true" if data["alerts_known"] else "false",
            "triggered": "true" if data["alerts"] else "false",
        },
    )
    return APIResponse(data=data).to_dict()


@capability_alerts_router.get("/export")
async def export_access_intelligence(
    request: Request,
    dataset: str = Query(
        ...,
        description=f"Dataset to export. One of: {list(EXPORT_DATASETS)}.",
    ),
    limit: int = Query(1000, ge=1, le=5000),
):
    """A bounded export of one access-intelligence dataset.

    Every response states its own completeness: ``truncated``, the ``limit`` applied, the
    ``row_count`` returned, the ``reasons`` it stopped, and a plain-language
    ``statement``. A truncated export that says nothing is worse than no export — a
    consumer treats a short file as the whole inventory."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_alert_service.export(
        tenant.tenant_id, dataset=dataset, limit=limit
    )
    metrics.increment(
        "capability_access_intelligence_exported",
        labels={
            "dataset": data["dataset"],
            "truncated": "true" if data["truncated"] else "false",
        },
    )
    return APIResponse(data=data).to_dict()
