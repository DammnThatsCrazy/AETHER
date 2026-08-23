"""Stage-boundary failures: card-linked import session.

Pipeline: receive (create session) -> validate -> normalize (approved) ->
COMMITTING entry (active_commit_id) -> Bronze+graph staging -> project ->
reconcile -> COMPLETED. Failure recovery path: FAILED -> requeue -> resume
under the SAME commit id; hard-terminal DEAD_LETTERED.

Boundary recovery asserted:

  * FSM: an illegal transition raises ConflictError (the FSM never fabricates
    an un-permitted advance).
  * crash at the staging boundary: the crash records FAILED + retry_count and
    keeps the deterministic active_commit_id; a requeue + replay resumes under
    the SAME commit id and produces exactly one commit row — no duplicate.
  * hard crash (stranded COMMITTING): a session left mid-commit is requeueable
    once stale, while a fresh COMMITTING is NOT requeueable (a live commit is
    never double-run).
  * sweeper boundary: an exhausted FAILED session is dead-lettered (terminal);
    a human-waiting state is never touched.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parents[1] / "adversarial"
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

import faultkit  # noqa: E402
from faultkit import WORKER_CRASH, arm_func, make_fault  # noqa: E402
from repositories.imports_repo import get_imports_repository  # noqa: E402
from services.card_linked_payments.import_session import (  # noqa: E402
    MAX_SESSION_RETRIES,
    ImportSessionState,
    is_dead_letterable,
    is_requeueable,
    is_stranded_committing,
    require_transition,
)
from services.imports.commit import commit_import  # noqa: E402
from services.imports.session_persistence import (  # noqa: E402
    requeue_session,
    sweep_stranded_sessions,
    transition_session,
)
from shared.common.common import utc_now  # noqa: E402

import services.imports.commit as commit_mod  # noqa: E402
import services.imports.service as svc  # noqa: E402

TENANT = "t_fault_clip"
CSV = b"entity_id,name\nentity_1,Alice\nentity_2,Bob\n"
MAPPING = [
    {
        "source_column": "entity_id",
        "primitive": "entity",
        "target_field": "external_id",
        "required": True,
    }
]


def _repo():
    return get_imports_repository()


async def _drive_to_approved() -> str:
    session = await svc.create_import(TENANT)
    import_id = session["id"]
    await svc.store_file(TENANT, import_id, filename="batch.csv", content=CSV, content_type="text/csv")
    await svc.analyze_import(TENANT, import_id)
    await svc.set_mapping(TENANT, import_id, MAPPING)
    result = await svc.validate_import(TENANT, import_id)
    assert result["status"] == "validated"
    await svc.approve_import(TENANT, import_id)
    return import_id


# ── FSM boundary ────────────────────────────────────────────────────────

def test_fsm_boundary_illegal_transition_raises_conflict():
    from services.card_linked_payments.import_session import ImportSessionState as S

    with pytest.raises(Exception) as ei:
        require_transition(S.UPLOADED, S.COMMITTING)
    assert "illegal import-session transition" in str(ei.value)


# ── crash at the staging boundary ───────────────────────────────────────

@pytest.mark.asyncio
async def test_crash_at_staging_boundary_fails_then_resumes_same_commit_id():
    import_id = await _drive_to_approved()

    real_stage = commit_mod._stage_and_mutate
    injector = faultkit.FaultInjector(make_fault(WORKER_CRASH), mode="once")
    commit_mod._stage_and_mutate = arm_func(real_stage, injector)

    exc = await faultkit.expect_fault(commit_import(TENANT, import_id), WORKER_CRASH)
    assert faultkit.classify(exc) == WORKER_CRASH

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "FAILED"
    assert session["retry_count"] == 1  # crash is counted, never silently dropped
    assert "worker_crash" in session["failure_reason"]
    commit_id_on_failure = session["active_commit_id"]
    assert commit_id_on_failure  # deterministic commit id persisted at entry

    # Restart: requeue + replay resumes under the SAME commit id.
    commit_mod._stage_and_mutate = real_stage
    await requeue_session(_repo(), TENANT, import_id, requested_by="ops")
    record = await commit_import(TENANT, import_id)

    session = await _repo().get_session_any(import_id)
    assert session["lifecycle_state"] == "COMPLETED"
    assert session["status"] == "committed"
    assert session["retry_count"] == 1  # preserved across the retry
    assert record["commit_id"] == commit_id_on_failure  # resumed, not duplicated

    commits = await _repo().list_commits(TENANT, import_id)
    assert len(commits) == 1  # exactly one commit row, idempotently upserted
    assert commits[0]["commit_id"] == commit_id_on_failure


# ── hard crash (stranded COMMITTING) boundary ───────────────────────────

@pytest.mark.asyncio
async def test_stranded_committing_resume_boundary_and_live_protection():
    import_id = await _drive_to_approved()

    # Fresh COMMITTING = a live commit is in progress -> NOT requeueable.
    await transition_session(
        _repo(), TENANT, import_id, ImportSessionState.COMMITTING,
        patch={"active_commit_id": "impc_live", "commit_started_at": utc_now().isoformat()},
    )
    live = await _repo().get_session_any(import_id)
    assert is_stranded_committing(live) is False
    assert is_requeueable(live) is False
    with pytest.raises(Exception):
        await requeue_session(_repo(), TENANT, import_id, requested_by="ops")

    # A hard crash leaves COMMITTING stale -> requeueable, and the resume keeps
    # the same active_commit_id (never forked).
    stale_at = (datetime.now(timezone.utc) - timedelta(seconds=3600)).isoformat()
    await transition_session(
        _repo(), TENANT, import_id, ImportSessionState.COMMITTING,
        patch={"active_commit_id": "impc_hard", "commit_started_at": stale_at},
    )
    stranded = await _repo().get_session_any(import_id)
    assert is_stranded_committing(stranded) is True
    assert is_requeueable(stranded) is True

    requeued = await requeue_session(_repo(), TENANT, import_id, requested_by="ops")
    assert lifecycle_state(requeued) == "COMMITTING"
    assert requeued["active_commit_id"] == "impc_hard"  # same id, resumable


def lifecycle_state(session: dict) -> str:
    return session.get("lifecycle_state", "")


# ── sweeper / dead-letter boundary ──────────────────────────────────────

@pytest.mark.asyncio
async def test_sweeper_boundary_exhausted_failed_dead_letters_human_states_untouched():
    exhausted_id = await _drive_to_approved()
    await transition_session(
        _repo(), TENANT, exhausted_id, ImportSessionState.FAILED,
        patch={"retry_count": MAX_SESSION_RETRIES, "failure_reason": "repeated failures"},
    )
    exhausted = await _repo().get_session_any(exhausted_id)
    assert is_dead_letterable(exhausted) is True

    # A CREATED (human-waiting) session is never a sweeper target.
    waiting_id = (await svc.create_import(TENANT))["id"]
    assert is_dead_letterable(await _repo().get_session_any(waiting_id)) is False

    summary = await sweep_stranded_sessions(_repo())
    assert exhausted_id in summary["dead_lettered_session_ids"]
    assert waiting_id not in summary["dead_lettered_session_ids"]

    dead = await _repo().get_session_any(exhausted_id)
    assert dead["lifecycle_state"] == "DEAD_LETTERED"  # hard terminal
    assert is_requeueable(dead) is False  # never silently re-run
    with pytest.raises(Exception):
        await requeue_session(_repo(), TENANT, exhausted_id, requested_by="ops")

    # The human-waiting session is untouched.
    assert (await _repo().get_session_any(waiting_id))["lifecycle_state"] == "CREATED"
