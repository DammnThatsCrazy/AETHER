"""Propagation & Diffusion lens API (flag-gated, tenant-scoped, read-only).

``POST /v1/social360/propagation/runs`` computes one bounded propagation run
over the caller's own tenant and returns the ``PropagationRun`` contract. It
never writes graph truth and never reads another tenant's data. Disabled unless
``AETHER_PROPAGATION_LENS_ENABLED`` is on.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.auth.auth import Permissions
from shared.common.common import APIResponse, BadRequestError, ServiceUnavailableError

router = APIRouter(prefix="/v1/social360/propagation", tags=["Propagation & Diffusion"])


class PropagationRunRequest(BaseModel):
    window_start: str
    window_end: str
    instrument_keys: list[str] = Field(default_factory=list, max_length=200)
    channels: Optional[list[str]] = None
    exposure_window_seconds: int = Field(default=72 * 3600, ge=60, le=30 * 24 * 3600)
    max_hops: int = Field(default=4, ge=1, le=16)
    include_live: bool = Field(default=False, description="Bounded live read of public-wallet venues")


def _require_enabled() -> None:
    from config.settings import settings

    if not settings.social360.propagation_lens_enabled:
        raise ServiceUnavailableError("Propagation lens is disabled")


def _require_permissions(request: Request) -> str:
    tenant = request.state.tenant
    if hasattr(tenant, "require_permission"):
        tenant.require_permission(Permissions.ANALYTICS)
        tenant.require_permission(Permissions.DERIVATIVES_READ)
    return tenant.tenant_id


@router.post("/runs")
async def create_propagation_run(body: PropagationRunRequest, request: Request) -> dict:
    from intelligence.propagation.contracts import ExposureChannel, PropagationQuery
    from intelligence.propagation.service import PropagationService

    _require_enabled()
    tenant_id = _require_permissions(request)
    try:
        channels = (
            tuple(ExposureChannel(c) for c in body.channels) if body.channels else tuple(ExposureChannel)
        )
        query = PropagationQuery(
            tenant_id=tenant_id,
            window_start=body.window_start,
            window_end=body.window_end,
            instrument_keys=tuple(body.instrument_keys),
            channels=channels,
            exposure_window_seconds=body.exposure_window_seconds,
            max_hops=body.max_hops,
        )
        result = await PropagationService().run(query, include_live=body.include_live)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return APIResponse(data=result.to_dict()).to_dict()
