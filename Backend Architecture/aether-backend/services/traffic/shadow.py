"""Shadow classification: legacy-vs-canonical divergence recording.

When ``TrafficFlags.shadow_classification_enabled`` is on for a tenant the
dispatcher calls :func:`shadow_compare_rows` for every touchpoint it projects.
For each row we take the canonical ``source_class`` the v3 classifier already
produced and derive what the pre-v3 ("legacy") system would have bucketed it
as, using the registry's LEGACY aliases reverse-mapped. When the two disagree a
divergence row is written to ``source_classification_shadow_divergences``.

Critically this path is *observational only* (mirrors the semantic
``shadow_provider`` seam in services/semantic_intelligence/service.py):

- it never mutates the customer-visible touchpoint row or its attribution,
- it never re-runs or overrides the canonical classifier,
- a failure is logged and swallowed so Silver writes are never lost.

The recorded rows back the operator route's
``classification_drift.legacy_vs_canonical_divergence_rate``.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger
from repositories.repos import get_pool
from services.traffic.classifier import (
    SOURCE_CLASSIFIER_VERSION,
    legacy_shadow_source_class as legacy_source_class,
)
from services.traffic import metrics as traffic_metrics

logger = get_logger("aether.traffic.shadow")

SHADOW_TABLE = "source_classification_shadow_divergences"

# In-memory fallback (local/test only), mirrors touchpoint_repo._local_store.
_local_divergences: list[dict[str, Any]] = []


def _reset_local_divergences() -> None:
    """Test hook — clears the in-memory divergence store."""
    _local_divergences.clear()


class ShadowDivergenceRepository:
    """Durable access to ``source_classification_shadow_divergences``."""

    async def _pool(self):
        return await get_pool()

    def _idempotency_key(
        self, tenant_id: str, source_event_id: str, classifier_version: str
    ) -> str:
        raw = f"{tenant_id}:{source_event_id}:{classifier_version}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def record(
        self,
        *,
        tenant_id: str,
        source_event_id: str,
        touchpoint_id: Optional[str],
        legacy_source_class: str,
        canonical_source_class: str,
        diverged: bool,
        classifier_version: str = SOURCE_CLASSIFIER_VERSION,
    ) -> dict[str, Any]:
        """Idempotently record one divergence observation.

        Idempotent on (tenant_id, source_event_id, classifier_version) so a
        replayed event never double-counts a divergence.
        """
        observed_at = datetime.now(timezone.utc)
        idem = self._idempotency_key(tenant_id, source_event_id, classifier_version)
        row = {
            "tenant_id": tenant_id,
            "source_event_id": source_event_id,
            "touchpoint_id": touchpoint_id,
            "legacy_source_class": legacy_source_class,
            "canonical_source_class": canonical_source_class,
            "diverged": diverged,
            "classifier_version": classifier_version,
            "observed_at": observed_at,
            "idempotency_key": idem,
        }
        pool = await self._pool()
        if pool is None:
            for existing in _local_divergences:
                if existing.get("idempotency_key") == idem:
                    return existing
            _local_divergences.append(dict(row))
            return row
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {SHADOW_TABLE}
                    (tenant_id, source_event_id, touchpoint_id, legacy_source_class,
                     canonical_source_class, diverged, classifier_version, observed_at,
                     idempotency_key)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                tenant_id, source_event_id, touchpoint_id, legacy_source_class,
                canonical_source_class, diverged, classifier_version, observed_at, idem,
            )
        return row

    async def divergence_rate(self, tenant_id: str) -> dict[str, Any]:
        """Return {total, diverged, rate} for a tenant."""
        pool = await self._pool()
        if pool is None:
            rows = [r for r in _local_divergences if r.get("tenant_id") == tenant_id]
            total = len(rows)
            diverged = sum(1 for r in rows if r.get("diverged"))
            return {
                "total": total,
                "diverged": diverged,
                "rate": (diverged / total) if total else 0.0,
            }
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*)::bigint AS total,
                       COUNT(*) FILTER (WHERE diverged)::bigint AS diverged
                FROM {SHADOW_TABLE}
                WHERE tenant_id=$1
                """,
                tenant_id,
            )
        total = int(row["total"] or 0)
        diverged = int(row["diverged"] or 0)
        return {
            "total": total,
            "diverged": diverged,
            "rate": (diverged / total) if total else 0.0,
        }


_repo = ShadowDivergenceRepository()


async def shadow_compare_rows(
    tenant_id: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute and record legacy-vs-canonical divergence for touchpoint rows.

    Reads the canonical ``source_class`` already assigned to each row (never
    re-classifies), derives the legacy bucket, and records a divergence fact.
    Returns the recorded divergence rows (for tests / callers); the input rows
    are never mutated. Never raises.
    """
    recorded: list[dict[str, Any]] = []
    try:
        for row in rows:
            canonical = row.get("source_class")
            source_event_id = row.get("source_event_id")
            if not canonical or not source_event_id:
                continue
            legacy = legacy_source_class(str(canonical))
            diverged = legacy != str(canonical)
            classifier_version = (
                row.get("source_classifier_version") or SOURCE_CLASSIFIER_VERSION
            )
            result = await _repo.record(
                tenant_id=tenant_id,
                source_event_id=str(source_event_id),
                touchpoint_id=(
                    str(row["touchpoint_id"]) if row.get("touchpoint_id") else None
                ),
                legacy_source_class=legacy,
                canonical_source_class=str(canonical),
                diverged=diverged,
                classifier_version=str(classifier_version),
            )
            traffic_metrics.record_shadow_divergence(diverged)
            recorded.append(result)
    except Exception as exc:  # pragma: no cover — shadow must never break Silver
        logger.warning("shadow_compare_failed tenant=%s: %s", tenant_id, exc)
    return recorded


def is_shadow_enabled_for(tenant_id: str) -> bool:
    """Thin wrapper so the dispatcher can gate without importing flags directly."""
    from services.traffic.flags import traffic_flags

    return traffic_flags.is_enabled_for_tenant("shadow_classification_enabled", tenant_id)


__all__ = [
    "SHADOW_TABLE",
    "ShadowDivergenceRepository",
    "shadow_compare_rows",
    "legacy_source_class",
    "is_shadow_enabled_for",
]
