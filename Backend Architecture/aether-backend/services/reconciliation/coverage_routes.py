"""Diagnostics API — tenant-level SDK dimension coverage.

Exposes the bounded tenant coverage sweep from
:mod:`services.reconciliation.coverage` as a read-only diagnostic endpoint.
The router is mounted by ``main.py`` (import
``services.reconciliation.coverage_routes.router``).

    GET /v1/diagnostics/sdk/coverage    Tenant SDK dimension coverage (census or representative sample)
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.reconciliation.coverage import DEFAULT_SAMPLE_LIMIT, compute_tenant_coverage

logger = get_logger("aether.service.diagnostics.coverage")

router = APIRouter(prefix="/v1/diagnostics", tags=["Diagnostics"])

# Hard ceiling on how many entities a single sweep may enumerate, so an
# unregistered/huge tenant (or an over-large ``?limit=``) cannot turn one
# diagnostic call into an unbounded scan.
_MAX_SAMPLE_LIMIT = 500


@router.get("/sdk/coverage")
async def get_sdk_coverage(
    request: Request,
    limit: int = Query(
        DEFAULT_SAMPLE_LIMIT,
        ge=1,
        description="Census threshold and maximum representative sample size.",
    ),
) -> dict:
    """Tenant-wide SDK dimension coverage via a census or deterministic sample.

    Tenant-scoped and read-only. Small populations use an exact census; larger
    populations use a deterministic full-frame hash sample with population,
    seed, methodology, and Wilson confidence evidence in the response.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    # Clamp defensively — never let a caller request an unbounded sweep.
    sample_limit = min(max(1, limit), _MAX_SAMPLE_LIMIT)

    result = await compute_tenant_coverage(
        tenant.tenant_id, sample_limit=sample_limit
    )

    metrics.increment("diagnostics_sdk_coverage")
    return APIResponse(data=result).to_dict()
