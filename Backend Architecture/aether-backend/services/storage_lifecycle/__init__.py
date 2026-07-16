"""Aether — Storage lifecycle workers (FT-8-OBJECT-BACKED-BRONZE).

Supervised runtime wiring for the Elastic Data Plane's object-backed Bronze
compaction sweep and the scheduled storage reconciler. The policy-driven
lifecycle logic itself lives in ``shared/storage/compaction.py`` and
``shared/storage/lifecycle.py``; retention for externalized objects rides the
existing maintenance retention worker (services/security/retention_worker.py).
"""

from services.storage_lifecycle.worker import (  # noqa: F401
    build_bronze_compaction_coro,
    run_bronze_compaction_loop,
)

__all__ = ["build_bronze_compaction_coro", "run_bronze_compaction_loop"]
