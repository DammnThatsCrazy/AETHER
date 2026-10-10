"""Semantic reconciler — recompute Gold projections from Silver evidence.

Scheduled safety-net (WorkerSpec ``semantic_reconciler``, gated on
``settings.semantic.reconciler_enabled``) that, per tenant, recomputes each
subject's Gold entity/sentiment state from the immutable Silver observations and
reports — and, by default, repairs — drift where the stored Gold projection no
longer matches what the reducer derives from current evidence.

The reducers are the single source of truth for the computation; this module
only decides *which* subjects to re-derive and whether the stored projection
still agrees. Repair reuses ``reducers.recompute_entity_state`` /
``recompute_entity_sentiment`` (idempotent, version-checked upserts), so a
reconciler pass can never write a projection the normal event path would not.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

from . import reducers
from .repositories.base_fact_repo import SemanticFactRepository

logger = get_logger("aether.semantic.reconciler")

_UNKNOWN_SUBJECT = "unknown_subject"
_RECONCILE_INTERVAL_S = int(os.getenv("SEMANTIC_RECONCILER_INTERVAL_S", str(6 * 3600)))


@dataclass
class SubjectDrift:
    subject_ref: str
    kind: str  # "entity" | "sentiment"


@dataclass
class ReconcileReport:
    """Per-tenant reconciler outcome (drift found, and how much was repaired)."""

    tenant_id: str
    subjects_checked: int = 0
    drifted: list[SubjectDrift] = field(default_factory=list)
    repaired: int = 0

    @property
    def is_clean(self) -> bool:
        return not self.drifted

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "subjects_checked": self.subjects_checked,
            "drifted": [{"subject_ref": d.subject_ref, "kind": d.kind} for d in self.drifted],
            "drift_count": len(self.drifted),
            "repaired": self.repaired,
            "is_clean": self.is_clean,
        }


def _entity_signature(data: dict[str, Any]) -> tuple:
    """Stable comparable fields of an entity Gold state (timestamps excluded).

    ``computed_at`` / ``window_end`` are stamped ``now`` on every recompute, so
    they can never participate in drift detection — only the reduced values do.
    """
    return (
        data.get("observation_count"),
        data.get("unique_source_count"),
        data.get("confidence"),
        data.get("semantic_summary"),
        tuple(sorted((data.get("stance_distribution") or {}).items())),
        tuple(sorted((data.get("intent_distribution") or {}).items())),
        tuple(data.get("active_topics") or []),
    )


def _sentiment_signature(data: dict[str, Any]) -> tuple:
    return (
        data.get("observation_count"),
        data.get("insufficient_data"),
        data.get("valence"),
        data.get("arousal"),
        data.get("intensity"),
        data.get("dominant_emotion"),
        data.get("sentiment_trend"),
        data.get("confidence"),
    )


async def _stored_gold(
    repo: SemanticFactRepository, tenant_id: str, subject_ref: str, idem: str
) -> Optional[dict[str, Any]]:
    for data in await repo.list_by_tenant(tenant_id, subject_ref):
        if data.get("idempotency_key") == idem:
            return data
    return None


async def reconcile_tenant(
    tenant_id: str, *, store: Optional[Any] = None, repair: bool = True
) -> ReconcileReport:
    """Recompute + (optionally) repair a tenant's Gold projections from Silver.

    Iterates the distinct subjects present in the tenant's Silver semantic /
    sentiment observations, re-derives each Gold projection, and records drift
    when the stored projection's stable signature diverges from the recomputed
    one. When ``repair`` is true (the scheduled default) the reducer re-persists
    the correct projection; ``repair=False`` is a pure report (dry run).
    """
    from .engine import get_store

    active_store = store or get_store()
    observations = await active_store.list_semantic(tenant_id)
    sentiments = await active_store.list_sentiment(tenant_id)
    report = ReconcileReport(tenant_id=tenant_id)

    entity_repo = SemanticFactRepository(reducers._GOLD_ENTITY_TABLE, mode="gold")
    entity_subjects = {
        o.primary_subject_ref
        for o in observations
        if o.primary_subject_ref and o.primary_subject_ref != _UNKNOWN_SUBJECT
    }
    for subject in sorted(entity_subjects):
        report.subjects_checked += 1
        subject_obs = [o for o in observations if o.primary_subject_ref == subject]
        recomputed = reducers.reduce_entity_state(tenant_id, subject, subject_obs)
        idem = f"gold_entity:{tenant_id}:{subject}:{reducers.REDUCER_VERSION}"
        stored = await _stored_gold(entity_repo, tenant_id, subject, idem)
        if stored is None or _entity_signature(stored) != _entity_signature(
            recomputed.model_dump(mode="json")
        ):
            report.drifted.append(SubjectDrift(subject, "entity"))
            if repair:
                await reducers.recompute_entity_state(tenant_id, subject, store=active_store)
                report.repaired += 1

    sentiment_repo = SemanticFactRepository(reducers._GOLD_SENTIMENT_TABLE, mode="gold")
    sentiment_subjects = {s.target_subject_ref for s in sentiments if s.target_subject_ref}
    for subject in sorted(sentiment_subjects):
        report.subjects_checked += 1
        subject_sent = [s for s in sentiments if s.target_subject_ref == subject]
        recomputed_sent = reducers.reduce_entity_sentiment(tenant_id, subject, subject_sent)
        idem = f"gold_sentiment:{tenant_id}:{subject}:{reducers.REDUCER_VERSION}"
        stored = await _stored_gold(sentiment_repo, tenant_id, subject, idem)
        if stored is None or _sentiment_signature(stored) != _sentiment_signature(
            recomputed_sent
        ):
            report.drifted.append(SubjectDrift(subject, "sentiment"))
            if repair:
                await reducers.recompute_entity_sentiment(tenant_id, subject, store=active_store)
                report.repaired += 1

    return report


async def reconcile_once() -> list[ReconcileReport]:
    """One reconciler pass across every tenant with Silver evidence.

    Tenants are enumerated from the durable Silver observations table; a
    deployment running the in-memory store (local/CI) has no rows there, so the
    pass is a no-op — matching the flag being off by default.
    """
    from .store import _OBSERVATIONS_TABLE

    tenants = await SemanticFactRepository(_OBSERVATIONS_TABLE).distinct_tenants()
    reports: list[ReconcileReport] = []
    for tenant_id in tenants:
        report = await reconcile_tenant(tenant_id)
        if not report.is_clean:
            metrics.increment("semantic_reconciler_drift_total", len(report.drifted))
            logger.warning("semantic reconciler drift: %s", report.to_dict())
        reports.append(report)
    return reports


async def run_semantic_reconciler_loop(interval_seconds: Optional[int] = None) -> None:
    """Supervised loop: recompute Gold from Silver on a fixed interval."""
    interval = int(
        interval_seconds if interval_seconds is not None else _RECONCILE_INTERVAL_S
    )
    logger.info("semantic reconciler worker started interval=%ss", interval)
    while True:
        try:
            await reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover — defensive supervision
            metrics.increment("semantic_reconciler_error_total")
            logger.error("semantic reconciler pass failed: %s", exc, exc_info=True)
        await asyncio.sleep(interval)


def build_semantic_reconciler_coro() -> Any:
    """Zero-arg coroutine factory for the ``semantic_reconciler`` WorkerSpec."""
    return run_semantic_reconciler_loop()
