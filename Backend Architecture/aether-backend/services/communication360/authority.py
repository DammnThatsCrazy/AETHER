"""Delegation authority — pure evaluation of agent-mediated communication scope (R4, §24).

Phase 5 of the Communication360 convergence program. This module is PURE LOGIC:
no DB, no network, no repository imports, and no import of the delegation engine
(it consumes only the delegation *outcome* the engine produces — ``allowed`` —
plus the frozen Phase-3 :class:`AuthorityEvaluation` contract).

Decision-log #6 mapping
-----------------------
The delegation engine's ``allowed`` outcome maps onto the canonical
:class:`AuthorityState` vocabulary of the frozen :class:`AuthorityEvaluation`
contract:

* ``allowed is True``  → :attr:`AuthorityState.GRANTED`  (confidence 1.0)
* ``allowed is False`` → :attr:`AuthorityState.DENIED`   (confidence 1.0)
* ``allowed is None``  → :attr:`AuthorityState.UNKNOWN`  (confidence 0.0 —
  the delegation outcome was genuinely not observed, never a silent grant)

:attr:`AuthorityState.PARTIAL` and :attr:`AuthorityState.DEGRADED` are RESERVED
for scope- and amount-limited grants (e.g. ``services/delegation`` scope
``max_amount`` or a resource-pattern restriction). A bare delegation ``allowed``
boolean cannot express them; they are produced only through
:func:`authority_state_for` with an explicit ``partial`` / ``degraded`` flag.
:func:`evaluate_authority` therefore only ever emits GRANTED / DENIED / UNKNOWN.

Role guard
----------
:func:`acting_within_scope` is the minimal participant-binding guard: an agent
holding :class:`~services.communication360.contracts.ParticipantBinding` role
``role`` over the communication scope may act only when the delegation outcome
is a grant. It never widens a denial.

Epistemic discipline (R1)
-------------------------
The evaluation mirrors an *observed* delegation outcome, so ``claim_state`` is
:attr:`EpistemicStatus.OBSERVED` — never in the factual band and never
self-escalated from a delivery/engagement signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Union

from services.communication360.contracts import (
    AuthorityEvaluation,
    AuthorityState,
    ParticipantBinding,
)
from shared.contracts_models.epistemic import EpistemicStatus

#: Statuses that must never appear on an authority evaluation.
FACTUAL_BAND: frozenset[EpistemicStatus] = frozenset(
    {
        EpistemicStatus.VERIFIED,
        EpistemicStatus.RESOLVED,
        EpistemicStatus.CAUSALLY_SUPPORTED,
    }
)

#: Epistemic status of an observed delegation-outcome evaluation (R1).
EVALUATION_CLAIM_STATE: EpistemicStatus = EpistemicStatus.OBSERVED

#: Confidence carried by an explicit (observed) delegation decision.
EXPLICIT_DECISION_CONFIDENCE: float = 1.0

#: Confidence carried when the delegation outcome was not observed.
UNKNOWN_DECISION_CONFIDENCE: float = 0.0


def authority_state_for(
    *,
    allowed: Optional[bool],
    partial: bool = False,
    degraded: bool = False,
) -> AuthorityState:
    """Map a delegation outcome (+ explicit scope-limitation flags) to a state.

    ``partial`` / ``degraded`` are reserved for scope-/amount-limited grants and
    must be declared explicitly — a bare ``allowed`` boolean never implies them.
    """
    if degraded:
        return AuthorityState.DEGRADED
    if partial:
        return AuthorityState.PARTIAL
    if allowed is True:
        return AuthorityState.GRANTED
    if allowed is False:
        return AuthorityState.DENIED
    return AuthorityState.UNKNOWN


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_authority(
    *,
    agent_entity_id: str,
    communication_scope: str,
    communication_scope_kind: str,
    delegation_allowed: Optional[bool] = None,
    delegation_grant_id: Optional[str] = None,
    reason: Optional[str] = None,
    tenant_id: Optional[str] = None,
    evaluation_id: Optional[str] = None,
    evaluated_at: Optional[str] = None,
) -> AuthorityEvaluation:
    """Evaluate delegation authority for an agent-mediated communication.

    Mirrors the ``services/delegation`` engine outcome (``allowed``) onto the
    frozen :class:`AuthorityEvaluation` contract. ``tenant_id`` is required
    (the record is tenant-scoped; it is never fabricated).
    """
    if not tenant_id:
        raise ValueError(
            "evaluate_authority requires tenant_id — AuthorityEvaluation is a "
            "tenant-scoped canonical record and no tenant may be invented"
        )
    if not agent_entity_id:
        raise ValueError("evaluate_authority requires agent_entity_id")

    decision = authority_state_for(allowed=delegation_allowed)
    confidence = (
        EXPLICIT_DECISION_CONFIDENCE
        if decision is not AuthorityState.UNKNOWN
        else UNKNOWN_DECISION_CONFIDENCE
    )

    return AuthorityEvaluation(
        evaluation_id=evaluation_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        agent_entity_id=agent_entity_id,
        communication_scope=communication_scope,
        communication_scope_kind=communication_scope_kind,
        delegation_grant_id=delegation_grant_id,
        decision=decision,
        reason=reason,
        evaluated_at=evaluated_at or _utc_now(),
        claim_state=EVALUATION_CLAIM_STATE,
        confidence=confidence,
    )


def _binding_role(
    binding: Union[ParticipantBinding, dict[str, Any]],
) -> Any:
    if isinstance(binding, ParticipantBinding):
        return binding.role
    if isinstance(binding, dict):
        return binding.get("role")
    return getattr(binding, "role", None)


def acting_within_scope(
    binding: Union[ParticipantBinding, dict[str, Any]],
    delegation_allowed: bool,
    *,
    role: str,
) -> bool:
    """Minimal role guard: may an agent holding ``role`` act under a grant?

    Returns ``True`` only when the delegation outcome is a grant AND the
    participant binding confers the requested role over the communication scope.
    ``PARTIAL`` / ``DEGRADED`` scope limitations are the caller's concern: this
    guard never widens a denial and never treats an unknown outcome as a grant.
    """
    if delegation_allowed is not True:
        return False
    if binding is None:
        return False
    bound_role = _binding_role(binding)
    if bound_role is None:
        return False
    return getattr(bound_role, "value", bound_role) == role


__all__ = [
    "EVALUATION_CLAIM_STATE",
    "EXPLICIT_DECISION_CONFIDENCE",
    "FACTUAL_BAND",
    "UNKNOWN_DECISION_CONFIDENCE",
    "acting_within_scope",
    "authority_state_for",
    "evaluate_authority",
]
