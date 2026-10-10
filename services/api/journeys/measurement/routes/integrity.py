"""Measurement Integrity Plane — definitions, results, and explainability.

Read surfaces over the immutable measurement-results store and the metric
registry. Every result carries a ``value_state`` (a metric is never a bare 0
when the data is missing/insufficient), lineage, sufficiency, and uncertainty;
``/explain`` also returns the restatement chain so a number can always be
traced to how it was derived and whether it was later superseded.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger

logger = get_logger("aether.measurement.routes.integrity")
router = APIRouter(prefix="/v1/measurement", tags=["Measurement Integrity"])


def _tenant(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return tenant


@router.get("/definitions")
async def get_measurement_definitions(request: Request) -> dict:
    """The registered metric definitions (name, version, unit, bounds, sample
    floor) — the contract a measurement result is validated against."""
    _tenant(request)
    from shared.measurement import REGISTRY_VERSION, list_definitions

    return APIResponse(
        data={"registry_version": REGISTRY_VERSION, "definitions": list_definitions()}
    ).to_dict()


@router.get("/results")
async def list_measurement_results(
    request: Request,
    metric_name: Optional[str] = Query(default=None),
    include_superseded: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Tenant-scoped measurement results (active by default; set
    ``include_superseded`` to see restated versions too)."""
    tenant = _tenant(request)
    from repositories.measurement_results_repo import get_measurement_results_repository

    repo = get_measurement_results_repository()
    results = await repo.list_for_tenant(
        tenant.tenant_id,
        metric_name=metric_name,
        include_superseded=include_superseded,
        limit=limit,
    )
    return APIResponse(
        data={"results": results, "count": len(results)},
        meta={"metric_name": metric_name, "include_superseded": include_superseded},
    ).to_dict()


@router.get("/results/{result_id}/explain")
async def explain_measurement_result(result_id: str, request: Request) -> dict:
    """Full derivation of a single result: value + value_state, lineage,
    sufficiency, uncertainty, and the ordered restatement chain."""
    tenant = _tenant(request)
    from repositories.measurement_results_repo import get_measurement_results_repository

    repo = get_measurement_results_repository()
    result = await repo.get(tenant.tenant_id, result_id)
    if result is None:
        raise NotFoundError("Measurement result")

    chain = await repo.restatement_chain(tenant.tenant_id, result_id)
    definition = None
    try:
        from shared.measurement import get_definition

        found = get_definition(result.get("metric_name", ""), result.get("metric_version", "1"))
        definition = found.model_dump() if found is not None else None
    except Exception as exc:  # pragma: no cover — definition lookup is advisory
        logger.debug("measurement definition lookup skipped: %s", exc)

    return APIResponse(
        data={
            "result": result,
            "value": result.get("value"),
            "value_state": result.get("value_state"),
            "lineage": result.get("lineage") or {},
            "sufficiency": result.get("sufficiency") or {},
            "uncertainty": result.get("uncertainty"),
            "definition": definition,
            "restatement_chain": chain,
            "superseded": bool(result.get("superseded_by")),
        }
    ).to_dict()
