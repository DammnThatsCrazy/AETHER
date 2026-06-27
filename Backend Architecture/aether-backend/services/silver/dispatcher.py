"""Silver dispatcher — routes Bronze events to the appropriate projector.

Usage::

    from services.silver.dispatcher import SilverDispatcher
    dispatcher = SilverDispatcher()
    results = await dispatcher.project(event_dict)
    # results: list[ProjectionResult], each with .table and .rows
"""

from __future__ import annotations

import asyncio
from typing import Any

from shared.logger.logger import get_logger
from .projectors.base import ProjectionResult
from .projectors import (
    ExposureProjector,
    OutcomeProjector,
    RevenueProjector,
    FrictionProjector,
    AccountActivityProjector,
    ServerOperationProjector,
    IdentityEvidenceProjector,
    AgentExecutionProjector,
    Web3TransactionProjector,
    X402FlowProjector,
    TouchpointProjector,
    ConversionProjector,
)
from .projectors.silver_graph_projector import SilverGraphProjector

logger = get_logger("silver.dispatcher")

_ALL_PROJECTORS = [
    ExposureProjector(),
    OutcomeProjector(),
    RevenueProjector(),
    FrictionProjector(),
    AccountActivityProjector(),
    ServerOperationProjector(),
    IdentityEvidenceProjector(),
    AgentExecutionProjector(),
    Web3TransactionProjector(),
    X402FlowProjector(),
    TouchpointProjector(),
    ConversionProjector(),
]

# Build a fast lookup: event_type → projector
_TYPE_MAP: dict[str, object] = {}
for _p in _ALL_PROJECTORS:
    for _t in _p.handles:
        _TYPE_MAP[_t] = _p

_graph_projector = SilverGraphProjector()

_TOUCHPOINT_TABLE = "silver_campaign_touchpoint_facts"

# Private hint keys injected by TouchpointProjector for resolver pass-through;
# these are stripped before rows reach the database writer.
_RESOLVER_HINT_KEYS = {"_canonical_campaign_id_hint", "_utm_id"}


async def _resolve_touchpoint_rows(rows: list[dict[str, Any]]) -> None:
    """Resolve campaign evidence for touchpoint rows in-place.

    Calls CampaignResolver per row, updates campaign_id and resolution fields.
    Never raises — resolution failure writes 'unresolved' status but does not
    drop the event.
    """
    try:
        from services.campaign.resolver import CampaignResolver
        resolver = CampaignResolver()
    except Exception as exc:
        logger.warning("campaign_resolver_unavailable: %s — skipping resolution", exc)
        for row in rows:
            for k in _RESOLVER_HINT_KEYS:
                row.pop(k, None)
        return

    for row in rows:
        canonical_hint = row.pop("_canonical_campaign_id_hint", None)
        utm_id = row.pop("_utm_id", None)
        tenant_id = row.get("tenant_id", "")

        try:
            result = await resolver.resolve_one(
                tenant_id,
                canonical_campaign_id=canonical_hint,
                platform=row.get("platform"),
                external_account_id=row.get("external_account_id"),
                external_campaign_id=row.get("external_campaign_id"),
                utm_id=utm_id,
                utm_source=row.get("utm_source"),
                utm_medium=row.get("utm_medium"),
                utm_campaign=row.get("utm_campaign"),
                utm_content=row.get("utm_content"),
                utm_term=row.get("utm_term"),
                landing_url=row.get("landing_url"),
                create_review_on_failure=True,
            )
            row["campaign_id"] = str(result.campaign_id) if result.campaign_id else None
            row["campaign_resolution_status"] = result.status
            row["campaign_resolution_method"] = result.method
            row["campaign_resolution_confidence"] = (
                float(result.confidence) if result.confidence is not None else None
            )
            row["campaign_resolution_version"] = result.resolution_version
        except Exception as exc:
            logger.warning(
                "campaign_resolution_error row=%s: %s",
                row.get("source_event_id"), exc,
            )
            row["campaign_resolution_status"] = "unresolved"
            row["campaign_resolution_version"] = "1.0"


class SilverDispatcher:
    """Projects a single Bronze event into Silver fact rows, then emits graph mutations."""

    async def project(self, event: dict[str, Any]) -> list[ProjectionResult]:
        event_type = event.get("type", "")
        projector = _TYPE_MAP.get(event_type)
        if projector is None:
            return []
        try:
            result = projector.project_and_emit(event)  # type: ignore[union-attr]
            if result and not result.skipped:
                if result.table == _TOUCHPOINT_TABLE and result.rows:
                    await _resolve_touchpoint_rows(result.rows)
                # Fire-and-forget graph mutations; never block or fail Silver writes
                asyncio.create_task(_graph_projector.maybe_emit(result, event))
                return [result]
            return []
        except Exception as exc:
            logger.error("silver_projection_error", event_type=event_type, error=str(exc))
            return []

    def project_sync(self, event: dict[str, Any]) -> list[ProjectionResult]:
        """Synchronous fallback for non-async callers (skips graph emission and resolution)."""
        event_type = event.get("type", "")
        projector = _TYPE_MAP.get(event_type)
        if projector is None:
            return []
        try:
            result = projector.project_and_emit(event)  # type: ignore[union-attr]
            if result and not result.skipped:
                if result.table == _TOUCHPOINT_TABLE and result.rows:
                    for row in result.rows:
                        for k in _RESOLVER_HINT_KEYS:
                            row.pop(k, None)
                return [result]
            return []
        except Exception as exc:
            logger.error("silver_projection_error", event_type=event_type, error=str(exc))
            return []

    def handles(self, event_type: str) -> bool:
        return event_type in _TYPE_MAP
