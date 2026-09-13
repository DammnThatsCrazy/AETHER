"""Computation Substrate — definitions, results, runs, and explainability.

Read surfaces over the immutable computed-results store and the canonical
definition registry. Every result is self-describing (status, quality, lineage,
supersession); ``/explain`` answers "what is this number?" end to end. Frontends
may FORMAT these values but must not recompute or reinterpret them.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger

logger = get_logger("aether.computation.routes")
router = APIRouter(prefix="/v1/computations", tags=["Computation Substrate"])


def _tenant(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return tenant


@router.get("/definitions")
async def list_computation_definitions(request: Request) -> dict:
    """The active canonical computation definitions (kind, type, unit, formula
    inputs, aggregation, decision-impact class)."""
    _tenant(request)
    from shared.computation.registry import REGISTRY_VERSION, list_active

    return APIResponse(
        data={
            "registry_version": REGISTRY_VERSION,
            "definitions": [d.model_dump(mode="json") for d in list_active()],
        }
    ).to_dict()


@router.get("/definitions/{definition_id}")
async def get_computation_definition(
    request: Request, definition_id: str, version: str = Query(default="1")
) -> dict:
    """A single canonical definition at a version."""
    _tenant(request)
    from shared.computation.registry import get_definition

    definition = get_definition(definition_id, version)
    if definition is None:
        raise NotFoundError(f"definition {definition_id}@{version} not found")
    return APIResponse(data=definition.model_dump(mode="json")).to_dict()


@router.get("/results")
async def list_computation_results(
    request: Request,
    definition_id: Optional[str] = Query(default=None),
    include_superseded: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Tenant-scoped canonical results (active by default)."""
    tenant = _tenant(request)
    from services.computation.repositories import get_computation_repository

    repo = get_computation_repository()
    rows = await repo.list_for_tenant(
        tenant.tenant_id,
        definition_id=definition_id,
        include_superseded=include_superseded,
        limit=limit,
    )
    return APIResponse(data={"results": rows, "count": len(rows)}).to_dict()


@router.get("/results/{result_id}")
async def get_computation_result(request: Request, result_id: str) -> dict:
    """A single canonical result envelope."""
    tenant = _tenant(request)
    from services.computation.repositories import get_computation_repository

    row = await get_computation_repository().get(tenant.tenant_id, result_id)
    if row is None:
        raise NotFoundError(f"result {result_id} not found")
    return APIResponse(data=row).to_dict()


@router.get("/results/{result_id}/explain")
async def explain_computation_result(request: Request, result_id: str) -> dict:
    """Explain a result: what it is, how it was derived, and its trust state."""
    tenant = _tenant(request)
    from services.computation.explain import build_explain
    from services.computation.repositories import get_computation_repository

    repo = get_computation_repository()
    row = await repo.get(tenant.tenant_id, result_id)
    if row is None:
        raise NotFoundError(f"result {result_id} not found")
    chain = await repo.restatement_chain(tenant.tenant_id, result_id)
    return APIResponse(data=build_explain(row, chain=chain)).to_dict()


@router.get("/runs/{run_id}")
async def get_computation_run(request: Request, run_id: str) -> dict:
    """A single computation run (definition + context + status + timings)."""
    tenant = _tenant(request)
    from services.computation.repositories import get_computation_repository

    run = await get_computation_repository().get_run(tenant.tenant_id, run_id)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    return APIResponse(data=run).to_dict()


__all__ = ["router"]
