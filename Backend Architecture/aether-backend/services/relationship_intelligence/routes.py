"""Relationship Intelligence read surface — ``/v1/relationships``.

Read-only REST surface over the relationship-fidelity substrate (Wave 2d/3b):

* ``GET /v1/relationships/{source}/{target}/fidelity`` — latest persisted
  fidelity-vector surface for the pair.
* ``GET /v1/relationships/{source}/{target}/explain`` — honest explain basis
  (registered predicate semantics + latest fidelity + degraded sections).
* ``GET /v1/relationships/{source}/{target}/influence`` — the pure nine-way
  influence-propagation decomposition over the evidence-backed path supplied
  (a skeleton read: without caller-supplied path edges it honestly reports
  ``insufficient_data`` — never a synthesized influence figure).

Every route is flag-gated and consent-gated:

* While the master Social360 flag is OFF the surface reports the same
  content-free ``feature_disabled`` degraded reason the projection adapter uses
  (``services/exploration/adapters/social360.py``) — off-flag behavior is
  unchanged and the routes never fabricate data.
* When the flag is ON, the D-05 consent gate
  (:func:`~.consent.require_social_read_consent`) is enforced for the read
  subject (the source entity). A denied read raises a content-free 403
  (:class:`ForbiddenError`) — no subject/tenant detail ever leaks.

Unknown is never 0: every envelope keeps unavailable dimensions ``None`` and
reports ``available`` / ``degraded`` state rather than inventing zeros.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from services.relationship_intelligence.coordinator import relationship_ref_for
from shared.common.common import APIResponse, ForbiddenError
from shared.logger.logger import get_logger

logger = get_logger("aether.relationship_intelligence.routes")

router = APIRouter(prefix="/v1/relationships", tags=["Relationship Intelligence"])

# Content-free degraded reason for the flag-off state (mirrors the projection
# adapter's ``_REASON_FEATURE_DISABLED`` so consumers see one vocabulary).
_REASON_FEATURE_DISABLED = "feature_disabled"
_FEATURE_DISABLED_MESSAGE = (
    "Relationship Intelligence read surface is disabled (rollout gate OFF)."
)

# Static, content-free 403 reason for a consent-denied read.
_FORBIDDEN_MESSAGE = "relationship read not permitted"


def _tenant(request: Request) -> Any:
    tenant = request.state.tenant
    tenant.require_permission("read")
    return tenant


def _feature_disabled_payload() -> dict[str, Any]:
    """Honest degraded envelope for the flag-off state (content-free reason)."""
    return {
        "available": False,
        "state": "degraded",
        "reason_code": _REASON_FEATURE_DISABLED,
        "reason": _FEATURE_DISABLED_MESSAGE,
        "degraded": True,
    }


def _degraded_payload(reason_code: str, reason: str) -> dict[str, Any]:
    """Honest ``no data`` envelope (absent data is never a zero vector)."""
    return {
        "available": False,
        "state": "degraded",
        "reason_code": reason_code,
        "reason": reason,
        "degraded": True,
    }


async def _guard_social_read(tenant_id: str, subject_entity_id: str) -> None:
    """Enforce the D-05 consent gate, mapping denial to a content-free 403."""
    from services.relationship_intelligence.consent import (
        ConsentRequired,
        require_social_read_consent,
    )

    try:
        await require_social_read_consent(
            tenant_id, subject_entity_id=subject_entity_id
        )
    except ConsentRequired:
        raise ForbiddenError(_FORBIDDEN_MESSAGE) from None


@router.get("/{source_entity_id}/{target_entity_id}/fidelity")
async def get_relationship_fidelity(
    request: Request, source_entity_id: str, target_entity_id: str
) -> dict:
    """Latest persisted fidelity-vector surface for one directed pair."""
    tenant = _tenant(request)
    from services.relationship_intelligence.reads import read_latest_fidelity

    relationship_ref = relationship_ref_for(source_entity_id, target_entity_id)
    from shared.relationship_spine import flags as _spine_flags

    if not _spine_flags.social360_enabled():
        return APIResponse(
            data=_feature_disabled_payload(), meta={"relationship_ref": relationship_ref}
        ).to_dict()

    await _guard_social_read(str(tenant.tenant_id), subject_entity_id=source_entity_id)

    read = await read_latest_fidelity(str(tenant.tenant_id), relationship_ref)
    if read is None:
        payload = _degraded_payload(
            reason_code="no_persisted_fidelity_run",
            reason=(
                "No persisted fidelity run for this relationship "
                "(fidelity unknown, never 0)."
            ),
        )
    else:
        payload = read
    return APIResponse(data=payload, meta={"relationship_ref": relationship_ref}).to_dict()


@router.get("/{source_entity_id}/{target_entity_id}/explain")
async def get_relationship_explain(
    request: Request, source_entity_id: str, target_entity_id: str
) -> dict:
    """Honest explain basis for one relationship pair (predicates + fidelity)."""
    tenant = _tenant(request)
    from services.relationship_intelligence.reads import read_relationship_basis

    relationship_ref = relationship_ref_for(source_entity_id, target_entity_id)
    from shared.relationship_spine import flags as _spine_flags

    if not _spine_flags.social360_enabled():
        return APIResponse(
            data=_feature_disabled_payload(), meta={"relationship_ref": relationship_ref}
        ).to_dict()

    await _guard_social_read(str(tenant.tenant_id), subject_entity_id=source_entity_id)

    basis = await read_relationship_basis(
        str(tenant.tenant_id), source_entity_id, target_entity_id
    )
    return APIResponse(data=basis, meta={"relationship_ref": relationship_ref}).to_dict()


@router.get("/{source_entity_id}/{target_entity_id}/influence")
async def get_relationship_influence(
    request: Request,
    source_entity_id: str,
    target_entity_id: str,
    as_of: Optional[str] = Query(default=None),
) -> dict:
    """Nine-way influence-propagation decomposition for one pair.

    Skeleton read: the decomposition module's path-edge inputs are not yet
    supplied by a caller-owned path builder, so without them the route honestly
    returns an ``empty`` / ``insufficient_data`` decomposition (never a
    synthesized influence figure).
    """
    tenant = _tenant(request)
    from services.relationship_intelligence.reads import read_influence

    relationship_ref = relationship_ref_for(source_entity_id, target_entity_id)
    from shared.relationship_spine import flags as _spine_flags

    if not _spine_flags.social360_enabled():
        return APIResponse(
            data=_feature_disabled_payload(), meta={"relationship_ref": relationship_ref}
        ).to_dict()

    await _guard_social_read(str(tenant.tenant_id), subject_entity_id=source_entity_id)

    envelope = await read_influence(
        str(tenant.tenant_id),
        source_entity_id,
        target_entity_id,
        as_of=as_of,
    )
    return APIResponse(data=envelope, meta={"relationship_ref": relationship_ref}).to_dict()


__all__ = [
    "router",
    "_REASON_FEATURE_DISABLED",
    "_guard_social_read",
]
