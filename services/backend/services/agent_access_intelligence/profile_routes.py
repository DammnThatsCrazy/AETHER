"""Agent Access Intelligence — per-agent access profiles + journeys (PR 4).

``GET /v1/capability-profiles``                  index of agents we have observed.
``GET /v1/capability-profiles/{agent_id}``       one agent's observed access profile.
``GET /v1/capability-profiles/{agent_id}/journey`` its first-observation milestones.

Mirrors ``authority_routes.py`` / ``risk_routes.py``: read ``request.state.tenant``, call
``require_permission(...)``, scope every query by ``tenant.tenant_id``, return
``APIResponse``. All three routes require ``read`` and only ``read`` — they compute over
existing stores, write no row and publish no event, so there is no new event type and no
``event-registry.json`` change.

Two honesty properties are carried by the API surface itself and must survive any change
here:

* An agent id that was never observed returns **200 with an unknown profile**, not a 404
  and not a zero. Another tenant's agent returns the identical shape, so the path
  parameter is never an existence oracle. Raising ``NotFoundError`` for one and not the
  other would leak exactly the fact the fail-closed reads elsewhere in this package are
  built to withhold.
* ``/journey`` returns an **observation order, not a causal history**. The response says
  so in ``basis``, ``is_causal_history``, ``scope_note`` and ``summary``; this docstring
  says so too, because the route name is the part most likely to be read alone.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.agent_access_intelligence.profiles import capability_profile_service

logger = get_logger("aether.service.agent_access_intelligence.profile_routes")

capability_profiles_router = APIRouter(
    prefix="/v1/capability-profiles",
    tags=["Agent Access Intelligence"],
)


@capability_profiles_router.get("")
async def list_agent_profiles(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Agents this tenant has been observed with at least one installation for.

    A light index, not a page of full profiles. Absence from it means "not observed",
    never "has no access" — ``note`` on the response says so."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_profile_service.list_profiles(
        tenant.tenant_id, limit=limit, offset=offset
    )
    metrics.increment(
        "capability_profiles_listed",
        labels={"truncated": "true" if data.get("truncated") else "false"},
    )
    return APIResponse(data=data).to_dict()


@capability_profiles_router.get("/{agent_id}")
async def read_agent_profile(agent_id: str, request: Request):
    """One agent's observed access profile.

    When an input was never observed the response carries ``profile_known: false``,
    ``null`` counts and a ``missing_inputs`` list. It never reports unknown reach as zero,
    and an unobserved agent id is answered identically to another tenant's."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_profile_service.profile(tenant.tenant_id, agent_id)
    metrics.increment(
        "capability_profile_reads",
        labels={"profile_known": "true" if data.get("profile_known") else "false"},
    )
    return APIResponse(data=data).to_dict()


@capability_profiles_router.get("/{agent_id}/journey")
async def read_agent_journey(
    request: Request,
    agent_id: str,
    limit: int = Query(200, ge=1, le=500),
):
    """This agent's access journey: bounded, ordered first-observation milestones.

    **Observation order, not causal history.** Each milestone is dated by the first time
    this platform *recorded* something, not the first time it happened, and capability
    milestones are tenant-scoped rather than agent-scoped. Not an audit trail."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_profile_service.journey(
        tenant.tenant_id, agent_id, limit=limit
    )
    metrics.increment(
        "capability_journey_reads",
        labels={
            "journey_known": "true" if data.get("journey_known") else "false",
            "truncated": "true" if data.get("truncated") else "false",
        },
    )
    return APIResponse(data=data).to_dict()
