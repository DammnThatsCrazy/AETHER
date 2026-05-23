"""Monthly overage invoice cron — runs as a background asyncio task."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from shared.logger.logger import get_logger

logger = get_logger("aether.billing.cron")


def _seconds_until_end_of_month() -> float:
    """Return seconds until 23:55 on the last day of the current month."""
    now = datetime.now(timezone.utc)
    # First day of next month
    if now.month == 12:
        first_next = now.replace(year=now.year + 1, month=1, day=1, hour=23, minute=55, second=0, microsecond=0)
    else:
        first_next = now.replace(month=now.month + 1, day=1, hour=23, minute=55, second=0, microsecond=0)
    # Last day of current month = day before first of next month
    last_day = first_next - timedelta(days=1)
    delta = (last_day - now).total_seconds()
    return max(delta, 0)


async def run_monthly_overage_cron() -> None:
    """Background task: sleep until end-of-month, then run the overage cycle.

    Loops indefinitely — intended to run for the lifetime of the process.
    """
    from services.billing.cycle import run_overage_cycle
    while True:
        wait_secs = _seconds_until_end_of_month()
        logger.info(f"Overage cron: next run in {wait_secs / 3600:.1f}h")
        await asyncio.sleep(wait_secs)
        try:
            summary = await run_overage_cycle()
            logger.info(f"Overage cron cycle complete: {summary}")
        except Exception as e:
            logger.error(f"Overage cron cycle failed: {e}")
        # Sleep 10 minutes after running to avoid re-triggering at midnight
        await asyncio.sleep(600)
