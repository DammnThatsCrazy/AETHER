"""Supervised retention sweep for journey handoff rows.

Rows hold source and destination anonymous IDs, so they are deleted once older
than ``RETAIN_DAYS``. The sweep runs regardless of ``JOURNEY_HANDOFF_ENABLED``:
turning the feature off must not strand rows that were written while it was on.
"""
from __future__ import annotations

import asyncio

from repositories.journey_handoff_repo import get_journey_handoff_repository
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.journey_handoff.sweep")


async def sweep_once() -> int:
    removed = await get_journey_handoff_repository().sweep_expired()
    if removed:
        metrics.increment("journey_handoff_swept_total", value=removed)
        logger.info("journey handoff sweep removed %s row(s)", removed)
    return removed


async def run_journey_handoff_sweep_loop(interval_seconds: float = 3600.0) -> None:
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a loop must never die on one tick
            logger.warning("journey handoff sweep failed: %s", exc)
            metrics.increment("journey_handoff_sweep_errors_total")
        await asyncio.sleep(interval_seconds)


def build_journey_handoff_sweep_coro():
    return run_journey_handoff_sweep_loop()
