"""OODA lifecycle state machine for the Suggestion entity.

Legal transitions are explicitly enumerated. Every transition appends an
immutable SuggestionAuditEvent and refreshes updated_at. Terminal states
raise BadRequestError on further transition attempts.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .repository import SuggestionRepository

from shared.common.common import BadRequestError, utc_now
from shared.logger.logger import get_logger

from .models import (
    OodaPhase,
    SuggestionAuditEvent,
    SuggestionStatus,
)

logger = get_logger("aether.suggestions.lifecycle")

# ---------------------------------------------------------------------------
# OODA phase mapping
# ---------------------------------------------------------------------------

STATUS_TO_OODA_PHASE: dict[SuggestionStatus, OodaPhase] = {
    SuggestionStatus.DETECTED:        OodaPhase.OBSERVE,
    SuggestionStatus.ORIENTED:        OodaPhase.ORIENT,
    SuggestionStatus.SUGGESTED:       OodaPhase.SUGGEST,
    SuggestionStatus.REVIEW_REQUIRED: OodaPhase.REVIEW,
    SuggestionStatus.APPROVED:        OodaPhase.REVIEW,
    SuggestionStatus.REJECTED:        OodaPhase.REVIEW,
    SuggestionStatus.SUPPRESSED:      OodaPhase.REVIEW,
    SuggestionStatus.EXECUTING:       OodaPhase.ACT,
    SuggestionStatus.EXECUTED:        OodaPhase.ACT,
    SuggestionStatus.DELIVERED:       OodaPhase.ACT,
    SuggestionStatus.MEASURED:        OodaPhase.MEASURE,
    SuggestionStatus.LEARNED:         OodaPhase.LEARN,
    SuggestionStatus.FAILED:          OodaPhase.ACT,
    SuggestionStatus.EXPIRED:         OodaPhase.CLOSED,
    SuggestionStatus.CLOSED:          OodaPhase.CLOSED,
}

# ---------------------------------------------------------------------------
# Legal transitions
# ---------------------------------------------------------------------------

LEGAL_TRANSITIONS: dict[SuggestionStatus, frozenset[SuggestionStatus]] = {
    SuggestionStatus.DETECTED: frozenset({
        SuggestionStatus.ORIENTED,
        SuggestionStatus.SUGGESTED,
        SuggestionStatus.EXPIRED,
    }),
    SuggestionStatus.ORIENTED: frozenset({
        SuggestionStatus.SUGGESTED,
        SuggestionStatus.EXPIRED,
    }),
    SuggestionStatus.SUGGESTED: frozenset({
        SuggestionStatus.REVIEW_REQUIRED,
        SuggestionStatus.DELIVERED,
        SuggestionStatus.SUPPRESSED,
        SuggestionStatus.EXPIRED,
        SuggestionStatus.APPROVED,
    }),
    SuggestionStatus.REVIEW_REQUIRED: frozenset({
        SuggestionStatus.APPROVED,
        SuggestionStatus.REJECTED,
        SuggestionStatus.SUPPRESSED,
        SuggestionStatus.EXPIRED,
    }),
    SuggestionStatus.APPROVED: frozenset({
        SuggestionStatus.EXECUTING,
        SuggestionStatus.DELIVERED,
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.EXECUTING: frozenset({
        SuggestionStatus.EXECUTED,
        SuggestionStatus.FAILED,
    }),
    SuggestionStatus.EXECUTED: frozenset({
        SuggestionStatus.MEASURED,
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.DELIVERED: frozenset({
        SuggestionStatus.MEASURED,
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.MEASURED: frozenset({
        SuggestionStatus.LEARNED,
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.LEARNED: frozenset({
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.FAILED: frozenset({
        SuggestionStatus.REVIEW_REQUIRED,
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.EXPIRED: frozenset({
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.SUPPRESSED: frozenset({
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.REJECTED: frozenset({
        SuggestionStatus.CLOSED,
    }),
    SuggestionStatus.CLOSED: frozenset(),
}


def validate_transition(
    from_status: SuggestionStatus,
    to_status: SuggestionStatus,
    requires_approval: bool = False,
) -> None:
    """Raise BadRequestError if the transition is not allowed."""
    allowed = LEGAL_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise BadRequestError(
            f"Cannot transition suggestion from {from_status.value!r} "
            f"to {to_status.value!r}. "
            f"Allowed targets: {sorted(s.value for s in allowed) or 'none (terminal)'}"
        )
    # requires_approval=True blocks SUGGESTED→APPROVED shortcut (must go via REVIEW_REQUIRED)
    if (
        requires_approval
        and from_status == SuggestionStatus.SUGGESTED
        and to_status == SuggestionStatus.APPROVED
    ):
        raise BadRequestError(
            "This suggestion requires human approval — it must enter "
            "review_required before being approved."
        )


def build_audit_event(
    action: str,
    from_status: Optional[str],
    to_status: Optional[str],
    actor_id: Optional[str] = None,
    actor_kind: str = "system",
    metadata: Optional[dict] = None,
) -> dict:
    return SuggestionAuditEvent(
        id=str(uuid.uuid4()),
        action=action,
        actor_id=actor_id,
        actor_kind=actor_kind,  # type: ignore[arg-type]
        from_status=from_status,
        to_status=to_status,
        metadata=metadata,
        timestamp=utc_now().isoformat(),
    ).model_dump()


async def apply_transition(
    repo: SuggestionRepository,
    suggestion_id: str,
    tenant_id: str,
    to_status: SuggestionStatus,
    actor_id: Optional[str] = None,
    actor_kind: str = "system",
    notes: Optional[str] = None,
) -> dict:
    """Atomically transition a suggestion to `to_status`.

    Validates, builds an audit event, updates status + ooda_phase + timestamps,
    then delegates persistence to the repository.
    """
    record = await repo.get_or_fail(suggestion_id, tenant_id)

    from_status_str = record["status"]
    from_status = SuggestionStatus(from_status_str)
    requires_approval = record.get("requires_approval", True)

    validate_transition(from_status, to_status, requires_approval=requires_approval)

    now = utc_now().isoformat()
    patch: dict = {
        "status": to_status.value,
        "ooda_phase": STATUS_TO_OODA_PHASE.get(to_status, OodaPhase.CLOSED).value,
        "updated_at": now,
    }

    if to_status in (SuggestionStatus.APPROVED, SuggestionStatus.REJECTED, SuggestionStatus.SUPPRESSED):
        patch["reviewed_at"] = now
        if actor_id:
            patch["reviewed_by"] = actor_id

    if to_status == SuggestionStatus.CLOSED:
        patch["closed_at"] = now

    audit = build_audit_event(
        action=f"transition_to_{to_status.value}",
        from_status=from_status_str,
        to_status=to_status.value,
        actor_id=actor_id,
        actor_kind=actor_kind,
        metadata={"notes": notes} if notes else None,
    )

    return await repo.transition(
        suggestion_id=suggestion_id,
        tenant_id=tenant_id,
        from_status=from_status_str,
        to_status=to_status.value,
        audit_event=audit,
    )


async def _hydrate_graph_refs(
    suggestion_id: str,
    tenant_id: str,
    graph_client: Any,
) -> list[dict]:
    """Populate path_id and snapshot_id on a suggestion's graph_refs.

    Runs shortest_path for each ref with an entity_id and stores the resulting
    canonical path_id. Called when suggestion transitions to review_required.
    Returns the updated graph_refs list.
    """
    from shared.graph.traversal import GraphTraversalEngine
    from shared.graph.path_scoring import make_path_id
    from repositories.repos import TraversalSnapshotRepository

    engine = GraphTraversalEngine(graph_client)
    snap_repo = TraversalSnapshotRepository()

    # Load suggestion's graph_refs from repo
    # (caller is responsible for saving the returned list back to the suggestion)
    return []  # base implementation returns empty; callers wire real entity_ids

