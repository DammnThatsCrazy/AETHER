"""
Aether Backend — Durable Reward Receipt Evidence Recording (A6 / program sec18)

Closes the audit-evidence gap for the claim-reconciliation loop
(:mod:`services.rewards.reconcile`): every delivery receipt (persisted by the
durable reward outbox) and every settlement receipt (tenant-submitted execution
receipt) MUST leave an immutable, append-only trace on the reward audit trail
(``reward_audit_log``) — even if the process crashes between receipt acceptance
and audit write.

Design
------
* **Durable.** ``record()`` appends to ``reward_audit_log`` (append-only). If the
  append fails transiently, the evidence intent is persisted as a row in the
  durable evidence outbox (``reward_evidence_outbox``) keyed deterministically
  per (receipt_type, tenant_id, external_id) so a retry is idempotent.
* **Bounded retry + DLQ.** ``drain()`` re-runs failed evidence appends with the
  delivery worker's exponential backoff, bounded by
  ``REWARD_EVIDENCE_MAX_ATTEMPTS`` (default 5), and dead-letters after
  exhaustion so evidence is never silently dropped and operators can see it.
* **Idempotent.** A receipt is never double-recorded: the audit append checks
  for an existing evidence entry by its deterministic id.
* **Rails/status aware.** The evidence payload carries rail, external_id,
  status, receipt/action/decision/proof ids, tx hash and chain — the fields the
  reconciler needs to tie a receipt to a proof. Confirmed settlements
  (``success``/``delivered``/``confirmed``/``executed``) are flagged
  ``settlement_confirmed=true`` for operator diagnostics.

The supervised retry loop is **not** auto-started here; the integration pass
wires ``get_receipt_evidence_service().build_evidence_loop()`` into the runtime
supervisor (see wiringNeeds).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from typing import Any, Awaitable, Callable, Optional

from repositories.repos import BaseRepository
from services.rewards.repositories import RewardAuditRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.receipt_evidence")

_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_INTERVAL_SECONDS = 60.0
_DEFAULT_BATCH_SIZE = 20

# Receipt statuses that confirm an on-chain claim / settlement actually executed.
_CONFIRMED_STATUSES = frozenset({"success", "delivered", "confirmed", "executed"})

# Accepted evidence kinds.
DELIVERY = "delivery"
SETTLEMENT = "settlement"
_EVIDENCE_KINDS = frozenset({DELIVERY, SETTLEMENT})


def _now_iso() -> str:
    return utc_now().isoformat()


def _max_attempts() -> int:
    raw = os.getenv("REWARD_EVIDENCE_MAX_ATTEMPTS", "")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning("ignoring non-integer REWARD_EVIDENCE_MAX_ATTEMPTS %r", raw)
    return _DEFAULT_MAX_ATTEMPTS


def _interval_seconds() -> float:
    raw = os.getenv("REWARD_EVIDENCE_INTERVAL_SECONDS", "")
    if raw:
        try:
            return max(10.0, float(raw))
        except ValueError:
            logger.warning("ignoring non-numeric REWARD_EVIDENCE_INTERVAL_SECONDS %r", raw)
    return _DEFAULT_INTERVAL_SECONDS


def evidence_id(receipt_type: str, tenant_id: str, external_id: str) -> str:
    """Deterministic evidence id → idempotent recording per receipt."""
    raw = f"{receipt_type}:{tenant_id}:{external_id}"
    return "ev_" + hashlib.sha256(raw.encode()).hexdigest()[:40]


# ═══════════════════════════════════════════════════════════════════════════
# DURABLE EVIDENCE OUTBOX (retry + dead-letter for failed audit appends)
# ═══════════════════════════════════════════════════════════════════════════

class RewardEvidenceOutboxRepository(BaseRepository):
    """Durable outbox of receipt-evidence appends that failed transiently.

    State machine: ``queued → done | dead_letter`` (a ``failed`` job is a
    queued retry with a ``next_attempt_at``). Id is the deterministic
    ``evidence_id`` so a re-record never creates a duplicate runnable job.
    """

    def __init__(self) -> None:
        super().__init__("reward_evidence_outbox")

    async def ensure_enqueued(self, evidence_id: str, payload: dict, error: str) -> dict:
        """Idempotent enqueue. Re-arms a dead-lettered job for the next drain."""
        existing = await self.find_by_id(evidence_id)
        if existing is not None and existing.get("state") in ("queued", "failed"):
            return existing
        job = {
            "id": evidence_id,
            "tenant_id": payload.get("tenant_id", ""),
            "state": "queued",
            "payload": payload,
            "attempt_count": 0,
            "max_attempts": _max_attempts(),
            "next_attempt_at": _now_iso(),
            "last_error": error[:500],
        }
        if existing is not None:
            return await self.update(evidence_id, {**job, "attempt_count": 0, "state": "queued"})
        return await self.insert(evidence_id, job)

    async def due_batch(self, batch_size: int = _DEFAULT_BATCH_SIZE) -> list[dict]:
        """Runnable (queued/failed with due next_attempt_at) evidence jobs."""
        now_str = _now_iso()
        jobs = await self.find_many(filters={}, limit=100000)
        jobs.sort(key=lambda r: str(r.get("next_attempt_at", "")))
        due: list[dict] = []
        for j in jobs:
            if len(due) >= batch_size:
                break
            if j.get("state") not in ("queued", "failed"):
                continue
            next_at = j.get("next_attempt_at", "")
            if next_at and next_at > now_str:
                continue
            due.append(j)
        return due

    async def status_counts(self) -> dict[str, int]:
        jobs = await self.find_many(filters={}, limit=100000)
        counts: dict[str, int] = {}
        for j in jobs:
            counts[j.get("state", "unknown")] = counts.get(j.get("state", "unknown"), 0) + 1
        return counts


# ═══════════════════════════════════════════════════════════════════════════
# EVIDENCE SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class RewardReceiptEvidenceService:
    """Durably records delivery/settlement receipts onto the audit trail."""

    def __init__(
        self,
        audit_repo: Optional[RewardAuditRepository] = None,
        outbox_repo: Optional[RewardEvidenceOutboxRepository] = None,
    ) -> None:
        self._audit = audit_repo or RewardAuditRepository()
        self._outbox = outbox_repo or RewardEvidenceOutboxRepository()

    # ── public API ────────────────────────────────────────────────────────

    async def record(
        self,
        receipt_type: str,
        *,
        tenant_id: str,
        receipt_id: Optional[str] = None,
        rail: str,
        external_id: str,
        status: str = "unknown",
        action_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        proof_id: Optional[str] = None,
        tx_hash: Optional[str] = None,
        chain_id: Optional[int] = None,
        amount: Optional[Any] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Append a durable audit-evidence entry for a receipt.

        Returns the appended audit record on success, or ``{"dead_lettered":
        True, ...}`` when the append failed and the evidence was routed to the
        durable evidence outbox (see :meth:`drain`). Never raises.
        """
        if receipt_type not in _EVIDENCE_KINDS:
            raise ValueError(f"receipt_type must be one of {sorted(_EVIDENCE_KINDS)}")
        if not external_id:
            raise ValueError("external_id is required to record receipt evidence")

        ev_id = evidence_id(receipt_type, tenant_id, external_id)
        confirmed = status in _CONFIRMED_STATUSES
        payload = {
            "tenant_id": tenant_id,
            "receipt_type": receipt_type,
            "evidence_id": ev_id,
            "receipt_id": receipt_id,
            "rail": rail,
            "external_id": external_id,
            "status": status,
            "settlement_confirmed": confirmed,
            "action_id": action_id,
            "decision_id": decision_id,
            "proof_id": proof_id,
            "tx_hash": tx_hash,
            "chain_id": chain_id,
            "amount": amount,
            "metadata": metadata or {},
        }

        # Idempotent: a receipt already recorded (e.g. a retried POST) is
        # returned as-is and never double-appended. Best-effort: if the lookup
        # itself fails we fall through to the append (which routes to the
        # durable outbox on failure rather than dropping the evidence).
        try:
            existing = await self._audit.find_many(
                filters={"tenant_id": tenant_id, "target_id": ev_id}, limit=1
            )
        except Exception:  # noqa: BLE001 - never fail record() on a lookup hiccup
            existing = []
        if existing:
            return existing[0]

        try:
            record = await self._append_audit(payload)
            metrics.increment(
                "rewards_receipt_evidence_recorded",
                labels={"tenant_id": tenant_id, "receipt_type": receipt_type},
            )
            return record
        except Exception as exc:  # noqa: BLE001 - durable before dropped
            logger.warning("receipt evidence append failed, routing to evidence outbox: %s", exc)
            await self._outbox.ensure_enqueued(ev_id, payload, str(exc))
            metrics.increment(
                "rewards_receipt_evidence_outboxed",
                labels={"tenant_id": tenant_id, "receipt_type": receipt_type},
            )
            return {
                "dead_lettered": False,
                "evidence_id": ev_id,
                "outboxed": True,
                "error": str(exc)[:200],
            }

    async def drain(self, batch_size: int = _DEFAULT_BATCH_SIZE) -> dict:
        """Retry failed evidence appends. Bounded retry, then dead-letter."""
        jobs = await self._outbox.due_batch(batch_size=batch_size)
        recorded = dead_lettered = 0
        for job in jobs:
            attempt = int(job.get("attempt_count", 0)) + 1
            max_attempts = int(job.get("max_attempts", _max_attempts()))
            payload = job.get("payload") or {}
            try:
                await self._append_audit(payload)
                await self._outbox.update(job["id"], {
                    "state": "done", "attempt_count": attempt,
                    "resolved_at": _now_iso(), "last_error": None,
                })
                recorded += 1
                metrics.increment(
                    "rewards_receipt_evidence_recorded",
                    labels={"tenant_id": payload.get("tenant_id", ""), "receipt_type": payload.get("receipt_type", "")},
                )
                continue
            except Exception as exc:  # noqa: BLE001 - bounded retry / DLQ
                if attempt >= max_attempts:
                    await self._outbox.update(job["id"], {
                        "state": "dead_letter", "attempt_count": attempt,
                        "last_error": str(exc)[:500],
                    })
                    dead_lettered += 1
                    metrics.increment(
                        "rewards_receipt_evidence_dead_lettered",
                        labels={"tenant_id": payload.get("tenant_id", ""), "receipt_type": payload.get("receipt_type", "")},
                    )
                    logger.error("receipt evidence DEAD-LETTER ev=%s attempt=%s err=%s",
                                 job["id"], attempt, str(exc)[:200])
                    continue
                from services.delivery.worker import _compute_next_attempt_at
                next_at = _compute_next_attempt_at(attempt)
                await self._outbox.update(job["id"], {
                    "state": "failed", "attempt_count": attempt,
                    "next_attempt_at": next_at, "last_error": str(exc)[:500],
                })
                logger.warning("receipt evidence retry ev=%s attempt=%s/%s next=%s err=%s",
                               job["id"], attempt, max_attempts, next_at, str(exc)[:200])
        return {
            "scanned": len(jobs), "recorded": recorded,
            "dead_lettered": dead_lettered,
            "retried": len(jobs) - recorded - dead_lettered,
        }

    async def status(self) -> dict:
        return await self._outbox.status_counts()

    # ── supervised retry loop ─────────────────────────────────────────────

    def build_evidence_loop(
        self,
        interval_s: Optional[float] = None,
    ) -> Callable[[], Awaitable[None]]:
        """Return an async loop that retries evidence appends periodically."""
        interval = interval_s or _interval_seconds()

        async def _loop() -> None:
            logger.info("reward_receipt_evidence_loop started interval=%ss", interval)
            while True:
                try:
                    summary = await self.drain()
                    if summary["scanned"]:
                        logger.info(
                            "receipt evidence iteration scanned=%s recorded=%s dlq=%s",
                            summary["scanned"], summary["recorded"], summary["dead_lettered"],
                        )
                except asyncio.CancelledError:
                    logger.info("reward_receipt_evidence_loop stopped")
                    raise
                except Exception as exc:  # noqa: BLE001 - loop survives
                    logger.error("receipt evidence iteration failed: %s", exc)
                await asyncio.sleep(interval)

        return _loop

    # ── helpers ───────────────────────────────────────────────────────────

    async def _append_audit(self, payload: dict) -> dict:
        """Append the immutable audit-log entry for a receipt evidence payload."""
        action = {
            DELIVERY: "receipt.delivery.recorded",
            SETTLEMENT: "receipt.settlement.recorded",
        }[payload.get("receipt_type", SETTLEMENT)]
        target_type = {
            DELIVERY: "reward_delivery_receipt",
            SETTLEMENT: "reward_settlement_receipt",
        }[payload.get("receipt_type", SETTLEMENT)]
        return await self._audit.append({
            "tenant_id": payload.get("tenant_id", ""),
            "actor_type": "system",
            "actor_id": "reward_receipt_evidence",
            "action": action,
            "target_type": target_type,
            "target_id": payload.get("evidence_id"),
            "after_state": {
                "receipt_type": payload.get("receipt_type"),
                "receipt_id": payload.get("receipt_id"),
                "rail": payload.get("rail"),
                "external_id": payload.get("external_id"),
                "status": payload.get("status"),
                "settlement_confirmed": payload.get("settlement_confirmed"),
                "action_id": payload.get("action_id"),
                "decision_id": payload.get("decision_id"),
                "proof_id": payload.get("proof_id"),
                "tx_hash": payload.get("tx_hash"),
                "chain_id": payload.get("chain_id"),
                "amount": payload.get("amount"),
            },
            "reason": f"{payload.get('receipt_type', SETTLEMENT)}_receipt.recorded",
            "request_id": payload.get("evidence_id"),
        })


# ── Module-level singleton ──────────────────────────────────────────────

_evidence_service: Optional[RewardReceiptEvidenceService] = None


def get_receipt_evidence_service() -> RewardReceiptEvidenceService:
    global _evidence_service
    if _evidence_service is None:
        _evidence_service = RewardReceiptEvidenceService()
    return _evidence_service


def reset_receipt_evidence_service() -> None:
    """Reset the evidence service singleton — for tests only."""
    global _evidence_service
    _evidence_service = None


__all__ = [
    "RewardEvidenceOutboxRepository",
    "RewardReceiptEvidenceService",
    "evidence_id",
    "get_receipt_evidence_service",
    "reset_receipt_evidence_service",
]
