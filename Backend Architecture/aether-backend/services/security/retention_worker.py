"""Retention sweep background worker.

Runs daily (configurable via RETENTION_SWEEP_INTERVAL_HOURS) and calls
DataRetentionService.sweep() to age out expired records per tenant policy.

FT-8 (object-backed Bronze): the same sweep additionally applies the
storage-plane lifecycle — policy-driven retention from
config/storage_policies.yaml (retention_class / delete_behavior) over
externalized objects, their descriptor index, AND Bronze rows, with active
legal holds blocking every deletion — when
STORAGE_LIFECYCLE_RETENTION_ENABLED is true (default OFF).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from shared.logger.logger import get_logger, metrics
from services.security.retention import data_retention_service

logger = get_logger("aether.security.retention.worker")

_INTERVAL_HOURS = int(os.getenv("RETENTION_SWEEP_INTERVAL_HOURS", "24"))


async def storage_lifecycle_retention_pass() -> Optional[dict]:
    """FT-8: retention for externalized objects + Bronze rows (flag-gated).

    Returns the per-resource-type report, or None when
    STORAGE_LIFECYCLE_RETENTION_ENABLED is off (the default) — the sweep is
    then a pure no-op so the FT-7-era behavior is unchanged.
    """
    from config.settings import settings  # lazy — avoids import cycles

    if not settings.storage_plane.lifecycle_retention_enabled:
        return None
    from shared.storage.lifecycle import StorageLifecycle  # lazy

    return await StorageLifecycle().apply_retention_sweep()


async def retention_sweep_loop(interval_hours: int = _INTERVAL_HOURS) -> None:
    """Background task: run retention sweep on a daily schedule."""
    logger.info(f"Retention sweep worker started: interval={interval_hours}h")
    while True:
        try:
            summary = await data_retention_service.sweep()
            logger.info(f"Retention sweep complete: {summary}")
        except Exception as e:
            logger.error(f"Retention sweep failed: {e}")
            metrics.increment("retention_sweep_loop_error")
        try:
            lifecycle_report = await storage_lifecycle_retention_pass()
            if lifecycle_report is not None:
                logger.info(
                    f"Storage lifecycle retention complete: {lifecycle_report}"
                )
        except Exception as e:
            logger.error(f"Storage lifecycle retention failed: {e}")
            metrics.increment("retention_sweep_loop_error")
        await asyncio.sleep(interval_hours * 3600)
