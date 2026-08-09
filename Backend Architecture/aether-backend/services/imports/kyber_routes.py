"""
Aether Service — Import Engine Kyber Operator Routes

Cross-tenant operator surface for the Tenant Import Engine. Every endpoint is
gated fail-closed by ``require_kyber_operator`` — no Aether tenant (including
role-admins) can reach them. Kyber is the internal operator console; these
routes never expose one tenant's data to another tenant.

Endpoints:
    GET  /v1/kyber/imports/timeline              Cross-tenant import sessions feed
    GET  /v1/kyber/imports/{import_id}           A single import (any tenant) + commits
    POST /v1/kyber/imports/{import_id}/requeue   Recover a failed / stranded-committing import
    POST /v1/kyber/imports/sweep-stranded        Run one session-sweeper pass (dead-letter)

The requeue surface is backed by the import-session FSM (program sec16): a
``FAILED`` session and a ``COMMITTING`` session stranded past its requeue
window (crash recovery) are both requeueable; a COMPLETED / DEAD_LETTERED /
ROLLED_BACK session is not. ``failure_reason`` and ``retry_count`` are
preserved across requeues for audit.

Only ``router`` is exported; mounting is done by main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from repositories.imports_repo import get_imports_repository
from services.security.request_context import require_kyber_operator
from shared.common.common import APIResponse, ConflictError, NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.imports.kyber_routes")
router = APIRouter(prefix="/v1/kyber/imports", tags=["Imports (Kyber)"])


@router.get("/timeline")
async def imports_timeline(
    request: Request,
    actor=Depends(require_kyber_operator),
    limit: int = Query(100, ge=1, le=500),
):
    """Newest-first import-session feed across all tenants (operator-only)."""
    sessions = await get_imports_repository().list_all_sessions(limit=limit)
    return APIResponse(
        data={"count": len(sessions), "sessions": sessions}
    ).to_dict()


@router.get("/{import_id}")
async def import_detail(
    import_id: str,
    request: Request,
    actor=Depends(require_kyber_operator),
):
    """A single import's session + commit history, regardless of tenant."""
    repo = get_imports_repository()
    session = await repo.get_session_any(import_id)
    if session is None:
        raise NotFoundError("import session")
    commits = await repo.list_commits(session["tenant_id"], import_id)
    return APIResponse(
        data={"session": session, "commits": commits, "commit_count": len(commits)}
    ).to_dict()


@router.post("/sweep-stranded")
async def sweep_stranded_imports(
    request: Request,
    actor=Depends(require_kyber_operator),
):
    """Run one import-session sweeper pass (operator-triggered).

    Dead-letters FAILED sessions whose retry budget is exhausted and sessions
    stranded in an in-flight state past the hard deadline (crash recovery gone
    cold). States waiting on a human are never touched. The supervisor also
    runs this hook periodically (see wiringNeeds for ``build_sweeper_coro``).
    """
    from services.imports.session_persistence import sweep_stranded_sessions

    report = await sweep_stranded_sessions(get_imports_repository())
    metrics.increment(
        "import_kyber_sweeps_total",
        value=report.get("dead_lettered", 0),
    )
    return APIResponse(data=report).to_dict()


@router.post("/{import_id}/requeue")
async def requeue_import(
    import_id: str,
    request: Request,
    actor=Depends(require_kyber_operator),
):
    """Recover a recoverable import and re-enqueue the durable commit job.

    Backed by the import-session FSM: a ``FAILED`` session and a ``COMMITTING``
    session stranded past its requeue window (crash recovery) are requeueable;
    COMPLETED / DEAD_LETTERED / ROLLED_BACK are not. ``failure_reason`` and
    ``retry_count`` are preserved for audit; the mapping and validation are
    unchanged (they are stored), so this is a safe replay of a commit that
    failed mid-flight. The requeued session lands in ``COMMITTING`` and the
    resumable ``commit_import`` re-stages idempotently under the same commit id.
    """
    from services.imports.session_persistence import requeue_session

    repo = get_imports_repository()
    session = await repo.get_session_any(import_id)
    if session is None:
        raise NotFoundError("import session")
    tenant_id = session["tenant_id"]

    try:
        await requeue_session(
            repo, tenant_id, import_id, requested_by=actor.actor_id
        )
    except ConflictError as exc:
        raise ConflictError(
            f"cannot requeue import session {import_id}: {exc}"
        )

    from services.jobs.service import get_jobs_service

    job = await get_jobs_service().enqueue(
        tenant_id,
        "import.commit",
        {"import_id": import_id},
        idempotency_key=f"import-commit-requeue:{import_id}:{actor.actor_id}",
        requested_by=actor.actor_id,
    )
    metrics.increment("import_kyber_requeued_total")
    logger.info("kyber requeued import %s (tenant %s) by %s", import_id, tenant_id, actor.actor_id)
    return APIResponse(data={"import_id": import_id, "job": job}).to_dict()
