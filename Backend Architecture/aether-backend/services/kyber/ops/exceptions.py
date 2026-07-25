"""The exception queue — one prioritised list instead of many dashboards.

An exception is not an alert. Many alerts collapse into one exception, and the
exception carries what it would cost to ignore. Two mechanisms do that work:

**Compression.** ``raise_exception`` never creates a second live row for a
``dedupe_key`` that already has one. It increments ``signal_count``, refreshes
``last_seen_at``, escalates severity, unions the exposure flags and reach, then
re-scores. This mirrors ``services/agent/ops_alerts.record_alert`` deliberately
— same escalate-never-downgrade rule, same "one row per key, with a count"
shape — so an operator does not have to learn two compression models.

It differs from ops_alerts in exactly one way, and the difference is
load-bearing: ops_alerts compresses inside a **time window**
(``OPS_ALERT_COMPRESSION_WINDOW_SECONDS``), whereas an exception compresses for
as long as it is **live**. That is not a preference. The migration declares a
partial unique index — one open exception per ``dedupe_key`` for status in
``open``/``acknowledged``/``in_progress`` — so a windowed second row would be
rejected by the database. Cooperating with the index means status, not age,
decides eligibility. The visible consequence is the one an operator would want:
a *resolved* exception whose condition recurs starts a fresh row, because a
recurrence after a fix is new information.

**Priority.** Ranking is computed in :mod:`.severity` from the exposure fields
and stored with its inputs, so the queue order can be explained after the fact.

Relationship to the alert plane: where ``services/agent/ops_alerts`` already
records a condition, the right move is to ingest that alert as an incident
signal (see :mod:`.correlation`) and raise one exception — not to emit a second
alert. This service adds prioritisation, state and audit over conditions the
platform already detects; it is not a second detector.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

from .contracts import ExceptionBucket, ExceptionStatus, OperationalException, now_iso
from .repository import OPEN_EXCEPTION_STATUSES, ExceptionRepository
from .severity import BUCKET_ORDER, apply_priority, bucket_rank, escalate_severity

logger = get_logger("aether.kyber.ops.exceptions")

#: Terminal statuses. A terminal exception is out of the queue and out of the
#: compression set; the same condition recurring opens a new row.
TERMINAL_STATUSES: frozenset[str] = frozenset({"resolved", "suppressed"})

#: Transitions the service will perform. Anything else is a BadRequestError
#: rather than a silent no-op, because an operator who thinks they acknowledged
#: something has to be right about that.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "acknowledged": frozenset({"open", "acknowledged", "in_progress"}),
    "in_progress": frozenset({"open", "acknowledged", "in_progress"}),
    "resolved": frozenset({"open", "acknowledged", "in_progress"}),
    "suppressed": frozenset({"open", "acknowledged", "in_progress"}),
}


class ExceptionService:
    """Raise, compress, rank and transition operational exceptions."""

    def __init__(self, repository: Optional[ExceptionRepository] = None) -> None:
        self._repo = repository or ExceptionRepository()

    # ── Audit ────────────────────────────────────────────────────────────────

    async def _audit(
        self,
        *,
        actor_id: str,
        event_type: str,
        action: str,
        exception_id: str,
        outcome: str = "allowed",
        tenant_id: Optional[str] = None,
        actor_type: str = "olympus_operator",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record one exception transition in the shared tamper-evident ledger.

        Fail-open on the write itself: the exception row is the durable
        operational signal, and an alerting/audit hiccup must not stop an
        operator from acknowledging a live incident. A missing *module*, by
        contrast, is a declared seam (``services/kyber/seams.py``) and fails the
        seam gate rather than degrading quietly.
        """
        try:
            from services.security.audit_ledger import audit_ledger

            await audit_ledger.record(
                actor_id=actor_id,
                actor_type=actor_type,
                event_type=event_type,
                resource_type="kyber_exception",
                action=action,
                outcome=outcome,
                tenant_id=tenant_id,
                resource_id=exception_id,
                metadata=metadata or {},
            )
        except Exception as exc:  # pragma: no cover - audit must not block ops
            logger.warning(
                "kyber exception audit unavailable (fail-open): event=%s exception=%s error=%s",
                event_type, exception_id, exc,
            )

    # ── Raise / compress ─────────────────────────────────────────────────────

    async def raise_exception(self, exc: OperationalException) -> OperationalException:
        """Record an exception, compressing onto the live row for its dedupe key.

        Args:
            exc: The candidate exception. ``priority_score``, ``priority_inputs``
                and ``bucket`` are always recomputed, so callers cannot inject a
                ranking.

        Returns:
            The stored exception — the **existing** row when compression
            applied, so callers observe the same identity an operator sees.
        """
        apply_priority(exc)

        if exc.dedupe_key:
            existing_row = await self._repo.find_open_by_dedupe_key(exc.dedupe_key)
            if existing_row is not None:
                return await self._compress(existing_row, exc)

        exc.status = "open" if exc.status in TERMINAL_STATUSES else exc.status
        exc.created_at = exc.created_at or now_iso()
        await self._repo.save(exc.model_dump())
        metrics.increment(
            "kyber_exception_open_total",
            labels={"bucket": exc.bucket, "severity": exc.severity},
        )
        await self._audit(
            actor_id="system",
            actor_type="system",
            event_type="kyber.exception.raised",
            action="raise_exception",
            exception_id=exc.exception_id,
            tenant_id=(exc.affected_tenants or [None])[0],
            metadata={
                "title": exc.title,
                "severity": exc.severity,
                "bucket": exc.bucket,
                "priority_score": exc.priority_score,
                "dedupe_key": exc.dedupe_key,
                "dominant_terms": exc.priority_inputs.get("dominant_terms", []),
            },
        )
        logger.info(
            "kyber exception raised id=%s bucket=%s score=%.4f",
            exc.exception_id, exc.bucket, exc.priority_score,
        )
        return exc

    async def _compress(
        self, existing_row: dict[str, Any], incoming: OperationalException
    ) -> OperationalException:
        """Fold ``incoming`` into the live row and re-rank it.

        Merge rules are monotonic on purpose — count up, severity up, exposure
        flags OR'd, reach unioned. A later occurrence of the same condition can
        reveal that it is worse than first thought; it can never prove it is
        milder, because the earlier occurrence still happened.
        """
        existing = OperationalException(**existing_row)
        existing.signal_count = existing.signal_count + max(1, incoming.signal_count)
        existing.last_seen_at = now_iso()
        existing.severity = escalate_severity(existing.severity, incoming.severity)
        existing.customer_visible = existing.customer_visible or incoming.customer_visible
        existing.security_exposure = existing.security_exposure or incoming.security_exposure
        existing.financial_exposure = existing.financial_exposure or incoming.financial_exposure
        existing.data_integrity_exposure = (
            existing.data_integrity_exposure or incoming.data_integrity_exposure
        )
        existing.sla_impact = existing.sla_impact or incoming.sla_impact
        existing.reversible = existing.reversible and incoming.reversible
        existing.confidence = max(existing.confidence, incoming.confidence)
        existing.affected_tenants = _union(existing.affected_tenants, incoming.affected_tenants)
        existing.affected_features = _union(existing.affected_features, incoming.affected_features)
        existing.affected_services = _union(existing.affected_services, incoming.affected_services)
        if incoming.time_to_breach_seconds is not None:
            existing.time_to_breach_seconds = (
                incoming.time_to_breach_seconds if existing.time_to_breach_seconds is None
                else min(existing.time_to_breach_seconds, incoming.time_to_breach_seconds)
            )
        if incoming.probable_cause and not existing.probable_cause:
            existing.probable_cause = incoming.probable_cause
        if incoming.recommended_action and not existing.recommended_action:
            existing.recommended_action = incoming.recommended_action
        if incoming.incident_id and not existing.incident_id:
            existing.incident_id = incoming.incident_id

        apply_priority(existing)
        existing.updated_at = now_iso()
        await self._repo.update(existing.exception_id, existing.model_dump())

        metrics.increment(
            "kyber_exception_compressed_total",
            labels={"bucket": existing.bucket, "severity": existing.severity},
        )
        await self._audit(
            actor_id="system",
            actor_type="system",
            event_type="kyber.exception.compressed",
            action="compress_exception",
            exception_id=existing.exception_id,
            tenant_id=(existing.affected_tenants or [None])[0],
            metadata={
                "dedupe_key": existing.dedupe_key,
                "signal_count": existing.signal_count,
                "severity": existing.severity,
                "bucket": existing.bucket,
                "priority_score": existing.priority_score,
            },
        )
        logger.info(
            "kyber exception compressed id=%s key=%s count=%d",
            existing.exception_id, existing.dedupe_key, existing.signal_count,
        )
        return existing

    # ── Reads ────────────────────────────────────────────────────────────────

    async def get(self, exception_id: str) -> Optional[OperationalException]:
        """One exception, or ``None``."""
        row = await self._repo.find_by_id(exception_id)
        return OperationalException(**row) if row else None

    async def queue(
        self,
        *,
        bucket: Optional[ExceptionBucket] = None,
        status: Optional[str] = "open",
        limit: int = 100,
    ) -> dict[str, Any]:
        """The operator queue: buckets in urgency order, score-sorted within.

        Args:
            bucket: Restrict to one bucket. ``None`` returns all four.
            status: ``"open"`` (the live set the unique index guards — open,
                acknowledged and in_progress), a specific status, or ``None``
                for every exception regardless of state.
            limit: Cap on rows returned per bucket.

        Returns:
            ``buckets`` keyed by bucket name in :data:`BUCKET_ORDER`, a flat
            ``items`` list in bucket-then-score order, per-bucket ``counts``,
            and ``total``. This is the whole surface an operator reads instead
            of watching dashboards, so the ordering is part of the contract.
        """
        rows = await self._repo.list_by_status(status, bucket=bucket, limit=max(limit * 4, limit))
        exceptions = [OperationalException(**row) for row in rows]
        exceptions.sort(key=lambda item: (bucket_rank(item.bucket), -item.priority_score))

        buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in BUCKET_ORDER}
        for item in exceptions:
            target = buckets.setdefault(item.bucket, [])
            if len(target) < limit:
                target.append(item.model_dump())

        if bucket is not None:
            buckets = {bucket: buckets.get(bucket, [])}

        items = [row for name in BUCKET_ORDER for row in buckets.get(name, [])]
        return {
            "order": [name for name in BUCKET_ORDER if name in buckets],
            "buckets": buckets,
            "items": items,
            "counts": {name: len(rows) for name, rows in buckets.items()},
            "total": sum(len(rows) for rows in buckets.values()),
            "status_filter": status,
            "generated_at": now_iso(),
        }

    # ── Transitions ──────────────────────────────────────────────────────────

    async def _transition(
        self,
        exception_id: str,
        target: ExceptionStatus,
        *,
        actor_id: str,
        event_type: str,
        action: str,
        mutate: Optional[Any] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> OperationalException:
        """Apply one audited state transition, or refuse it."""
        row = await self._repo.find_by_id(exception_id)
        if row is None:
            raise NotFoundError(f"kyber exception {exception_id}")
        exc = OperationalException(**row)

        allowed = _ALLOWED_TRANSITIONS.get(target, frozenset())
        if exc.status not in allowed:
            await self._audit(
                actor_id=actor_id,
                event_type=event_type,
                action=action,
                exception_id=exception_id,
                outcome="blocked",
                tenant_id=(exc.affected_tenants or [None])[0],
                metadata={"from_status": exc.status, "to_status": target},
            )
            raise BadRequestError(
                f"exception {exception_id} is {exc.status}; cannot transition to {target}"
            )

        previous = exc.status
        exc.status = target
        exc.updated_at = now_iso()
        if mutate is not None:
            mutate(exc)
        await self._repo.update(exception_id, exc.model_dump())

        await self._audit(
            actor_id=actor_id,
            event_type=event_type,
            action=action,
            exception_id=exception_id,
            tenant_id=(exc.affected_tenants or [None])[0],
            metadata={"from_status": previous, "to_status": target, **(metadata or {})},
        )
        logger.info(
            "kyber exception %s id=%s actor=%s (%s -> %s)",
            action, exception_id, actor_id, previous, target,
        )
        return exc

    async def acknowledge(self, exception_id: str, *, actor_id: str) -> OperationalException:
        """Claim an exception. It stays in the queue — someone now owns it."""
        def _mutate(exc: OperationalException) -> None:
            exc.metadata = {
                **exc.metadata,
                "acknowledged_by": actor_id,
                "acknowledged_at": now_iso(),
            }

        return await self._transition(
            exception_id,
            "acknowledged",
            actor_id=actor_id,
            event_type="kyber.exception.acknowledged",
            action="acknowledge_exception",
            mutate=_mutate,
        )

    async def resolve(
        self, exception_id: str, *, actor_id: str, note: Optional[str] = None
    ) -> OperationalException:
        """Close an exception out.

        Leaves the compression set, so a recurrence of the same ``dedupe_key``
        opens a new row rather than resurrecting this one — a condition that
        comes back after a fix is new information, not a duplicate.
        """
        def _mutate(exc: OperationalException) -> None:
            exc.metadata = {
                **exc.metadata,
                "resolved_by": actor_id,
                "resolved_at": now_iso(),
                "resolution_note": note or "",
            }

        return await self._transition(
            exception_id,
            "resolved",
            actor_id=actor_id,
            event_type="kyber.exception.resolved",
            action="resolve_exception",
            mutate=_mutate,
            metadata={"note": note or ""},
        )

    async def suppress(
        self, exception_id: str, *, actor_id: str, reason: str
    ) -> OperationalException:
        """Silence an exception, with a mandatory reason.

        Suppression is the one transition that removes something from view
        without fixing it, so the reason is required and recorded. It also
        leaves the compression set: the condition recurring produces a fresh
        row, which is what stops a suppression from becoming permanent
        blindness.
        """
        if not reason or not reason.strip():
            raise BadRequestError("suppression requires a reason")

        def _mutate(exc: OperationalException) -> None:
            exc.metadata = {
                **exc.metadata,
                "suppressed_by": actor_id,
                "suppressed_at": now_iso(),
                "suppression_reason": reason,
            }

        result = await self._transition(
            exception_id,
            "suppressed",
            actor_id=actor_id,
            event_type="kyber.exception.suppressed",
            action="suppress_exception",
            mutate=_mutate,
            metadata={"reason": reason},
        )
        metrics.increment(
            "kyber_exception_suppressed_total",
            labels={"bucket": result.bucket, "severity": result.severity},
        )
        return result

    async def attach_to_incident(
        self, exception_id: str, incident_id: str
    ) -> OperationalException:
        """Link an exception to the incident that explains it."""
        row = await self._repo.find_by_id(exception_id)
        if row is None:
            raise NotFoundError(f"kyber exception {exception_id}")
        exc = OperationalException(**row)
        exc.incident_id = incident_id
        exc.updated_at = now_iso()
        await self._repo.update(exception_id, exc.model_dump())
        await self._audit(
            actor_id="system",
            actor_type="system",
            event_type="kyber.exception.attached",
            action="attach_exception_to_incident",
            exception_id=exception_id,
            tenant_id=(exc.affected_tenants or [None])[0],
            metadata={"incident_id": incident_id},
        )
        return exc

    # ── Aggregates for the briefing ──────────────────────────────────────────

    async def open_counts_by_bucket(self) -> dict[str, int]:
        """Live exception counts per bucket, for the operator briefing."""
        rows = await self._repo.list_by_status("open", limit=2000)
        counts = {name: 0 for name in BUCKET_ORDER}
        for row in rows:
            bucket = str(row.get("bucket") or "informational")
            counts[bucket] = counts.get(bucket, 0) + 1
        return counts


def _union(current: list[str], incoming: list[str]) -> list[str]:
    """Order-preserving union. Reach only ever grows under compression."""
    merged = list(current)
    for value in incoming or []:
        if value not in merged:
            merged.append(value)
    return merged


#: Process-wide singleton. Worker O2 and the routes both call this.
exception_service = ExceptionService()

__all__ = [
    "OPEN_EXCEPTION_STATUSES",
    "TERMINAL_STATUSES",
    "ExceptionService",
    "exception_service",
]
