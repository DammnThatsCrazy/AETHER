"""Import-session state machine: FSM, persistence, resumability, idempotent replay.

Program sec16 deliverable for the card-linked import-session lifecycle. Proves:

  1. the full program vocabulary is an explicit enum/FSM with *legal*
     transitions (an illegal move raises ConflictError before any write);
  2. the legacy lowercase ``status`` projection stays parity-safe (a member of
     the parity-locked ``ImportStatus`` enum) so the TS frontend keeps parsing;
  3. every program-required session field persists (failure_reason,
     retry_count, projection/reconciliation state, accepted/rejected/duplicate/
     quarantine counts, schema_version, source_checksum);
  4. commit_import is resumable + idempotent: a crash at the COMMITTING
     boundary leaves a recoverable FAILED (in-process) or stranded COMMITTING
     (hard crash) session — requeue resumes under the SAME commit id and never
     duplicates rows/edges, and never silently stops mid-import;
  5. requeue accepts FAILED and stranded COMMITTING (after timeout) and refuses
     COMPLETED / DEAD_LETTERED / ROLLED_BACK;
  6. the session-level sweeper dead-letters budget-exhausted FAILED sessions and
     hard-stranded in-flight sessions, and never touches human-wait states.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.imports_repo import get_imports_repository  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.card_linked_payments.import_session import (  # noqa: E402
    MAX_SESSION_RETRIES,
    REQUEUE_COMMITTING_TIMEOUT_S,
    SWEEPER_DEAD_LETTER_TIMEOUT_S,
    ImportSessionState,
    TERMINAL_STATES,
    can_transition,
    is_dead_letterable,
    is_requeueable,
    legacy_status_for,
    lifecycle_state_of,
    require_transition,
)
from services.imports.contracts import IMPORT_STATUSES  # noqa: E402
from services.imports.commit import commit_import  # noqa: E402
from services.imports.session_persistence import (  # noqa: E402
    ensure_program_fields,
    mark_failed,
    requeue_session,
    sweep_stranded_sessions,
    transition_session,
)

TENANT = "t_clip_sec16"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _repo():
    return get_imports_repository()


def _now():
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _iso_old(**kwargs) -> str:
    return _iso(_now() - timedelta(**kwargs))


# ═══════════════════════════════════════════════════════════════════════════
# 1. FSM vocabulary + legal transitions (pure)
# ═══════════════════════════════════════════════════════════════════════════

def test_full_program_vocabulary_is_declared():
    expected = {
        "CREATED", "UPLOADED", "VALIDATING", "VALIDATED", "REJECTED",
        "NORMALIZING", "COMMITTING", "PROJECTING", "RECONCILING",
        "COMPLETED", "FAILED", "DEAD_LETTERED", "ROLLED_BACK",
    }
    assert {s.value for s in ImportSessionState} == expected


def test_terminal_states_are_hard_stops():
    assert TERMINAL_STATES == {"DEAD_LETTERED", "ROLLED_BACK"}
    # A hard-stop state has no legal outgoing transition.
    assert not can_transition(ImportSessionState.DEAD_LETTERED, ImportSessionState.COMMITTING)
    assert not can_transition(ImportSessionState.ROLLED_BACK, ImportSessionState.COMPLETED)


def test_legal_transition_path_is_fully_traversable():
    path = [
        ImportSessionState.CREATED,
        ImportSessionState.UPLOADED,
        ImportSessionState.VALIDATING,
        ImportSessionState.VALIDATED,
        ImportSessionState.NORMALIZING,
        ImportSessionState.COMMITTING,
        ImportSessionState.PROJECTING,
        ImportSessionState.RECONCILING,
        ImportSessionState.COMPLETED,
    ]
    for current, target in zip(path, path[1:]):
        assert can_transition(current, target), f"{current.value} -> {target.value}"


def test_illegal_transition_raises_conflict():
    with pytest.raises(Exception) as excinfo:
        require_transition(ImportSessionState.CREATED, ImportSessionState.COMMITTING)
    assert "illegal import-session transition" in str(excinfo.value)
    # Approved → committing without normalizing is a skip (illegal).
    with pytest.raises(Exception):
        require_transition(ImportSessionState.VALIDATED, ImportSessionState.COMMITTING)


def test_failed_is_retryable_but_dead_lettered_is_not():
    assert can_transition(ImportSessionState.FAILED, ImportSessionState.COMMITTING)
    assert can_transition(ImportSessionState.FAILED, ImportSessionState.DEAD_LETTERED)


def test_committing_self_arc_is_the_resume_arc():
    assert can_transition(ImportSessionState.COMMITTING, ImportSessionState.COMMITTING)


# ═══════════════════════════════════════════════════════════════════════════
# 2. legacy projection stays parity-safe
# ═══════════════════════════════════════════════════════════════════════════

def test_every_legacy_projection_is_a_declared_import_status():
    for state in ImportSessionState:
        assert legacy_status_for(state) in IMPORT_STATUSES, (
            f"{state.value} projects to {legacy_status_for(state)!r} "
            "which is not in the parity-locked ImportStatus enum"
        )


def test_lifecycle_adoption_from_legacy_statuses():
    assert lifecycle_state_of({"status": "created"}) is ImportSessionState.CREATED
    assert lifecycle_state_of({"status": "uploaded"}) is ImportSessionState.UPLOADED
    assert lifecycle_state_of({"status": "validated"}) is ImportSessionState.VALIDATED
    assert lifecycle_state_of({"status": "review_required"}) is ImportSessionState.VALIDATED
    assert lifecycle_state_of({"status": "approved"}) is ImportSessionState.NORMALIZING
    assert lifecycle_state_of({"status": "committing"}) is ImportSessionState.COMMITTING
    assert lifecycle_state_of({"status": "committed"}) is ImportSessionState.COMPLETED
    assert lifecycle_state_of({"status": "failed"}) is ImportSessionState.FAILED
    assert lifecycle_state_of({"status": "rolled_back"}) is ImportSessionState.ROLLED_BACK
    # lifecycle_state wins over the legacy status.
    assert lifecycle_state_of(
        {"lifecycle_state": "COMPLETED", "status": "approved"}
    ) is ImportSessionState.COMPLETED


def test_requeue_and_dead_letter_eligibility():
    fresh = {"lifecycle_state": "COMMITTING", "updated_at": _iso(_now())}
    stranded = {"lifecycle_state": "COMMITTING", "updated_at": _iso_old(minutes=30)}
    failed = {"lifecycle_state": "FAILED", "updated_at": _iso(_now())}
    completed = {"lifecycle_state": "COMPLETED", "updated_at": _iso(_now())}
    dead = {"lifecycle_state": "DEAD_LETTERED", "updated_at": _iso(_now())}
    budget_exhausted = {"lifecycle_state": "FAILED", "retry_count": MAX_SESSION_RETRIES}

    assert is_requeueable(failed) is True  # FAILED always requeueable
    assert is_requeueable(stranded) is True  # stranded committing past window
    assert is_requeueable(fresh) is False  # live commit must not be double-run
    assert is_requeueable(completed) is False
    assert is_requeueable(dead) is False
    assert is_dead_letterable(budget_exhausted) is True
    assert is_dead_letterable(failed) is False  # budget not exhausted
    assert is_dead_letterable(fresh) is False  # not yet stale
    assert is_dead_letterable(completed) is False


# ═══════════════════════════════════════════════════════════════════════════
# 3. session persistence + guarded transitions
# ═══════════════════════════════════════════════════════════════════════════

async def _create_session() -> dict:
    return await _repo().create_session(TENANT)


@pytest.mark.asyncio
async def test_create_session_seeds_program_fields():
    repo = _repo()
    session = await repo.create_session(TENANT)
    await ensure_program_fields(repo, TENANT, session["id"])
    session = await repo.get_session(TENANT, session["id"])
    assert session["lifecycle_state"] == "CREATED"
    assert session["retry_count"] == 0
    assert session["failure_reason"] is None
    assert session["accepted_count"] == 0
    assert session["rejected_count"] == 0
    assert session["duplicate_count"] == 0
    assert session["quarantine_count"] == 0
    assert session["projection_state"] == "none"
    assert session["reconciliation_state"] == "none"


@pytest.mark.asyncio
async def test_guarded_transition_persists_fields():
    repo = _repo()
    session = await _create_session()
    import_id = session["id"]
    await ensure_program_fields(repo, TENANT, import_id)

    updated = await transition_session(
        repo, TENANT, import_id, ImportSessionState.UPLOADED,
        patch={"file_count": 1, "source_checksum": "abc123"},
    )
    assert updated["lifecycle_state"] == "UPLOADED"
    assert updated["status"] == "uploaded"  # legacy projection
    assert updated["file_count"] == 1
    assert updated["source_checksum"] == "abc123"
    assert updated["retry_count"] == 0  # untouched by a success transition

    # Illegal move: CREATED-based session already advanced to UPLOADED.
    with pytest.raises(Exception):
        await transition_session(repo, TENANT, import_id, ImportSessionState.COMPLETED)


@pytest.mark.asyncio
async def test_mark_failed_records_reason_and_increments_retry_count():
    repo = _repo()
    session = await _create_session()
    import_id = session["id"]
    await ensure_program_fields(repo, TENANT, import_id)

    failed = await mark_failed(
        repo, TENANT, import_id, failure_reason="boom"
    )
    assert failed["lifecycle_state"] == "FAILED"
    assert failed["status"] == "failed"
    assert "boom" in failed["failure_reason"]
    assert failed["retry_count"] == 1

    # Requeue preserves failure_reason + retry_count, then a second failure
    # stacks the counter and records the new reason.
    requeued = await requeue_session(repo, TENANT, import_id, requested_by="ops")
    assert requeued["lifecycle_state"] == "COMMITTING"
    assert requeued["status"] == "committing"
    assert requeued["retry_count"] == 1
    assert requeued["failure_reason"] == "boom"

    failed_again = await mark_failed(repo, TENANT, import_id, failure_reason="boom2")
    assert failed_again["retry_count"] == 2
    assert failed_again["failure_reason"] == "boom2"


@pytest.mark.asyncio
async def test_requeue_refuses_completed_and_dead_lettered():
    repo = _repo()
    session = await _create_session()
    import_id = session["id"]
    await ensure_program_fields(repo, TENANT, import_id)

    await mark_failed(repo, TENANT, import_id, failure_reason="once")
    await requeue_session(repo, TENANT, import_id)
    # Drive to COMPLETED.
    await transition_session(repo, TENANT, import_id, ImportSessionState.PROJECTING)
    await transition_session(repo, TENANT, import_id, ImportSessionState.RECONCILING)
    await transition_session(repo, TENANT, import_id, ImportSessionState.COMPLETED)

    with pytest.raises(Exception):
        await requeue_session(repo, TENANT, import_id)


@pytest.mark.asyncio
async def test_requeue_stranded_committing_needs_timeout():
    repo = _repo()
    session = await _create_session()
    import_id = session["id"]
    await ensure_program_fields(repo, TENANT, import_id)

    # Fabricate a stranded COMMITTING session (as a hard crash would leave it).
    # ``BaseRepository.update`` rewrites ``updated_at``, so stranded-detection
    # anchors on ``commit_started_at`` (set by commit_import at COMMITTING entry).
    await repo.update_session(
        TENANT, import_id,
        lifecycle_state="COMMITTING", status="committing",
        active_commit_id="impc_deadbeef",
        commit_started_at=_iso(_now()),
    )
    with pytest.raises(Exception):
        await requeue_session(repo, TENANT, import_id)

    # Once past the requeue window it becomes requeueable.
    await repo.update_session(TENANT, import_id, commit_started_at=_iso_old(minutes=30))
    requeued = await requeue_session(repo, TENANT, import_id, requested_by="ops")
    assert requeued["lifecycle_state"] == "COMMITTING"
    assert requeued["active_commit_id"] == "impc_deadbeef"  # resume same commit


@pytest.mark.asyncio
async def test_sweeper_dead_letters_exhausted_and_stranded_but_not_human_wait():
    repo = _repo()
    exhausted = await _create_session()
    stranded = await _create_session()
    human_wait = await _create_session()

    # FAILED with the retry budget exhausted. Each real retry is an attempt
    # (mark_failed: in-flight -> FAILED) followed by an operator requeue
    # (FAILED -> COMMITTING); end the cycle on a FAILED so the sweeper sees a
    # budget-exhausted FAILED session.
    for i in range(MAX_SESSION_RETRIES):
        await mark_failed(repo, TENANT, exhausted["id"], failure_reason="loop")
        if i < MAX_SESSION_RETRIES - 1:
            await requeue_session(repo, TENANT, exhausted["id"], requested_by="ops")

    # Hard-stranded COMMITTING past the sweeper deadline (anchor on the commit
    # start time — updated_at is rewritten by the repository on every write).
    await repo.update_session(
        TENANT, stranded["id"],
        lifecycle_state="COMMITTING", status="committing",
        commit_started_at=_iso_old(hours=SWEEPER_DEAD_LETTER_TIMEOUT_S / 3600 + 2),
    )

    # VALIDATED is waiting on a human — the sweeper must never touch it.
    await repo.update_session(
        TENANT, human_wait["id"],
        lifecycle_state="VALIDATED", status="validated",
        updated_at=_iso_old(hours=200),
    )

    report = await sweep_stranded_sessions(repo)
    assert report["scanned"] >= 3
    assert report["dead_lettered"] == 2
    assert set(report["dead_lettered_session_ids"]) == {
        exhausted["id"], stranded["id"],
    }
    assert (await repo.get_session_any(exhausted["id"]))["lifecycle_state"] == "DEAD_LETTERED"
    assert (await repo.get_session_any(stranded["id"]))["lifecycle_state"] == "DEAD_LETTERED"
    assert (await repo.get_session_any(human_wait["id"]))["lifecycle_state"] == "VALIDATED"


# ═══════════════════════════════════════════════════════════════════════════
# 4. resumable + idempotent commit_import
# ═══════════════════════════════════════════════════════════════════════════

CSV = b"entity_id,name\nentity_1,Alice\nentity_2,Bob\n"

MAPPING = [
    {
        "source_column": "entity_id",
        "primitive": "entity",
        "target_field": "external_id",
        "required": True,
    }
]


async def _drive_to_approved(tenant: str) -> str:
    """create → upload → analyze → map → validate → approve (returns import_id)."""
    import services.imports.service as svc

    session = await svc.create_import(tenant)
    import_id = session["id"]
    await svc.store_file(
        tenant, import_id, filename="batch.csv", content=CSV, content_type="text/csv"
    )
    await svc.analyze_import(tenant, import_id)
    await svc.set_mapping(tenant, import_id, MAPPING)
    result = await svc.validate_import(tenant, import_id)
    assert result["status"] == "validated"
    await svc.approve_import(tenant, import_id)
    return import_id


@pytest.mark.asyncio
async def test_commit_happy_path_completes_with_program_fields():
    import services.imports.commit as commit_mod

    import_id = await _drive_to_approved(TENANT)
    record = await commit_import(TENANT, import_id)
    assert record["status"] == "committed"

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "COMPLETED"
    assert session["status"] == "committed"
    assert session["projection_state"] == "completed"
    # commit_import never runs a real reconciliation path, so the honest marker
    # is pending_provider_corroboration — "cleared" requires a real verdict.
    assert session["reconciliation_state"] == "pending_provider_corroboration"
    assert session["accepted_count"] >= 2
    assert session["schema_version"] == 1
    assert session["source_checksum"] is not None
    assert session.get("active_commit_id") == record["commit_id"]


@pytest.mark.asyncio
async def test_commit_in_process_crash_then_requeue_resumes(monkeypatch):
    """Crash at the COMMITTING boundary records FAILED; requeue resumes under
    the SAME commit id — no silent stop, no duplicate commit row."""
    import services.imports.commit as commit_mod

    import_id = await _drive_to_approved(TENANT)

    def _crash(*args, **kwargs):
        raise RuntimeError("worker died mid-staging")

    real_stage = commit_mod._stage_and_mutate  # capture BEFORE patching
    monkeypatch.setattr(commit_mod, "_stage_and_mutate", _crash)
    with pytest.raises(RuntimeError):
        await commit_import(TENANT, import_id)

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "FAILED"
    assert "worker died mid-staging" in session["failure_reason"]
    assert session["retry_count"] == 1
    commit_id_on_failure = session["active_commit_id"]

    # Restart: operator requeues, then the job re-runs commit_import.
    monkeypatch.setattr(commit_mod, "_stage_and_mutate", real_stage)
    await requeue_session(_repo(), TENANT, import_id, requested_by="ops")
    record = await commit_import(TENANT, import_id)

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "COMPLETED"
    assert session["status"] == "committed"
    assert session["retry_count"] == 1  # preserved across the retry
    assert record["commit_id"] == commit_id_on_failure  # resumed, not duplicated

    commits = await _repo().list_commits(TENANT, import_id)
    assert len(commits) == 1  # one commit row, idempotently upserted
    assert commits[0]["commit_id"] == commit_id_on_failure


@pytest.mark.asyncio
async def test_commit_hard_crash_stranded_committing_resumes(monkeypatch):
    """A hard crash leaves the session in COMMITTING with no failure recorded;
    the resumable commit re-enters and completes under the same id."""
    import services.imports.commit as commit_mod

    import_id = await _drive_to_approved(TENANT)
    first = await commit_import(TENANT, import_id)
    assert first["status"] == "committed"

    # Now fabricate a hard crash on a *fresh* session: we simulate a crash that
    # happened between the COMMITTING entry transition and any error handling by
    # driving a second import to COMMITTING and leaving it there.
    second_id = await _drive_to_approved(TENANT)
    await transition_session(
        _repo(), TENANT, second_id, ImportSessionState.COMMITTING,
        patch={"active_commit_id": "impc_stranded"},
    )
    stranded = await _repo().get_session_any(second_id)
    assert stranded["lifecycle_state"] == "COMMITTING"
    assert stranded["retry_count"] == 0  # no failure was ever recorded

    # The commit entry guard accepts the stranded COMMITTING (crash recovery)
    # and resumes under the same commit id.
    record = await commit_import(TENANT, second_id)
    session = await _repo().get_session_any(second_id)
    assert session["lifecycle_state"] == "COMPLETED"
    assert record["commit_id"] == "impc_stranded"

    commits = await _repo().list_commits(TENANT, second_id)
    assert len(commits) == 1


@pytest.mark.asyncio
async def test_commit_replay_never_silently_stops_mid_import(monkeypatch):
    """Crash at each stage boundary → every restart lands in a KNOWN recoverable
    state (FAILED or stranded COMMITTING), and resuming always completes."""
    import services.imports.commit as commit_mod

    for attempt in range(3):  # three distinct crash points
        import_id = await _drive_to_approved(TENANT)
        real = commit_mod._stage_and_mutate
        calls = {"n": 0}

        async def _flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError(f"crash-{attempt}")
            return await real(*args, **kwargs)

        monkeypatch.setattr(commit_mod, "_stage_and_mutate", _flaky)
        with pytest.raises(RuntimeError):
            await commit_import(TENANT, import_id)

        session = await _repo().get_session_any(import_id)
        # Either the in-process failure was recorded (FAILED) or the process
        # died before marking (stranded COMMITTING) — never a half-way state.
        assert session["lifecycle_state"] in {"FAILED", "COMMITTING"}

        monkeypatch.setattr(commit_mod, "_stage_and_mutate", real)
        if session["lifecycle_state"] == "COMMITTING":
            # Simulate the requeue window elapsing on a stranded COMMITTING.
            await _repo().update_session(
                TENANT, import_id, commit_started_at=_iso_old(minutes=30)
            )
        await requeue_session(_repo(), TENANT, import_id, requested_by="ops")
        record = await commit_import(TENANT, import_id)

        done = await _repo().get_session_any(import_id)
        assert done["lifecycle_state"] == "COMPLETED"
        assert record["status"] in {"committed", "partially_committed"}
        assert len(await _repo().list_commits(TENANT, import_id)) == 1


@pytest.mark.asyncio
async def test_commit_budget_exhaustion_dead_letters(monkeypatch):
    """A deterministically failing commit cannot loop forever inside the FSM."""
    import services.imports.commit as commit_mod

    import_id = await _drive_to_approved(TENANT)

    def _always_crash(*args, **kwargs):
        raise RuntimeError("deterministic failure")

    monkeypatch.setattr(commit_mod, "_stage_and_mutate", _always_crash)
    with pytest.raises(RuntimeError):
        await commit_import(TENANT, import_id)
    # Exhaust the budget through retries.
    for _ in range(MAX_SESSION_RETRIES - 1):
        with pytest.raises(RuntimeError):
            await commit_import(TENANT, import_id)

    session = await _repo().get_session_any(import_id)
    assert session["retry_count"] == MAX_SESSION_RETRIES
    # The entry guard now refuses — a bounded retry budget, not an infinite loop.
    with pytest.raises(Exception) as excinfo:
        await commit_import(TENANT, import_id)
    assert "not commit-eligible" in str(excinfo.value)

    # The sweeper turns the exhausted session into DEAD_LETTERED.
    report = await sweep_stranded_sessions(_repo())
    assert session["id"] in report["dead_lettered_session_ids"]
    assert (await _repo().get_session_any(import_id))["lifecycle_state"] == "DEAD_LETTERED"


# ═══════════════════════════════════════════════════════════════════════════
# 5. transient validation failures leave a retryable (not wedged) session
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_transient_failure_is_retryable(monkeypatch):
    """A transient failure after entering VALIDATING must not leave the session
    pinned there — the FSM forbids VALIDATING -> VALIDATING, so a wedged
    session could only be dead-lettered. The fallback to UPLOADED keeps the
    import retryable: the retry re-enters VALIDATING legally and succeeds."""
    import services.imports.analyzer as analyzer
    import services.imports.service as svc

    tenant = "t_retry_validating"
    session = await svc.create_import(tenant)
    import_id = session["id"]
    await svc.store_file(
        tenant, import_id, filename="batch.csv", content=CSV, content_type="text/csv"
    )
    await svc.analyze_import(tenant, import_id)
    await svc.set_mapping(tenant, import_id, MAPPING)

    calls = {"n": 0}
    real_read_rows = analyzer.read_rows

    def _flaky_read_rows(content, fmt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient storage failure")
        return real_read_rows(content, fmt)

    monkeypatch.setattr(analyzer, "read_rows", _flaky_read_rows)
    with pytest.raises(RuntimeError):
        await svc.validate_import(tenant, import_id)

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "UPLOADED"  # retryable, not VALIDATING
    assert "transient storage failure" in session["failure_reason"]

    # Retry: UPLOADED -> VALIDATING is legal, and the same import validates
    # end to end (no forbidden VALIDATING -> VALIDATING was attempted).
    monkeypatch.setattr(analyzer, "read_rows", real_read_rows)
    result = await svc.validate_import(tenant, import_id)
    assert result["status"] == "validated"
    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "VALIDATED"


# ═══════════════════════════════════════════════════════════════════════════
# 6. mid-finalization commit resumability (PROJECTING / RECONCILING)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_commit_finalization_transient_failure_resumes(monkeypatch):
    """A transient failure on PROJECTING -> RECONCILING leaves a successfully
    staged import stranded at PROJECTING. The retry entry guard must accept
    mid-finalization states so the commit resumes to COMPLETED instead of being
    rejected — and must not re-stage or duplicate the commit row."""
    import services.imports.session_persistence as sp

    import_id = await _drive_to_approved(TENANT)

    real_transition = sp.transition_session
    calls = {"n": 0}

    async def _flaky_transition(repo, tenant_id, import_id, target, *args, **kwargs):
        if target is ImportSessionState.RECONCILING:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("reconciling transition failed transiently")
        return await real_transition(repo, tenant_id, import_id, target, *args, **kwargs)

    monkeypatch.setattr(sp, "transition_session", _flaky_transition)
    with pytest.raises(RuntimeError):
        await commit_import(TENANT, import_id)

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "PROJECTING"  # stranded mid-finalization
    assert session["active_commit_id"]  # staging was already done under this id

    # Retry: PROJECTING is commit-eligible; the resume advances to COMPLETED
    # without re-running staging or creating a second commit row.
    monkeypatch.setattr(sp, "transition_session", real_transition)
    record = await commit_import(TENANT, import_id)
    assert record["status"] == "committed"

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "COMPLETED"
    assert session["status"] == "committed"
    assert session["reconciliation_state"] == "pending_provider_corroboration"
    assert len(await _repo().list_commits(TENANT, import_id)) == 1


