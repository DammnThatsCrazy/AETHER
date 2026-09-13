"""Card-linked import-session state machine (program sec16).

The canonical import-session lifecycle per the program spec — an explicit
enum/FSM with a full vocabulary and *legal transitions*:

    CREATED → UPLOADED → VALIDATING → VALIDATED → NORMALIZING → COMMITTING
                                        ↓             │
                                      REJECTED        ↓
                                          PROJECTING → RECONCILING → COMPLETED
    any in-flight state → FAILED → COMMITTING (retry) / DEAD_LETTERED
    COMPLETED → ROLLED_BACK

The program vocabulary is authoritative (``lifecycle_state``). A legacy
lowercase ``status`` is *projected* alongside it so the TS frontend (which
zod-enforces the parity-locked ``ImportStatus`` enum) and the existing
commit/approve surface keep working unchanged — a program state with no
direct legacy equivalent maps to the nearest member of ``IMPORT_STATUSES``.

This module is pure (no repository I/O) so the whole FSM is unit-testable in
isolation. Durable transitions live in
``services/imports/session_persistence.py``; ``commit_import`` in
``services/imports/commit.py`` drives the commit arc resumably.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from shared.common.common import ConflictError
from shared.temporal.instant import coerce_utc_lenient

# ── the vocabulary ───────────────────────────────────────────────────────────


class ImportSessionState(str, Enum):
    """Full program-spec import-session lifecycle vocabulary.

    ``COMMITTING`` is re-entrant (a crash mid-commit leaves the session in
    ``COMMITTING``; a restart or operator requeue *resumes* it — the self arc
    touches the session so the sweeper grants a fresh window). ``FAILED`` is
    retryable; the sweeper dead-letters a session only once its retry budget
    is exhausted or it is stranded in an in-flight state past a hard deadline.
    """

    CREATED = "CREATED"  # session row created; no bytes yet
    UPLOADED = "UPLOADED"  # file bytes persisted (sha256 recorded)
    VALIDATING = "VALIDATING"  # dry-run validation running
    VALIDATED = "VALIDATED"  # validation passed (maybe awaiting approval)
    REJECTED = "REJECTED"  # validation failed; re-upload / re-validate to proceed
    NORMALIZING = "NORMALIZING"  # approved; records being built from the mapping
    COMMITTING = "COMMITTING"  # Bronze + graph staging in progress (re-entrant)
    PROJECTING = "PROJECTING"  # Silver / graph projection in progress
    RECONCILING = "RECONCILING"  # reconciliation against provider evidence
    COMPLETED = "COMPLETED"  # terminal success (fully staged)
    FAILED = "FAILED"  # terminal failure (retryable up to the retry budget)
    DEAD_LETTERED = "DEAD_LETTERED"  # retry budget / hard deadline exhausted
    ROLLED_BACK = "ROLLED_BACK"  # a committed session was rolled back


ALL_STATES: frozenset[str] = frozenset(state.value for state in ImportSessionState)

# ── legal transitions ────────────────────────────────────────────────────────
#
# Every arc is directed and explicit. There is no implicit transition: moving a
# session to a state not listed here raises ConflictError at the persistence
# layer, so no caller can silently skip a stage.

_TRANSITIONS: dict[ImportSessionState, frozenset[ImportSessionState]] = {
    ImportSessionState.CREATED: frozenset(
        {ImportSessionState.UPLOADED, ImportSessionState.FAILED,
         ImportSessionState.DEAD_LETTERED, ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.UPLOADED: frozenset(
        # self arc = a tenant adds another file to the same import.
        {ImportSessionState.UPLOADED, ImportSessionState.VALIDATING,
         ImportSessionState.FAILED, ImportSessionState.DEAD_LETTERED,
         ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.VALIDATING: frozenset(
        {ImportSessionState.UPLOADED, ImportSessionState.VALIDATED,
         ImportSessionState.REJECTED, ImportSessionState.FAILED,
         ImportSessionState.DEAD_LETTERED, ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.VALIDATED: frozenset(
        # approve → NORMALIZING; a re-validation replays VALIDATING; a
        # re-validation that now fails → REJECTED; adding another file returns
        # to UPLOADED (the whole batch is re-validated).
        {ImportSessionState.UPLOADED, ImportSessionState.NORMALIZING,
         ImportSessionState.VALIDATING, ImportSessionState.REJECTED,
         ImportSessionState.FAILED, ImportSessionState.DEAD_LETTERED,
         ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.REJECTED: frozenset(
        {ImportSessionState.UPLOADED, ImportSessionState.VALIDATING,
         ImportSessionState.FAILED, ImportSessionState.DEAD_LETTERED,
         ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.NORMALIZING: frozenset(
        {ImportSessionState.COMMITTING, ImportSessionState.FAILED,
         ImportSessionState.DEAD_LETTERED, ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.COMMITTING: frozenset(
        # self arc = resume a stranded commit (crash recovery / requeue).
        {ImportSessionState.COMMITTING, ImportSessionState.PROJECTING,
         ImportSessionState.FAILED, ImportSessionState.DEAD_LETTERED,
         ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.PROJECTING: frozenset(
        {ImportSessionState.RECONCILING, ImportSessionState.FAILED,
         ImportSessionState.DEAD_LETTERED, ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.RECONCILING: frozenset(
        {ImportSessionState.COMPLETED, ImportSessionState.FAILED,
         ImportSessionState.DEAD_LETTERED, ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.COMPLETED: frozenset({ImportSessionState.ROLLED_BACK}),
    ImportSessionState.FAILED: frozenset(
        {ImportSessionState.COMMITTING, ImportSessionState.DEAD_LETTERED,
         ImportSessionState.ROLLED_BACK}
    ),
    ImportSessionState.DEAD_LETTERED: frozenset(),
    ImportSessionState.ROLLED_BACK: frozenset(),
}

# States that are hard stops — no further transition is ever legal.
TERMINAL_STATES: frozenset[str] = frozenset(
    {ImportSessionState.DEAD_LETTERED.value, ImportSessionState.ROLLED_BACK.value}
)

# States whose process left no live worker (an operator/sweeper may act on them).
IN_FLIGHT_STATES: frozenset[str] = frozenset(
    {s.value for s in ImportSessionState}
    - TERMINAL_STATES
    - {ImportSessionState.CREATED.value, ImportSessionState.UPLOADED.value,
       ImportSessionState.VALIDATED.value, ImportSessionState.REJECTED.value}
)

# ── time windows ─────────────────────────────────────────────────────────────
# A ``COMMITTING`` session is *stranded* (requeueable) once it has been sitting
# in that state longer than this — long enough that any live worker would have
# marked the session failed (or completed) first. Kept far below the sweeper's
# hard dead-letter deadline so a stranded commit is recoverable, not terminal.
REQUEUE_COMMITTING_TIMEOUT_S: int = 300
# A session stranded in an in-flight state (COMMITTING/PROJECTING/RECONCILING/
# NORMALIZING/VALIDATING) past this hard deadline is dead-lettered by the
# sweeper regardless of recorded failures (an unrecorded crash leaves no
# failure_reason, so the sweeper must act on staleness alone).
SWEEPER_DEAD_LETTER_TIMEOUT_S: int = 24 * 60 * 60
# Recorded-failure budget. A session that reaches this many failed commit
# attempts is dead-lettered rather than retried forever.
MAX_SESSION_RETRIES: int = 5

# ── legacy projection ────────────────────────────────────────────────────────
# The parity-locked ``ImportStatus`` enum (services/imports/contracts.py +
# packages/shared/imports.ts) has no NORMALIZING/PROJECTING/RECONCILING/
# REJECTED/DEAD_LETTERED/COMPLETED. The legacy ``status`` field stays a member
# of that enum so the TS zod schema keeps parsing; the FSM is authoritative.
_LEGACY_PROJECTION: dict[ImportSessionState, str] = {
    ImportSessionState.CREATED: "created",
    ImportSessionState.UPLOADED: "uploaded",
    ImportSessionState.VALIDATING: "validating",
    ImportSessionState.VALIDATED: "validated",
    ImportSessionState.REJECTED: "review_required",
    ImportSessionState.NORMALIZING: "approved",
    ImportSessionState.COMMITTING: "committing",
    ImportSessionState.PROJECTING: "committing",
    ImportSessionState.RECONCILING: "committing",
    ImportSessionState.COMPLETED: "committed",
    ImportSessionState.FAILED: "failed",
    ImportSessionState.DEAD_LETTERED: "failed",
    ImportSessionState.ROLLED_BACK: "rolled_back",
}

# Reverse map for adopting pre-FSM sessions (best-effort; unknown statuses
# collapse to CREATED so a never-driven session stays inert).
_LEGACY_TO_STATE: dict[str, ImportSessionState] = {
    "created": ImportSessionState.CREATED,
    "files_pending": ImportSessionState.CREATED,
    "uploaded": ImportSessionState.UPLOADED,
    "analyzing": ImportSessionState.UPLOADED,
    "analyzed": ImportSessionState.UPLOADED,
    "mapping": ImportSessionState.UPLOADED,
    "mapped": ImportSessionState.UPLOADED,
    "validating": ImportSessionState.VALIDATING,
    "validated": ImportSessionState.VALIDATED,
    "review_required": ImportSessionState.VALIDATED,
    "approved": ImportSessionState.NORMALIZING,
    "committing": ImportSessionState.COMMITTING,
    "committed": ImportSessionState.COMPLETED,
    "partially_committed": ImportSessionState.COMPLETED,
    "failed": ImportSessionState.FAILED,
    "cancelled": ImportSessionState.ROLLED_BACK,
    "rolled_back": ImportSessionState.ROLLED_BACK,
}

# ── program-required session fields ──────────────────────────────────────────
# Defaults merged into every session row so the operator surface and the
# scorecard can rely on the fields being present (idempotent reads).
DEFAULT_SESSION_FIELDS: dict[str, object] = {
    "lifecycle_state": ImportSessionState.CREATED.value,
    "failure_reason": None,
    "retry_count": 0,
    "projection_state": "none",  # none | pending | completed | dead_lettered
    "reconciliation_state": "none",  # none | pending_provider_corroboration | cleared | drift
    "accepted_count": 0,
    "rejected_count": 0,
    "duplicate_count": 0,
    "quarantine_count": 0,
    "schema_version": None,
    "source_checksum": None,
    "commit_started_at": None,  # anchor for stranded-commit detection
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── FSM primitives ───────────────────────────────────────────────────────────


def can_transition(current: Optional[ImportSessionState], target: ImportSessionState) -> bool:
    """True when the FSM permits ``current -> target`` (or ``current`` is
    unknown, in which case only the initial state is allowed)."""
    if current is None:
        return target is ImportSessionState.CREATED
    return target in _TRANSITIONS.get(current, frozenset())


def require_transition(
    current: Optional[ImportSessionState], target: ImportSessionState
) -> None:
    """Raise ``ConflictError`` when the FSM forbids ``current -> target``."""
    if not can_transition(current, target):
        if current is None:
            raise ConflictError(
                f"import session has no lifecycle state; only {ImportSessionState.CREATED.value} "
                "is reachable — the session is outside the program FSM"
            )
        raise ConflictError(
            f"illegal import-session transition {current.value!r} -> {target.value!r}"
        )


def is_terminal(state: Optional[ImportSessionState]) -> bool:
    """True when the state is a hard stop (dead-lettered / rolled back)."""
    return state is not None and state.value in TERMINAL_STATES


def is_in_flight(state: Optional[ImportSessionState]) -> bool:
    """True when the state is one a worker is (or was) actively driving."""
    return state is not None and state.value in IN_FLIGHT_STATES


def legacy_status_for(state: ImportSessionState) -> str:
    """The parity-safe legacy ``status`` value for a program state."""
    return _LEGACY_PROJECTION[state]


def lifecycle_state_of(session: dict) -> Optional[ImportSessionState]:
    """The authoritative program state of a session row.

    Reads ``lifecycle_state`` first; falls back to a best-effort adoption from
    the legacy lowercase ``status`` for sessions created before the FSM, and
    to ``None`` when neither maps (a session the FSM must not drive).
    """
    raw = session.get("lifecycle_state")
    if raw is not None:
        try:
            return ImportSessionState(str(raw))
        except ValueError:
            pass
    legacy = str(session.get("status") or "")
    return _LEGACY_TO_STATE.get(legacy)


def _parse_iso(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = coerce_utc_lenient(parsed)
    return parsed


def stale_for(session: dict, now: Optional[datetime] = None, timeout_s: int = 0) -> bool:
    """True when the session's ``updated_at`` is older than ``timeout_s``.

    Malformed/absent timestamps are treated as stale so a single bad row can
    never pin a session in an in-flight state forever.
    """
    now = now or _utc_now()
    updated = _parse_iso(session.get("updated_at"))
    if updated is None:
        return True
    return (now - updated).total_seconds() > timeout_s


def commit_stale_for(session: dict, now: Optional[datetime] = None, timeout_s: int = 0) -> bool:
    """Staleness anchored on ``commit_started_at`` (falling back to
    ``updated_at``).

    ``BaseRepository.update`` rewrites ``updated_at`` on every write, so it is
    a poor anchor for a *stranded commit*: an unrelated session write (or the
    self-arc refresh on resume) would mask a commit that died mid-stage. The
    commit's own start time survives those writes — a hard crash leaves it in
    the past; a live worker refreshing it keeps the sweeper/requeue from
    acting. ``commit_import`` sets/refreshes it on every COMMITTING entry.
    """
    now = now or _utc_now()
    anchor = _parse_iso(session.get("commit_started_at"))
    if anchor is None:
        anchor = _parse_iso(session.get("updated_at"))
    if anchor is None:
        return True
    return (now - anchor).total_seconds() > timeout_s


def is_stranded_committing(
    session: dict,
    now: Optional[datetime] = None,
    timeout_s: int = REQUEUE_COMMITTING_TIMEOUT_S,
) -> bool:
    """True when the session is in ``COMMITTING`` and past the requeue window.

    Guards the operator requeue surface so a live worker still driving the
    commit is never double-run; the job-worker retry path does not use this
    guard (it resumes on every re-invocation, bounded by the retry budget).
    """
    if lifecycle_state_of(session) is not ImportSessionState.COMMITTING:
        return False
    return commit_stale_for(session, now=now, timeout_s=timeout_s)


def is_requeueable(
    session: dict,
    now: Optional[datetime] = None,
    committing_timeout_s: int = REQUEUE_COMMITTING_TIMEOUT_S,
) -> bool:
    """True when an operator may requeue the session.

    ``FAILED`` is always requeueable (explicit operator action); a stranded
    ``COMMITTING`` is requeueable once its requeue window has elapsed. Sessions
    in any other state — including DEAD_LETTERED / ROLLED_BACK / COMPLETED —
    are not requeueable.
    """
    state = lifecycle_state_of(session)
    if state is ImportSessionState.FAILED:
        return True
    return is_stranded_committing(session, now=now, timeout_s=committing_timeout_s)


def is_dead_letterable(
    session: dict,
    now: Optional[datetime] = None,
    hard_timeout_s: int = SWEEPER_DEAD_LETTER_TIMEOUT_S,
    max_retries: int = MAX_SESSION_RETRIES,
) -> bool:
    """True when the sweeper should dead-letter the session.

    Two conditions: (a) a ``FAILED`` session whose recorded-failure budget is
    exhausted, or (b) a session stranded in an in-flight state past the hard
    deadline (an unrecorded crash leaves no failure_reason, so the sweeper must
    act on staleness alone). Never dead-letters a state waiting on a human
    (CREATED / UPLOADED / VALIDATED / REJECTED).
    """
    state = lifecycle_state_of(session)
    if state is ImportSessionState.FAILED:
        return int(session.get("retry_count", 0) or 0) >= max_retries
    if state is not None and is_in_flight(state):
        return commit_stale_for(session, now=now, timeout_s=hard_timeout_s)
    return False


def new_session_fields(*, extra: Optional[dict] = None) -> dict:
    """A fresh program-field block for a newly created session row."""
    fields = dict(DEFAULT_SESSION_FIELDS)
    fields["retry_count"] = 0
    if extra:
        fields.update(extra)
    return fields


__all__ = [
    "ImportSessionState",
    "ALL_STATES",
    "TERMINAL_STATES",
    "IN_FLIGHT_STATES",
    "REQUEUE_COMMITTING_TIMEOUT_S",
    "SWEEPER_DEAD_LETTER_TIMEOUT_S",
    "MAX_SESSION_RETRIES",
    "DEFAULT_SESSION_FIELDS",
    "can_transition",
    "require_transition",
    "is_terminal",
    "is_in_flight",
    "legacy_status_for",
    "lifecycle_state_of",
    "stale_for",
    "commit_stale_for",
    "is_stranded_committing",
    "is_requeueable",
    "is_dead_letterable",
    "new_session_fields",
]
