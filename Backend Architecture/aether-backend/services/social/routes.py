"""
Aether — Social Intelligence API Route (legacy compatibility wrapper)

GET /v1/profile/{entity_id}/social-intelligence?window=30d|60d|90d|lifetime

This route is a legacy compatibility wrapper over the canonical Profile360
``IntelligenceAggregator.social_intelligence`` — the real handler that this
router's mount order previously shadowed in main.py. It performs NO local metric
fabrication: the response is exactly what the canonical aggregator produces from
evidence-backed gold rows. When no evidence-backed social facts exist the
canonical envelope reports an empty ``items`` list and a summary that carries no
follower/influence/engagement claims — never ``followers = 0``,
``influence_level = "low"``, or ``engagement_rate = 0.0`` for unknown data.

Honesty notes (M4 legacy social honesty migration):
  - No fabricated zeros / default "low" influence are synthesized in this module.
  - The wrapper enforces the read permission and window validation, then
    delegates to the canonical aggregator and wraps its envelope in the standard
    ``APIResponse`` shape (identical to the Profile360 handler it shadows).
  - The legacy stub's invented ``summary.{total_followers_deduped,
    influence_level, engagement_rate, platforms_connected}`` contract is gone;
    callers read the canonical envelope (``items[]`` + ``summary``).

Ownership: M4 slice of the Social360 + Relationship Fidelity program. See
``reports/social360/LEGACY_SOCIAL_TRUTH_MATRIX.md`` §0.1. main.py still mounts
this router ahead of profile_router; the mount-order / false-comment fix in
main.py is integrator-owned (this module is not responsible for main.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

if TYPE_CHECKING:
    from services.profile.intelligence import IntelligenceAggregator

logger = get_logger("aether.social.routes")

router = APIRouter(tags=["social"])

_WINDOW_MAP = {"30d": 30, "60d": 60, "90d": 90, "lifetime": None}

# Lazily-initialized canonical aggregator singleton (mirrors the pattern in
# services/profile/routes.py). Kept module-private so tests can override the
# FastAPI dependency with a fake aggregator.
_aggregator: "IntelligenceAggregator | None" = None


def _get_aggregator() -> "IntelligenceAggregator":
    """Return the canonical Profile360 IntelligenceAggregator (lazy import).

    The import is deferred so that importing this legacy router does not pull in
    the profile aggregator dependency tree at module import time.
    """
    global _aggregator
    if _aggregator is None:
        # Local import keeps import-time coupling out of the module top level.
        from services.profile.intelligence import IntelligenceAggregator

        _aggregator = IntelligenceAggregator()
    return _aggregator


@router.get("/v1/profile/{entity_id}/social-intelligence")
async def get_social_intelligence(
    entity_id: str,
    request: Request,
    window: str = Query(default="30d", description="30d | 60d | 90d | lifetime"),
    intel: Any = Depends(_get_aggregator),
):
    """Return evidence-backed social intelligence for an entity.

    Entity-agnostic: works for any human, brand, organization, or AI agent that
    has observed social facts in the gold tier. When no evidence-backed social
    facts exist the canonical envelope reports an empty items list and an
    unpopulated summary — it never converts unknown data into zeros or a default
    "low" influence level.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    if window not in _WINDOW_MAP:
        raise HTTPException(status_code=400, detail=f"window must be one of: {list(_WINDOW_MAP.keys())}")

    envelope = await intel.social_intelligence(entity_id, tenant.tenant_id, window=window)
    # Wrap in the standard APIResponse envelope so the wire shape is identical to
    # the canonical Profile360 handler this route shadows (frontend clients parse
    # response.data). The inner envelope is the aggregator's honest output.
    return APIResponse(data=envelope).to_dict()
