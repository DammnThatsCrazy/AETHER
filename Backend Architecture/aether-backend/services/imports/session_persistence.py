"""Import-session program-field persistence + guarded FSM transitions.

Durable home of the program-spec import-session lifecycle
(``services/card_linked_payments/import_session``). Every transition is
guarded by the FSM — an illegal move raises ``ConflictError`` before any write
— and every transition persists the *full* program-required field set
(``failure_reason``, ``retry_count``, projection/reconciliation state, the
accepted/rejected/duplicate/quarantine counts, ``schema_version`` and
``source_checksum``) onto the session row.

The session row is a JSONB BaseRepository row, so these are JSONB fields — no
DDL change is required for them. ``sweep_stranded_sessions`` is the session-
level sweeper hook (dead-letters budget-exhausted / hard-stranded sessions);
the supervisor wires it via ``build_sweeper_coro`` (see wiringNeeds).

The commit arc itself lives in ``services/imports/commit.py`` (resumable
``commit_import``); this module is the persistence + policy seam beneath it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from repositories.imports_repo import get_imports_repository
from services.card_linked_payments.import_session import (
    ImportSessionState,
    is_dead_letterable,
    is_requeueable,
    legacy_status_for,
    lifecycle_state_of,
    new_session_fields,
    require_transition,
)
from shared.common.common import ConflictError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.imports.session_persistence")

# Bounded scan for the sweeper so a single pass can never scan an unbounded
# table in one query (raise via config when the fleet grows).
_SWEEP_SCAN_LIMIT = 5_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_program_fields(
    repo: Any, tenant_id: str, import_id: str
) -> dict:
    """Idempotently merge the program-required field defaults onto a session.

    Reads the session (tenant-guarded), fills any missing program fields, and
    writes them back only when something changed. Safe on legacy sessions.
    """
    session = await repo.get_session(tenant_id, import_id)
    missing = {k: v for k, v in new_session_fields().items() if k not in session}
    if missing:
        return await repo.update_session(tenant_id, import_id, **missing)
    return session


async def transition_session(
    repo: Any,
    tenant_id: str,
    import_id: str,
    target: ImportSessionState,
    *,
    patch: Optional[dict] = None,
    legacy_status: Optional[str] = None,
) -> dict:
    """A guarded FSM transition that persists the target state atomically.

    ``patch`` merges arbitrary program fields onto the row; ``legacy_status``
    overrides the default parity-safe ``status`` projection (used for
    ``partially_committed`` on a COMPLETED commit with row errors).
    Raises ``ConflictError`` when the FSM forbids the move — nothing is written.
    """
    session = await repo.get_session(tenant_id, import_id)
    current = lifecycle_state_of(session)
    require_transition(current, target)

    patch = dict(patch or {})
    patch["lifecycle_state"] = target.value
    patch["status"] = legacy_status or legacy_status_for(target)
    # ``updated_at`` is owned by BaseRepository (rewritten on every write), so
    # the FSM does not touch it — stranded-commit detection anchors on the
    # dedicated ``commit_started_at`` field instead.
    return await repo.update_session(tenant_id, import_id, **patch)


async def mark_failed(
    repo: Any,
    tenant_id: str,
    import_id: str,
    *,
    failure_reason: str,
    exc: Optional[BaseException] = None,
) -> dict:
    """Persist a failure on the session: FAILED + failure_reason + retry_count.

    ``retry_count`` is incremented (never reset) so the retry budget and the
    sweeper see cumulative attempts; ``failure_reason`` records the most recent
    failure and is *preserved* across requeues (never auto-cleared). A session
    already in DEAD_LETTERED / ROLLED_BACK refuses the write (ConflictError).
    """
    session = await repo.get_session(tenant_id, import_id)
    detail = f": {type(exc).__name__}: {exc}" if exc is not None else ""
    reason = f"{failure_reason}{detail}" if detail else failure_reason
    retry_count = int(session.get("retry_count", 0) or 0) + 1
    return await transition_session(
        repo,
        tenant_id,
        import_id,
        ImportSessionState.FAILED,
        patch={
            "failure_reason": reason,
            "retry_count": retry_count,
            "failed_at": _now_iso(),
        },
    )


async def requeue_session(
    repo: Any,
    tenant_id: str,
    import_id: str,
    *,
    requested_by: Optional[str] = None,
) -> dict:
    """Requeue a recoverable session for another commit attempt.

    ``FAILED`` is always requeueable; a stranded ``COMMITTING`` (no live worker,
    past the requeue window) is requeueable too. Both land back in COMMITTING;
    ``failure_reason`` / ``retry_count`` are preserved for audit. Any other
    state (COMPLETED / DEAD_LETTERED / ROLLED_BACK / in-flight-but-not-stranded)
    raises ``ConflictError``.
    """
    session = await repo.get_session(tenant_id, import_id)
    if not is_requeueable(session):
        state = lifecycle_state_of(session)
        raise ConflictError(
            f"cannot requeue import session in state "
            f"{state.value if state else 'UNKNOWN'!r} "
            "(requeueable: FAILED, or COMMITTING past its requeue window)"
        )
    requeued = await transition_session(
        repo,
        tenant_id,
        import_id,
        ImportSessionState.COMMITTING,
        patch={
            "requeued_at": _now_iso(),
            "last_requeued_by": requested_by,
        },
    )
    metrics.increment("import_session_requeued_total")
    logger.info(
        "requeued import session %s (tenant %s, by %s)",
        import_id, tenant_id, requested_by,
    )
    return requeued


async def dead_letter_session(
    repo: Any,
    tenant_id: str,
    import_id: str,
    *,
    reason: str,
) -> dict:
    """Move a session to DEAD_LETTERED (operator / sweeper terminal stop)."""
    return await transition_session(
        repo,
        tenant_id,
        import_id,
        ImportSessionState.DEAD_LETTERED,
        patch={
            "failure_reason": reason,
            "dead_lettered_at": _now_iso(),
        },
    )


async def sweep_stranded_sessions(
    repo: Any,
    *,
    scan_limit: int = _SWEEP_SCAN_LIMIT,
    now: Optional[datetime] = None,
) -> dict:
    """Session-level sweeper hook: dead-letter recoverable-but-exhausted rows.

    Two classes are dead-lettered:
      * ``FAILED`` sessions whose ``retry_count`` reached the retry budget;
      * sessions stranded in an in-flight state (COMMITTING / PROJECTING /
        RECONCILING / NORMALIZING / VALIDATING) past the hard deadline — an
        unrecorded crash leaves no failure_reason, so staleness alone is the
        signal.
    States waiting on a human (CREATED / UPLOADED / VALIDATED / REJECTED) and
    hard-terminal states are never touched. Returns the scan/dead-letter counts
    for the operator surface and metrics.
    """
    now = now or datetime.now(timezone.utc)
    rows = await repo.sessions.find_many(filters=None, limit=scan_limit)
    dead_lettered: list[str] = []
    for row in rows:
        tenant_id = row.get("tenant_id")
        import_id = row.get("id")
        if not tenant_id or not import_id:
            continue
        if not is_dead_letterable(row, now=now):
            continue
        try:
            await dead_letter_session(
                repo,
                tenant_id,
                import_id,
                reason=(
                    "session retry budget exhausted; dead-lettered by import "
                    "session sweeper"
                ),
            )
            dead_lettered.append(import_id)
        except ConflictError:
            continue  # raced to a terminal state — nothing to do
    metrics.gauge(
        "import_session_sweeper_scanned", float(len(rows)),
    )
    metrics.gauge(
        "import_session_sweeper_dead_lettered", float(len(dead_lettered)),
    )
    logger.info(
        "import session sweeper pass: scanned=%s dead_lettered=%s",
        len(rows), len(dead_lettered),
    )
    return {
        "scanned": len(rows),
        "dead_lettered": len(dead_lettered),
        "dead_lettered_session_ids": dead_lettered,
    }


def build_sweeper_coro(repo: Any = None, *, poll_interval_s: int = 3600):
    """Zero-arg coroutine factory for supervisor wiring (same shape as the
    job-lease sweeper). Runs one sweep per poll; errors are logged and the
    loop continues; cancellation propagates."""
    import asyncio

    async def _sweep_forever() -> None:
        while True:
            try:
                await sweep_stranded_sessions(repo or get_imports_repository())
            except Exception as exc:  # noqa: BLE001 — a sweep pass must never kill the supervisor
                logger.error(
                    "import-session sweeper pass crashed",
                    extra={"error": str(exc)},
                )
            await asyncio.sleep(poll_interval_s)

    return _sweep_forever()


__all__ = [
    "ensure_program_fields",
    "transition_session",
    "mark_failed",
    "requeue_session",
    "dead_letter_session",
    "sweep_stranded_sessions",
    "build_sweeper_coro",
]
