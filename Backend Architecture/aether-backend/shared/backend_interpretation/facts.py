"""WS-D typed relationship-fact construction (item 1 wiring surface).

:class:`RelationshipFact` is the canonical typed relationship carrier
(``primitives.py``). This module bridges it from the two real relationship
write surfaces that exist on this branch:

* :func:`fact_from_assertion` — a promoted relationship-spine assertion
  (``shared/relationship_spine/promotion.RelationshipAssertion``) becomes a
  typed fact whose ``resolution_method`` is chosen honestly from the
  assertion's ``claim_ceiling`` (``derived`` -> ``inferred``, ``observed`` ->
  ``observed``) and whose ``evidence_refs`` keep every supporting observation
  id.

Subject/object entity KINDS are not carried by the graph-edge promotion path
(its vertices are bare ids), so callers that know the kinds pass them in
(``subject_kind="user"`` etc.). This is an explicit, documented boundary — WS-D
never guesses a kind. A future lane that threads EntityRefs through promotion
can drop the kind parameters entirely.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.backend_interpretation.primitives import (
    RelationshipFact,
    ValidityWindow,
    utc_now_iso,
)
from services.operational_intelligence.models import EntityRef


def fact_from_assertion(
    assertion: Any,
    *,
    tenant_id: Optional[str] = None,
    subject_kind: Optional[str] = None,
    object_kind: Optional[str] = None,
    resolution_method: Optional[str] = None,
    observed_at: Optional[str] = None,
    model_version: Optional[str] = None,
    policy_version: str = "relationship-promotion/m6-evidence-group-v1",
) -> RelationshipFact:
    """Build a typed :class:`RelationshipFact` from a promoted relationship.

    ``assertion`` may be any object exposing ``predicate``,
    ``source_entity_id``, ``target_entity_id``, ``evidence_refs``,
    ``claim_ceiling``, ``valid_from`` and (optionally) ``assertion_id`` /
    ``tenant_id`` — the exact surface of
    ``shared.relationship_spine.promotion.RelationshipAssertion``.

    ``subject_kind`` / ``object_kind`` are REQUIRED: the graph promotion path
    carries bare vertex ids, so a kind cannot be recovered from the assertion.
    WS-D never guesses a kind — if either is omitted the fact is NOT built and a
    :class:`ValueError` is raised (callers that know the kinds must pass them;
    see the module docstring). There is no ``allow_kindless`` fallback: an
    unkinded ``EntityRef`` would silently poison the relationship fact's
    canonical identity, so the seam fails closed instead.
    """
    tenant = tenant_id or getattr(assertion, "tenant_id", None)
    if not tenant:
        raise ValueError("fact_from_assertion requires a tenant_id")

    if resolution_method is None:
        ceiling = getattr(assertion, "claim_ceiling", "observed")
        resolution_method = "inferred" if ceiling == "derived" else "observed"

    subject = _entity_ref(subject_kind, assertion.source_entity_id)
    obj = _entity_ref(object_kind, assertion.target_entity_id)

    evidence_ids: list[str] = list(getattr(assertion, "evidence_refs", []) or [])

    fact_id = getattr(assertion, "assertion_id", None)
    if not fact_id:
        import hashlib

        raw = (
            f"{tenant}:{assertion.predicate}:{assertion.source_entity_id}:"
            f"{assertion.target_entity_id}"
        )
        fact_id = hashlib.sha256(raw.encode()).hexdigest()

    return RelationshipFact(
        tenant_id=tenant,
        fact_id=f"rel-{fact_id}",
        relationship_key=(
            f"{assertion.predicate}:{assertion.source_entity_id}:"
            f"{assertion.target_entity_id}"
        ),
        subject=subject,
        object=obj,
        predicate=str(assertion.predicate),
        direction="outgoing",
        resolution_method=resolution_method,  # type: ignore[arg-type]
        resolution_reason="promoted_relationship_assertion",
        validity=ValidityWindow(valid_from=getattr(assertion, "valid_from", None)),
        claim_type="derived",
        model_version=model_version,
        policy_version=policy_version,
        evidence_refs=[_evidence_by_id(i) for i in evidence_ids],
        source_event_id=evidence_ids[0] if evidence_ids else None,
        observed_at=observed_at or utc_now_iso(),
    )


def _entity_ref(kind: Optional[str], entity_id: str) -> EntityRef:
    if not kind:
        raise ValueError(
            "RelationshipFact requires a canonical EntityRef kind; the graph "
            "promotion path carries bare vertex ids, so pass subject_kind/"
            "object_kind explicitly. WS-D never guesses a kind."
        )
    return EntityRef(kind=kind, id=entity_id)


def _evidence_by_id(evidence_id: str) -> Any:
    from services.operational_intelligence.models import EvidenceRef

    return EvidenceRef(id=evidence_id, type="event", source="relationship_promotion")


__all__ = ["fact_from_assertion"]
