"""Agent Access Intelligence — capability access graph API (PR 4, ``AAI-4-GRAPH``).

``/v1/capability-graph/neighborhood``  bounded agents→servers→capabilities neighborhood
                                      around exactly one anchor.
``/v1/capability-graph/summary``       bounded counts by node kind and edge kind.

The prefix is ``/v1/capability-graph`` and not ``/v1/graph``: that prefix is already
owned by two other routers, and a third mounting under it would make route
classification and ownership ambiguous for no gain.

Mirrors ``authority_routes.py`` / ``risk_routes.py``: read ``request.state.tenant``, call
``require_permission(...)``, scope every query by ``tenant.tenant_id``, return
``APIResponse``. Both routes require ``read`` and only ``read`` — they compute over
stores that already exist, write no row and publish no event, so there is no new event
type and no ``event-registry.json`` change.

Both responses report ``*_known: false`` with ``null`` counts rather than a 404 or a zero
when the inputs they need were never observed, and disclose every bound they hit. See
``access_graph`` for why that distinction is the whole point of the surface.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.agent_access_intelligence.access_graph import (
    DEFAULT_DEPTH,
    DEFAULT_NODES,
    MAX_DEPTH,
    MAX_NODES,
    capability_access_graph_service,
)

logger = get_logger("aether.service.agent_access_intelligence.access_graph_routes")

capability_graph_router = APIRouter(
    prefix="/v1/capability-graph",
    tags=["Agent Access Intelligence"],
)


@capability_graph_router.get("/neighborhood")
async def read_access_neighborhood(
    request: Request,
    agent_id: Optional[str] = Query(
        default=None, description="What this agent has been observed reaching."
    ),
    capability_id: Optional[str] = Query(
        default=None, description="Who has been observed reaching this capability."
    ),
    server_key: Optional[str] = Query(
        default=None,
        description="What is bound to this server (its observed name or URL).",
    ),
    depth: int = Query(
        DEFAULT_DEPTH,
        ge=1,
        le=MAX_DEPTH,
        description=(
            f"Hops from the anchor. Hard-capped at {MAX_DEPTH}; the applied depth and the "
            "cap are always stated in the response."
        ),
    ),
    limit: int = Query(
        DEFAULT_NODES,
        ge=1,
        le=MAX_NODES,
        description="Maximum nodes. Hitting it is disclosed, never silently truncated.",
    ),
):
    """The bounded access neighborhood around exactly one anchor.

    Exactly one of ``agent_id`` / ``capability_id`` / ``server_key`` is required — they
    ask three different questions and a request naming none or several has no single
    answer. When an input is absent the response carries ``neighborhood_known: false``,
    ``null`` counts and a ``missing_inputs`` list; ``nodes``/``edges`` are still returned
    as evidence and are never claimed to be complete. Edge ``authorized`` is tri-state:
    ``null`` means the authorization read was unavailable, never "unauthorized"."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_access_graph_service.neighborhood(
        tenant.tenant_id,
        agent_id=agent_id,
        capability_id=capability_id,
        server_key=server_key,
        depth=depth,
        limit=limit,
    )
    metrics.increment(
        "capability_access_graph_neighborhood_reads",
        labels={
            "anchor": str(data.get("anchor", {}).get("kind")),
            "known": "true" if data.get("neighborhood_known") else "false",
            "complete": "true" if data.get("complete") else "false",
        },
    )
    return APIResponse(data=data).to_dict()


@capability_graph_router.get("/summary")
async def read_access_graph_summary(request: Request):
    """Bounded node/edge counts for the tenant's whole observed access graph.

    Every count is ``null`` when any bounded read truncated — a partial total is still a
    number a reader will treat as complete. A tenant with no observations at all reports
    zeros with ``observed_any: false`` and says so in the summary: an absence of
    observation is not evidence that its agents reach nothing."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await capability_access_graph_service.summary(tenant.tenant_id)
    metrics.increment(
        "capability_access_graph_summary_reads",
        labels={"known": "true" if data.get("summary_known") else "false"},
    )
    return APIResponse(data=data).to_dict()
