"""Bronze object-compaction worker (FT-8-OBJECT-BACKED-BRONZE).

Supervised loop (WorkerSpec ``bronze_object_compaction``, owned by the
``materializer`` runtime role) that, on each interval:

  1. runs one Bronze compaction pass — packing cold payload batches into
     externalized objects with hot searchable metadata retained in Postgres —
     when BOTH ``BRONZE_OBJECT_COMPACTION_ENABLED`` and
     ``STORAGE_EXTERNALIZATION_ENABLED`` are true (the compactor itself
     re-checks the flags, so a disabled pass is a no-op, never an error);
  2. runs one storage-reconciler pass (descriptor index vs object store:
     missing / orphan / checksum-drift metrics) when
     ``STORAGE_RECONCILER_ENABLED`` is true — this is the runtime scheduling
     FT-7 deferred to FT-8.

All flags default OFF; the WorkerSpec's ``enabled`` gate keeps the loop from
starting at all when neither behavior is switched on.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.storage_lifecycle.worker")


async def run_bronze_compaction_loop(interval_seconds: Optional[int] = None) -> None:
    """Periodic compaction + reconciliation sweep (flags re-read every pass)."""
    from config.settings import settings

    interval = int(
        interval_seconds
        if interval_seconds is not None
        else settings.storage_plane.bronze_compaction_interval_s
    )
    logger.info(f"bronze object-compaction worker started interval={interval}s")
    while True:
        try:
            await _sweep_once(settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            metrics.increment("storage_lifecycle_sweep_error_total")
            logger.error(f"bronze compaction sweep failed: {exc}", exc_info=True)
        await asyncio.sleep(interval)


async def _sweep_once(settings: Any) -> None:
    plane = settings.storage_plane
    if plane.bronze_compaction_enabled and plane.externalization_enabled:
        from shared.storage.compaction import BronzeObjectCompactor

        stats = await BronzeObjectCompactor().compact_once()
        if stats.rows_externalized or stats.errors:
            logger.info(
                f"bronze compaction pass: candidates={stats.candidates} "
                f"rows_externalized={stats.rows_externalized} "
                f"objects={stats.objects_written} errors={len(stats.errors)}"
            )
    if plane.reconciler_enabled:
        from shared.storage.reconciler import reconcile_object_store

        report = await reconcile_object_store()
        if not report.is_clean:
            logger.warning(
                f"storage reconciler pass found drift: {report.to_dict()}"
            )


def build_bronze_compaction_coro() -> Any:
    """Zero-arg coroutine factory for the ``bronze_object_compaction`` WorkerSpec."""
    return run_bronze_compaction_loop()
