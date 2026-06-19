"""Retention sweep background worker.

Runs daily (configurable via RETENTION_SWEEP_INTERVAL_HOURS) and calls
DataRetentionService.sweep() to age out expired records per tenant policy.
"""
from __future__ import annotations

import asyncio
import os

from shared.logger.logger import get_logger, metrics
from services.security.retention import data_retention_service

logger = get_logger("aether.security.retention.worker")

_INTERVAL_HOURS = int(os.getenv("RETENTION_SWEEP_INTERVAL_HOURS", "24"))


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
        await asyncio.sleep(interval_hours * 3600)
