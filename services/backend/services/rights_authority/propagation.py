"""Rights Authority → governed-write propagation PRODUCER (blueprint §11/§17 P3).

:mod:`services.rights_authority.envelope` exposes *how* a resolved
:class:`~services.rights_authority.contracts.RightsDecision` rides a spine or
graph artifact. This module is the producer that actually does it for a governed
write:

1. **resolve** — call the AUTHORITATIVE
   :class:`~services.rights_authority.resolver.EffectiveRightsResolver` (never a
   local re-implementation, never a cached guess) with the pipeline's own
   ``RightsDecisionRequest`` inputs;
2. **stamp** — put the returned durable ``rdec_...`` ``decision_id`` onto the
   write: :func:`stamp_intent` for a ``MutationIntent`` (→
   ``MutationIntent.rights_decision_ref`` → ``MutationRecord.rights_decision_ref``
   → the ``graph_mutation_ledger.rights_decision_ref`` column),
   :func:`stamp_envelope` for a ``SpineEnvelope`` (via ``apply_rights_ref`` plus
   the decision's :class:`EvidenceRef` on ``evidence_refs``).

Fail-closed doctrine, encoded structurally:

- **Nothing runs when the gate is off.** :func:`propagate_rights` returns
  ``None`` before it touches the resolver, so with ``RIGHTS_AUTHORITY_ROLLOUT``
  unset/``off`` a caller stamps nothing, records nothing and denies nothing —
  the write stays byte-identical to the pre-propagation behaviour.
- **No fabricated refs.** The only value ever stamped is a
  ``decision_id`` returned by the authoritative resolver, and only when that
  decision is an ALLOW. :func:`_require_durable_decision_id` rejects anything
  that is not a non-empty ``rdec_...`` identity, so a stub/partial resolver
  cannot smuggle a made-up governance ref onto a write.
- **Never an unresolved allow.** A denied decision is not stamped. Under
  ``enforce`` (:func:`~services.rights_authority.rollout.enforce_denials`) the
  denial *binds*: :func:`propagate_rights` raises
  :class:`RightsPropagationDenied` so the caller refuses the write instead of
  writing it with no rights ancestry. Under ``shadow`` / ``warn`` the decision
  is recorded and returned for comparison; the caller proceeds unstamped.

Blueprint §11: "Graph mutation ``MutationIntent``/``MutationRecord`` gain a
rights ref; every material derivative resolves to the rights of its upstream
evidence." §17 Phase 3 invariant: "no governed derivative loses rights
ancestry." This module is that seam's producer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.rights_authority.contracts import RightsDecision, RightsDecisionRequest
from services.rights_authority.envelope import apply_rights_ref, decision_evidence_ref
from services.rights_authority.resolver import (
    EffectiveRightsResolver,
    effective_rights_resolver,
)
from services.rights_authority.rollout import (
    RolloutMode,
    current_mode,
    enforce_denials,
    is_active,
)
from shared.graph.mutation_gateway import MutationIntent
from shared.spine.spine_envelope import SpineEnvelope

__all__ = [
    "DECISION_REF_PREFIX",
    "RightsPropagation",
    "RightsPropagationDenied",
    "USE_WRITE_TENANT_GRAPH",
    "DESTINATION_TENANT_INTERNAL",
    "propagate_rights",
    "stamp_envelope",
    "stamp_intent",
]

# Durable decision identities are minted as ``rdec_<hex>`` (contracts.py
# ``_rdec_id``). A ref that does not carry this prefix is not a durable decision
# identity and must never reach a write.
DECISION_REF_PREFIX = "rdec_"

# Canonical resolver vocabulary for a tenant-graph write: the §16 requested-use
# token (``_FAMILY_ALIASES`` maps it to the ``tenant_graph`` family) and the
# tenant-internal destination boundary. Named here so every propagating pipeline
# asks the same question and therefore replays to the same decision identity.
USE_WRITE_TENANT_GRAPH = "write_tenant_graph"
DESTINATION_TENANT_INTERNAL = "tenant_internal"


@dataclass(frozen=True)
class RightsPropagation:
    """One propagation attempt: the decision, the mode, and what got stamped.

    ``stamped`` is True only for a decision the authoritative resolver resolved
    as an ALLOW with a durable ``rdec_...`` identity — i.e. only when
    :func:`stamp_intent` / :func:`stamp_envelope` would actually write a ref.
    """

    decision: RightsDecision
    mode: RolloutMode
    stamped: bool

    @property
    def decision_id(self) -> str:
        return self.decision.decision_id

    @property
    def allowed(self) -> bool:
        return bool(self.decision.allowed)

    @property
    def reason_codes(self) -> list[str]:
        return list(self.decision.reason_codes)


class RightsPropagationDenied(Exception):
    """An ``enforce``-mode denial: the governed write must not proceed.

    Carries the full :class:`RightsDecision` (and its stable ``reason_codes``)
    so a caller can render a typed refusal with the authority's own reasons
    instead of inventing a parallel vocabulary — the same shape
    ``services.population.governance.MembershipConsentDeniedError`` uses for the
    consent gate it sits beside.
    """

    def __init__(self, decision: RightsDecision) -> None:
        reasons = "|".join(decision.reason_codes) or decision.disposition.value
        super().__init__(f"Rights propagation denied: {reasons}")
        self.decision = decision
        self.reason_codes = list(decision.reason_codes)
        self.disposition = decision.disposition


def _require_durable_decision_id(decision_id: str) -> str:
    """Return ``decision_id`` if it is a durable ``rdec_...`` identity, else raise.

    The fail-closed backstop for "never fabricate a decision id": an injected or
    misbehaving resolver returning ``""``, a placeholder, or a non-durable token
    cannot get that value stamped onto a governed write.
    """
    value = str(decision_id or "")
    if not value.startswith(DECISION_REF_PREFIX) or not value[len(DECISION_REF_PREFIX):].strip():
        raise ValueError(
            "rights propagation requires a durable "
            f"{DECISION_REF_PREFIX}... decision id, got {decision_id!r}"
        )
    return value


async def propagate_rights(
    *,
    tenant_id: str,
    source_id: str,
    actor: str,
    purpose: str,
    requested_use: str = USE_WRITE_TENANT_GRAPH,
    destination: str = DESTINATION_TENANT_INTERNAL,
    actor_role: Optional[str] = None,
    artifact_ref: Optional[str] = None,
    artifact_class: Optional[str] = None,
    subject_ref: Optional[str] = None,
    as_of: Optional[str] = None,
    resolver: Optional[EffectiveRightsResolver] = None,
) -> Optional[RightsPropagation]:
    """Resolve the governing rights decision for one governed write.

    Returns ``None`` when the gate is ``off`` — the caller then stamps nothing
    and the write is byte-identical to its pre-propagation behaviour. Otherwise
    the authoritative resolver is asked, its decision is recorded durably (the
    ``shadow``/``warn``/``enforce`` contract), and the result reports whether a
    ref may be stamped.

    Raises :class:`RightsPropagationDenied` when the decision is a denial AND
    the gate is in ``enforce``; in ``shadow``/``warn`` a denial is returned
    unstamped so the caller can surface it without blocking.
    """
    if not is_active():
        return None

    decision = await (resolver or effective_rights_resolver).resolve_request(
        RightsDecisionRequest(
            tenant_id=tenant_id,
            source_id=source_id,
            artifact_ref=artifact_ref,
            artifact_class=artifact_class,
            actor=actor,
            actor_role=actor_role,
            requested_use=requested_use,
            purpose=purpose,
            destination=destination,
            subject_ref=subject_ref,
            as_of=as_of,
        )
    )

    if not decision.allowed:
        if enforce_denials():
            raise RightsPropagationDenied(decision)
        return RightsPropagation(
            decision=decision, mode=current_mode(), stamped=False
        )

    _require_durable_decision_id(decision.decision_id)
    return RightsPropagation(decision=decision, mode=current_mode(), stamped=True)


def stamp_intent(
    intent: MutationIntent, propagation: Optional[RightsPropagation]
) -> MutationIntent:
    """Stamp ``propagation``'s decision ref onto a graph ``MutationIntent``.

    Returns ``intent`` unchanged when ``propagation`` is ``None`` (gate off) or
    ``stamped`` is False (a denial, or a decision with no durable identity) — a
    denied or unresolved basis never produces an allow ref. The gateway then
    copies the ref onto ``MutationRecord.rights_decision_ref``, so it reaches
    the append-only ledger and the versioned fact payload.
    """
    if propagation is None or not propagation.stamped:
        return intent
    intent.rights_decision_ref = propagation.decision_id
    return intent


def stamp_envelope(
    envelope: SpineEnvelope, propagation: Optional[RightsPropagation]
) -> SpineEnvelope:
    """Stamp ``propagation``'s decision ref onto a ``SpineEnvelope``.

    Sets ``rights_decision_ref`` via
    :func:`~services.rights_authority.envelope.apply_rights_ref` and appends the
    decision's :class:`EvidenceRef` to ``evidence_refs`` (appends only — the
    Rights Authority adds to evidence, it never replaces evidence another
    authority supplied). The append is idempotent: an already-present identical
    decision evidence ref is not duplicated, so re-stamping the same envelope
    with the same decision is a no-op.

    Same gate as :func:`stamp_intent`: ``None`` / not-stamped leaves the
    envelope untouched.
    """
    if propagation is None or not propagation.stamped:
        return envelope
    apply_rights_ref(envelope, propagation.decision_id)
    evidence = decision_evidence_ref(propagation.decision)
    if evidence not in envelope.evidence_refs:
        envelope.evidence_refs.append(evidence)
    return envelope
