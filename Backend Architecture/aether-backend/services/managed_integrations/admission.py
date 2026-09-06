"""Reconciled Control Plane — §16 integration admission engine (Phase 3).

The admission engine registers integrations that arrive from the existing
authorities (SDK installs, provider connections, connectors, imports, feeds)
and drives each one through the §16 admission lifecycle:

    discover -> understand -> classify -> reconcile_source_authority ->
    authorize -> simulate -> approve -> compile -> activate -> observe

``observe`` is the admission *terminal* — at that point the continuous
lifecycle takes over (monitor -> drift -> reconcile -> change / review /
suspend / revoke), which is the loop §16 labels "continuous":

* ``STAGE_ADJACENCY`` is the drawn order and nothing else — a stage advances
  to exactly the next canonical stage; there is no skipping, no invented
  re-entry, and no move out of ``observe``. Illegal moves raise
  (``validate_stage_move``) before anything is persisted.
* ``CONT_LIFECYCLE_EDGES`` are the drawn continuous-lifecycle edges:
  ``monitor -> drift -> reconcile``, then ``reconcile -> change / review /
  suspend / revoke``; ``change`` and ``review`` close back into ``monitor``
  while ``suspend`` and ``revoke`` have NO auto-exit (operator-governed).
* Every move is persisted through ``admission_repository`` — an admission
  record is a lifecycle fact, and reaching ``activate`` is the only thing that
  sets ``active``; reaching ``observe`` leaves it as-is.

CP-03 boundary — admission never equals authorization: "Discovery never equals
authorization" (CP-03) and "capability never equals enablement" (CP-04) hold
throughout this module. An admission record is a §16 lifecycle fact, never an
enablement — the engine only advances lifecycle position on its own row; it
grants no actuator authority, executes no ChangeSet, flips no provider
capability, and never reads the reconcile/execution stores it is not given.
Nothing here schedules, subscribes or auto-runs; all Reconciled Control Plane
flags default OFF and this module runs only when a caller drives it. ``actor``
is accepted so a later append-only audit surface can attribute each move —
the Phase-3 record itself is the lifecycle fact (the Phase-3 §16 surface has
no audit column and none is invented here).

Sections cited: §16 (admission lifecycle), §17 (discovery precedes admission),
CP-03 / CP-04 (discovery/capability never equal authorization/enablement).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.managed_integrations.admission_repository import (
    AdmissionRecordView,
    get_admission_record_repository,
)
from services.managed_integrations.contracts import (
    ADMISSION_STAGES,
    CONTINUOUS_LIFECYCLE_ACTIONS,
    INTEGRATION_SOURCE_ORIGINS,
    is_admission_stage,
)

# ── §16 drawn stage order (the blueprint's line, no skipping, no re-entry) ──

# Every stage advances to exactly the next canonical stage; ``observe`` maps to
# None because it is the admission terminal — the continuous lifecycle (below)
# takes over from there. This adjacency is derived from the shared §16 contract
# order so a contract revision can never silently diverge from the drawn line.
_STAGE_SEQUENCE: tuple[str, ...] = ADMISSION_STAGES
STAGE_ADJACENCY: dict[str, Optional[str]] = dict(
    zip(_STAGE_SEQUENCE, (*_STAGE_SEQUENCE[1:], None))
)

# ── §16 drawn continuous-lifecycle edges ─────────────────────────────────────
# monitor -> drift -> reconcile -> change / review / suspend / revoke; change
# and review close back into monitoring (the "continuous" loop); suspend and
# revoke have NO auto-exit — they are operator-governed.
CONT_LIFECYCLE_EDGES: dict[str, frozenset[str]] = {
    "monitor": frozenset({"drift"}),
    "drift": frozenset({"reconcile"}),
    "reconcile": frozenset({"change", "review", "suspend", "revoke"}),
    "change": frozenset({"monitor"}),
    "review": frozenset({"monitor"}),
    "suspend": frozenset(),
    "revoke": frozenset(),
}


def validate_stage_move(from_stage: str, to_stage: str) -> None:
    """Raise ``ValueError`` unless ``from_stage -> to_stage`` is the one drawn
    §16 adjacency step (fail closed: no skipping, no reverse, no re-entry, no
    move out of the ``observe`` terminal, no unknown stage token)."""
    if (
        not is_admission_stage(from_stage)
        or not is_admission_stage(to_stage)
        or STAGE_ADJACENCY.get(from_stage) != to_stage
    ):
        raise ValueError(
            f"illegal §16 admission stage move {from_stage} -> {to_stage} "
            "(admission advances one canonical stage at a time: discover -> "
            "understand -> classify -> reconcile_source_authority -> "
            "authorize -> simulate -> approve -> compile -> activate -> "
            "observe; observe is the admission terminal)"
        )


def validate_lifecycle_move(from_state: str, to_state: str) -> None:
    """Raise ``ValueError`` unless ``from_state -> to_state`` is a drawn §16
    continuous-lifecycle edge (fail closed: unknown tokens, skipped edges and
    moves out of ``suspend``/``revoke`` all raise)."""
    if (
        from_state not in CONTINUOUS_LIFECYCLE_ACTIONS
        or to_state not in CONTINUOUS_LIFECYCLE_ACTIONS
        or to_state not in CONT_LIFECYCLE_EDGES.get(from_state, frozenset())
    ):
        raise ValueError(
            f"illegal §16 continuous-lifecycle move {from_state} -> {to_state} "
            "(drawn edges only: monitor -> drift -> reconcile -> "
            "change/review/suspend/revoke, then change -> monitor and "
            "review -> monitor; suspend and revoke have no auto-exit)"
        )


def next_stage(stage: str) -> Optional[str]:
    """The one canonical §16 stage reachable from ``stage`` (None for unknown
    tokens and for ``observe`` — the admission terminal)."""
    return STAGE_ADJACENCY.get(stage)


@dataclass(frozen=True)
class IntegrationAdmissionFacts:
    """The evidence-bearing source facts an admission record is born from
    (§16 / §17): which integration was discovered, from which source, in which
    tenant/environment. The row created from these facts is a lifecycle fact
    only (CP-03) — it never authorizes anything."""

    managed_integration_ref: str
    tenant_id: str
    environment_id: str
    source_ref: str
    integration_kind: str
    source_origin: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_facts(facts: IntegrationAdmissionFacts) -> None:
    """Fail closed on facts that cannot be registered (§16 source origins)."""
    if facts.source_origin not in INTEGRATION_SOURCE_ORIGINS:
        raise ValueError(
            f"unknown §16 integration source_origin {facts.source_origin!r} "
            f"(admission facts must name a §6 source origin)"
        )


async def get_or_create(
    facts: IntegrationAdmissionFacts,
    *,
    at: Optional[datetime] = None,
) -> dict:
    """Register one integration for §16 admission — idempotent.

    Creates the admission record at the §16 entry position (``discover`` /
    ``monitor`` / ``active=false``) when no record exists for the (tenant,
    environment, integration); otherwise returns the existing record unchanged.
    The repo's plain INSERT is the SQL guard against a duplicate — the unique
    (tenant, env, integration) index means only one admission per integration.
    """
    _validate_facts(facts)
    repo = get_admission_record_repository()
    existing = await repo.get_for_integration(
        tenant_id=facts.tenant_id,
        environment_id=facts.environment_id,
        managed_integration_ref=facts.managed_integration_ref,
    )
    if existing is not None:
        return existing
    at = at or _now()
    return await repo.create(
        AdmissionRecordView(
            admission_id=f"adm_{uuid.uuid4().hex[:16]}",
            managed_integration_ref=facts.managed_integration_ref,
            tenant_id=facts.tenant_id,
            environment_id=facts.environment_id,
            source_ref=facts.source_ref,
            integration_kind=facts.integration_kind,
            source_origin=facts.source_origin,
            current_stage="discover",
            lifecycle_state="monitor",
            active=False,
            created_at=at,
            updated_at=at,
        )
    )


async def admit(
    facts: IntegrationAdmissionFacts,
    *,
    actor: str = "operator",
    at: Optional[datetime] = None,
) -> dict:
    """§16 engine entry point: admit a discovered integration (CP-03 boundary —
    this registers the lifecycle fact only). Idempotent: re-admission of an
    already-registered integration returns the existing record.
    """
    return await get_or_create(facts, at=at)


async def _require_record(
    *,
    tenant_id: str,
    environment_id: str,
    admission_id: str,
) -> dict:
    """The record a move operates on — absent records fail closed (§16)."""
    row = await get_admission_record_repository().get(
        tenant_id=tenant_id,
        environment_id=environment_id,
        admission_id=admission_id,
    )
    if row is None:
        raise ValueError(
            f"no §16 admission record for admission_id={admission_id!r} "
            f"(tenant {tenant_id!r}, environment {environment_id!r}) — "
            "admit the integration first"
        )
    return row


async def advance_stage(
    *,
    tenant_id: str,
    environment_id: str,
    admission_id: str,
    actor: str = "operator",
    at: Optional[datetime] = None,
) -> dict:
    """Advance one admission record exactly one §16 adjacency step.

    Illegal moves raise before anything is persisted: an unknown or terminal
    position, or any skip/reverse, never reaches the repository. Reaching
    ``activate`` sets ``active=True`` (the only thing that does); reaching
    ``observe`` leaves ``active`` as-is (the continuous lifecycle takes over).
    """
    row = await _require_record(
        tenant_id=tenant_id,
        environment_id=environment_id,
        admission_id=admission_id,
    )
    stage = str(row["current_stage"])
    if not is_admission_stage(stage):
        raise ValueError(
            f"illegal §16 admission stage move {stage!r} -> *: unknown stage "
            "token on the record — fail closed"
        )
    to_stage = STAGE_ADJACENCY[stage]
    if to_stage is None:
        raise ValueError(
            f"illegal §16 admission stage move {stage} -> <terminal>: observe "
            "is the admission terminal and advances no further — the "
            "continuous lifecycle takes over"
        )
    validate_stage_move(stage, to_stage)
    return await get_admission_record_repository().update_stage(
        tenant_id=tenant_id,
        environment_id=environment_id,
        admission_id=admission_id,
        current_stage=to_stage,
        active=True if to_stage == "activate" else None,
        at=at,
    )


async def set_lifecycle_state(
    *,
    tenant_id: str,
    environment_id: str,
    admission_id: str,
    to_state: str,
    actor: str = "operator",
    at: Optional[datetime] = None,
) -> dict:
    """Move an admitted integration along a drawn §16 continuous-lifecycle edge.

    The move is validated against the record's *current* ``lifecycle_state``
    (``CONT_LIFECYCLE_EDGES``) before anything is persisted — e.g. ``monitor
    -> reconcile`` (skipping drift) and ``reconcile -> approve`` (approve is an
    admission stage, not a continuous action) both raise.
    """
    row = await _require_record(
        tenant_id=tenant_id,
        environment_id=environment_id,
        admission_id=admission_id,
    )
    from_state = str(row["lifecycle_state"])
    validate_lifecycle_move(from_state, to_state)
    return await get_admission_record_repository().update_stage(
        tenant_id=tenant_id,
        environment_id=environment_id,
        admission_id=admission_id,
        current_stage=str(row["current_stage"]),
        lifecycle_state=to_state,
        at=at,
    )


async def activate(
    *,
    tenant_id: str,
    environment_id: str,
    admission_id: str,
    actor: str = "operator",
    at: Optional[datetime] = None,
) -> dict:
    """Convenience: drive an admitted integration to ``activate`` (``active``
    becomes True).

    Guarded by §16 legality — activation requires the full walk, so the record
    must already sit at ``compile`` (a record at any earlier stage must be
    advanced one adjacency step at a time, and an already-activated record
    raises rather than re-entering the line). Fails closed before any persist.
    """
    row = await _require_record(
        tenant_id=tenant_id,
        environment_id=environment_id,
        admission_id=admission_id,
    )
    if str(row["current_stage"]) != "compile":
        raise ValueError(
            f"illegal §16 activation: record {admission_id!r} is at "
            f"{row['current_stage']!r}, not 'compile' — activation requires "
            "the full admission walk (compile -> activate is the only legal "
            "entry)"
        )
    return await advance_stage(
        tenant_id=tenant_id,
        environment_id=environment_id,
        admission_id=admission_id,
        actor=actor,
        at=at,
    )


__all__ = [
    "CONT_LIFECYCLE_EDGES",
    "STAGE_ADJACENCY",
    "IntegrationAdmissionFacts",
    "activate",
    "admit",
    "advance_stage",
    "get_or_create",
    "next_stage",
    "set_lifecycle_state",
    "validate_lifecycle_move",
    "validate_stage_move",
]
