"""
Aether Security — Background Cleanup Task

Periodic cleanup of expired in-memory state across all defense
components to prevent unbounded memory growth in long-running processes.

Supports three integration modes:

  1. **Threading** (default) — ``start_cleanup_thread()`` for standalone use
  2. **asyncio** — ``cleanup_periodic()`` coroutine for FastAPI/uvicorn
  3. **Celery beat** — ``celery_cleanup_task`` for distributed workers

All modes call ``ExtractionDefenseLayer.cleanup()`` which purges:
  - Expired rate limit sliding window buckets
  - Old query pattern records beyond the analysis window
  - Decayed risk scorer states near zero
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .defense_layer import ExtractionDefenseLayer

logger = logging.getLogger("aether.security.cleanup")

# Default interval: 5 minutes
DEFAULT_INTERVAL_SECONDS = 300


# ======================================================================
# Threading mode
# ======================================================================


class CleanupThread(threading.Thread):
    """
    Daemon thread that runs periodic cleanup of defense layer state.

    Usage:
        thread = CleanupThread(defense_layer, interval_seconds=300)
        thread.start()
        # ... on shutdown ...
        thread.stop()
    """

    def __init__(
        self,
        defense_layer: ExtractionDefenseLayer,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ):
        super().__init__(daemon=True, name="extraction-defense-cleanup")
        self._defense = defense_layer
        self._interval = interval_seconds
        self._stop_event = threading.Event()

    def run(self) -> None:
        logger.info(
            "Cleanup thread started (interval=%ds)", self._interval,
        )
        while not self._stop_event.wait(self._interval):
            try:
                result = self._defense.cleanup()
                total = sum(result.values())
                if total > 0:
                    logger.info("Cleanup removed %d expired entries: %s", total, result)
            except Exception:
                logger.exception("Error during defense cleanup")

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to finish."""
        self._stop_event.set()
        self.join(timeout=5.0)
        logger.info("Cleanup thread stopped")


def start_cleanup_thread(
    defense_layer: ExtractionDefenseLayer,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> CleanupThread:
    """Start a daemon cleanup thread. Returns the thread handle."""
    thread = CleanupThread(defense_layer, interval_seconds)
    thread.start()
    return thread


# ======================================================================
# Asyncio mode (for FastAPI / uvicorn)
# ======================================================================


async def cleanup_periodic(
    defense_layer: ExtractionDefenseLayer,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """
    Async coroutine that runs cleanup periodically.

    Usage in FastAPI lifespan:

        @asynccontextmanager
        async def lifespan(app):
            task = asyncio.create_task(cleanup_periodic(defense_layer))
            yield
            task.cancel()
    """
    logger.info("Async cleanup task started (interval=%ds)", interval_seconds)
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                result = defense_layer.cleanup()
                total = sum(result.values())
                if total > 0:
                    logger.info("Cleanup removed %d expired entries: %s", total, result)
            except Exception:
                logger.exception("Error during async defense cleanup")
    except asyncio.CancelledError:
        logger.info("Async cleanup task cancelled")


# ======================================================================
# Celery beat integration
# ======================================================================


def make_celery_task(defense_layer: ExtractionDefenseLayer):
    """
    Create a Celery task function for periodic cleanup.

    Usage with Celery beat:

        from celery import Celery
        app = Celery(...)

        cleanup_task = make_celery_task(defense_layer)
        app.task(name="extraction_defense.cleanup")(cleanup_task)

        # In beat schedule:
        app.conf.beat_schedule = {
            "extraction-defense-cleanup": {
                "task": "extraction_defense.cleanup",
                "schedule": 300.0,
            }
        }
    """
    def celery_cleanup_task():
        result = defense_layer.cleanup()
        total = sum(result.values())
        logger.info("Celery cleanup removed %d expired entries: %s", total, result)
        return result

    return celery_cleanup_task
