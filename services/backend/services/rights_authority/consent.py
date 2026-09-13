"""Default consent-evaluator adapter for the Effective Rights Resolver.

Bridges the resolver's consent seam (``services.rights_authority.resolver``:
``consent_evaluator(request, grant) -> ConsentPolicyDecision | None``) to the
server-authoritative consent authority (``services.consent.authority``).
``default_consent_evaluator`` is a thin adapter over
``services.consent.authority.evaluate_consent`` that returns a
``ConsentPolicyDecision`` so the resolver can record ``policy_decision_id`` refs
and honor allow vs deny instead of falling back to the self-asserted
``consent_basis:...:unverified`` evidence string.

Mapping contract (documented, fail-closed)
------------------------------------------
* NON-CONSENT grants → ``None``. A grant whose ``legal_basis`` is not
  ``consent`` is governed by its structured rights (source_use /
  generated_output_rights / learning_authority / disclosure_authority), NOT by
  this seam; returning ``None`` leaves the resolver's structured path in charge
  exactly as before.
* CONSENT grants → the server authority is consulted for the grant-scoped data
  subject:

      subject_id   = grant.subject_ref   (the canonical data-subject reference)
      anonymous_id = None

  ``subject_ref`` is deliberately NOT trusted as consent — it is only used as
  the *lookup key* into the server ConsentReceipt store, so the server record
  decides (this mirrors the ingestion ``evaluate_consent`` posture: a
  subject-less or receipt-less consent grant is DENIED
  ``consent_receipt_missing``, never silently fail-opened to allowed). When
  ``subject_ref`` is empty there is no subject at all, which the authority
  also treats as an absence-of-evidence denial.
* PURPOSE → ``request.purpose`` verbatim. ``evaluate_consent`` requires a
  registry consent purpose (``CONSENT_PURPOSES`` in the shared consent
  registry); an unknown / non-registry purpose is DENIED ``consent_unknown`` and
  an empty purpose is DENIED ``purpose_not_authorized``. Both are fail-closed
  and both are recorded honestly as the decision's ``denied_reason``. The only
  allow path is a registry purpose that has a granted, still-valid server
  receipt for the grant's subject.

Persistence
-----------
Returned decisions are persisted (best-effort) to the tenant-scoped
``consent_policy_decisions`` store so the ``consent_decision_refs`` recorded on
the durable ``RightsDecision`` resolve to real evidence rows. A persistence
failure never changes allow/deny — the decision is already computed from the
authority; it only means the evidence ref may not be cross-lookupable (logged).

Residual seams (reported honestly)
----------------------------------
* ``DataRightsGrant`` carries an optional ``subject_ref`` string, so an
  aggregate / multi-subject source grant cannot be verified against one data
  subject. A consent-based grant over an aggregate source fails closed at the
  server authority (no subject → ``consent_receipt_missing``) until grant
  records can carry per-subject consent linkage.
* Grant-level *learning / olympus* consent also needs a registry consent purpose
  (e.g. model-training) that the current shared consent registry does not yet
  define; callers naming such a purpose today get an authoritative
  ``consent_unknown`` denial, not an allow.
* The decision's ``actor_type`` is left at the ``ConsentPolicyDecision`` default
  (``"system"``): ``RightsDecisionRequest`` carries an actor id but no
  classified actor type, so classifying the requesting principal here would be a
  guess. ``actor_id`` is still recorded faithfully.

The resolver wires this adapter into its module singleton by default; bare
``EffectiveRightsResolver()`` construction remains evaluator-less (fail-closed
``consent_required``) so existing tests and consumers that construct their own
resolvers are unchanged.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from services.policy.contracts import ConsentPolicyDecision
from services.policy.repositories import ConsentPolicyDecisionRepository

if TYPE_CHECKING:  # pragma: no cover - annotations only (avoid heavy import edges)
    from services.integrations.data_rights.models import DataRightsGrant
    from services.rights_authority.contracts import RightsDecisionRequest

logger = logging.getLogger("aether.rights_irrl.consent")

_CONSENT_LEGAL_BASIS = "consent"

_consent_policy_repo = ConsentPolicyDecisionRepository()


def _is_consent_grant(grant: "DataRightsGrant") -> bool:
    legal = str(getattr(grant, "legal_basis", "") or "").strip().lower()
    return legal == _CONSENT_LEGAL_BASIS


def _subject_from_grant(
    grant: "DataRightsGrant", request: Optional["RightsDecisionRequest"] = None
) -> Optional[str]:
    """The grant-scoped data-subject identifier, if any.

    ``subject_ref`` is the canonical data-subject identifier.  ``consent_basis``
    describes purpose/legal basis and must never be treated as an identifier.
    """
    requested = str(getattr(request, "subject_ref", "") or "").strip()
    raw = requested or str(getattr(grant, "subject_ref", "") or "").strip()
    return raw or None


def _build_decision(
    request: "RightsDecisionRequest",
    grant: "DataRightsGrant",
    *,
    purpose: str,
    subject_id: Optional[str],
    allowed: bool,
    reason_code: Optional[str],
) -> ConsentPolicyDecision:
    required = [purpose] if purpose else []
    return ConsentPolicyDecision(
        tenant_id=request.tenant_id,
        actor_id=request.actor,
        subject_ref=subject_id,
        resource_type="data_rights_grant",
        resource_id=grant.data_rights_grant_id,
        action=request.requested_use or "rights_resolution",
        purpose=purpose or None,
        required_purposes=required,
        missing_purposes=[] if allowed else required,
        granted_purposes=[purpose] if (allowed and purpose) else [],
        allowed=allowed,
        denied_reason=None if allowed else reason_code,
    )


async def _persist_best_effort(decision: ConsentPolicyDecision) -> None:
    """Record the decision so its ``policy_decision_id`` resolves as evidence.

    Best-effort on purpose: allow/deny is decided by the authority above, never
    by the ability to write this evidence row.
    """
    try:
        await _consent_policy_repo.insert(
            decision.policy_decision_id, decision.model_dump(mode="json")
        )
    except Exception:  # pragma: no cover - persistence is best-effort
        logger.warning(
            "could not persist consent policy decision %s",
            decision.policy_decision_id,
            exc_info=True,
        )


async def default_consent_evaluator(
    request: "RightsDecisionRequest",
    grant: "DataRightsGrant",
) -> Optional[ConsentPolicyDecision]:
    """Evaluate consent against the server authority for a consent-based grant.

    Returns ``None`` for non-consent grants (structured rights govern) or when
    the server authority cannot be reached (the resolver then falls back to its
    own fail-closed ``consent_required`` branch). Otherwise returns a
    ``ConsentPolicyDecision`` whose ``allowed`` reflects the server
    ``evaluate_consent`` result.
    """
    if not _is_consent_grant(grant):
        return None

    purpose = str(request.purpose or "").strip()
    subject_id = _subject_from_grant(grant, request)

    try:
        # Lazy import: keeps the consent authority off the module import graph
        # until a resolution actually needs it, and lets failures below fail
        # closed (None → resolver consent_required branch) rather than raising.
        from services.consent.authority import evaluate_consent

        allowed, reason_code = await evaluate_consent(
            tenant_id=request.tenant_id,
            subject_id=subject_id,
            anonymous_id=None,
            purpose=purpose,
        )
    except Exception:  # pragma: no cover - authority unavailable
        logger.exception(
            "consent authority unavailable for grant %s; failing closed",
            getattr(grant, "data_rights_grant_id", "?"),
        )
        return None

    decision = _build_decision(
        request,
        grant,
        purpose=purpose,
        subject_id=subject_id,
        allowed=bool(allowed),
        reason_code=reason_code,
    )
    await _persist_best_effort(decision)
    return decision
