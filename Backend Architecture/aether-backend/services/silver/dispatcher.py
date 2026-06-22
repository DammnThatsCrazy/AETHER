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


class SilverDispatcher:
    """Projects a single Bronze event into Silver fact rows, then emits graph mutations."""

    async def project(self, event: dict[str, Any]) -> list[ProjectionResult]:
        event_type = event.get("type", "")
        projector = _TYPE_MAP.get(event_type)
        if projector is None:
            return []
        try:
            result = projector.project(event)  # type: ignore[union-attr]
            if result and not result.skipped:
                # Fire-and-forget graph mutations; never block or fail Silver writes
                asyncio.create_task(_graph_projector.maybe_emit(result, event))
                return [result]
            return []
        except Exception as exc:
            logger.error("silver_projection_error", event_type=event_type, error=str(exc))
            return []

    def project_sync(self, event: dict[str, Any]) -> list[ProjectionResult]:
        """Synchronous fallback for non-async callers (skips graph emission)."""
        event_type = event.get("type", "")
        projector = _TYPE_MAP.get(event_type)
        if projector is None:
            return []
        try:
            result = projector.project(event)  # type: ignore[union-attr]
            return [result] if result and not result.skipped else []
        except Exception as exc:
            logger.error("silver_projection_error", event_type=event_type, error=str(exc))
            return []

    def handles(self, event_type: str) -> bool:
        return event_type in _TYPE_MAP
