"""Measurement privacy handler — propagates DSR erasure into the measurement pipeline."""

from __future__ import annotations

import asyncio
from typing import Any

from shared.logger.logger import get_logger
from services.measurement.repositories.touchpoint_repo import TouchpointRepository
from services.measurement.repositories.conversion_repo import ConversionRepository

logger = get_logger("aether.measurement.privacy")

_touchpoint_repo = TouchpointRepository()
_conversion_repo = ConversionRepository()


class MeasurementPrivacyHandler:
    """Propagates consent erasure into the measurement data pipeline.

    Called fire-and-forget from the DSR route when request_type == 'erasure'.
    Steps:
      1. Tombstone touchpoints (sets privacy_class='deleted', nulls identity fields)
      2. Mark conversions attribution-ineligible (nulls identity fields)
      3. Triggers journey rebuild for the profile (which will auto-recompute attribution)
    """

    async def handle_erasure(self, tenant_id: str, user_id: str) -> dict[str, Any]:
        touchpoint_count = 0
        conversion_count = 0
        journey_rebuild_triggered = False
        errors: list[str] = []

        try:
            touchpoint_count = await _touchpoint_repo.tombstone_for_profile(tenant_id, user_id)
            logger.info(
                "DSR erasure: tombstoned %d touchpoints",
                touchpoint_count,
                extra={"tenant_id": tenant_id, "user_id": user_id},
            )
        except Exception as exc:
            errors.append(f"touchpoint_tombstone: {exc}")
            logger.error("DSR erasure touchpoint tombstone failed: %s", exc, extra={"tenant_id": tenant_id})

        try:
            conversion_count = await _conversion_repo.tombstone_for_profile(tenant_id, user_id)
            logger.info(
                "DSR erasure: tombstoned %d conversions",
                conversion_count,
                extra={"tenant_id": tenant_id, "user_id": user_id},
            )
        except Exception as exc:
            errors.append(f"conversion_tombstone: {exc}")
            logger.error("DSR erasure conversion tombstone failed: %s", exc, extra={"tenant_id": tenant_id})

        try:
            from services.measurement.engine.journey_compiler import JourneyCompiler
            compiler = JourneyCompiler()
            await compiler.rebuild_affected_by_consent_change(tenant_id, user_id)
            journey_rebuild_triggered = True
        except Exception as exc:
            errors.append(f"journey_rebuild: {exc}")
            logger.error("DSR erasure journey rebuild failed: %s", exc, extra={"tenant_id": tenant_id})

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "touchpoints_tombstoned": touchpoint_count,
            "conversions_tombstoned": conversion_count,
            "journey_rebuild_triggered": journey_rebuild_triggered,
            "errors": errors,
            "partial_failure": bool(errors),
        }


_handler = MeasurementPrivacyHandler()


async def handle_erasure_background(tenant_id: str, user_id: str) -> None:
    """Fire-and-forget wrapper — swallows exceptions after logging."""
    try:
        result = await _handler.handle_erasure(tenant_id, user_id)
        logger.info("DSR erasure complete: %s", result, extra={"tenant_id": tenant_id})
    except Exception as exc:
        logger.error("DSR erasure handler fatal: %s", exc, extra={"tenant_id": tenant_id})
