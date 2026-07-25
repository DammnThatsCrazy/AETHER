"""HTTP surface for the Kyber Tenant Mirror.

Three routes, all reads, all naming exactly one tenant. The split between them
is the disclosure level, and the level is the whole product decision:

* ``/mirror/{surface}`` at **D3** is the mirror proper — exactly what the
  tenant sees, and therefore the only rendering that may be compared against
  Aether.
* ``/mirror/{surface}/parity`` is the same read reduced to evidence: a digest,
  and — when the caller supplies Aether's own payload — the located divergence.
* ``/mirror/{surface}/masked`` at **D2** is the same surface with identifiers
  redacted, for an operator who needs shape and volume without needing to know
  *who*. It is explicitly not parity-comparable, and the envelope says so.

The parity comparison payload arrives as a query parameter rather than a
request body because this route must stay a ``GET``: it derives an artifact and
changes nothing, so making it a ``POST`` would misclassify it in the route
registry and in the audit ledger. The cost is a size limit, which is stated in
the refusal rather than silently truncating a comparison.

Every route authorizes through ``require_kyber_access``. The import is lazy and
its failure mode is a dependency that **denies** — there is no deployment slice
in which a tenant's data is mirrored without an authorization decision having
been recorded. The router is not mounted here; the application assembles it.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Path, Query, Request

from shared.common.common import APIResponse, BadRequestError, ForbiddenError
from shared.logger.logger import get_logger

from ..access.capabilities import ACTION_CLASS_READ
from ..access.disclosure import DisclosureLevel
from .service import MIRROR_CAPABILITY, MIRROR_MASKED_CAPABILITY, tenant_mirror_service

logger = get_logger("aether.kyber.mirror.routes")

router = APIRouter(prefix="/v1/kyber/tenants", tags=["Kyber Tenant Mirror"])

#: Largest Aether payload accepted inline on the parity route. Comparisons
#: bigger than this belong client-side against the digest the route returns;
#: the refusal below says so rather than comparing a truncated payload.
MAX_COMPARE_BYTES = 8192


def _require(capability: str, **kwargs: Any) -> Callable[..., Any]:
    """Build the Kyber access dependency, or a dependency that denies.

    A missing authorization module must never read as "no authorization
    required", so the fallback refuses rather than passing the request through.
    """
    try:
        from services.kyber.access.dependencies import require_kyber_access
    except ImportError:  # pragma: no cover - only while the access plane is absent
        logger.error(
            f"kyber access dependency unavailable; mirror routes will deny "
            f"capability={capability}"
        )

        async def _deny() -> None:
            raise ForbiddenError("Kyber access control is unavailable")

        return _deny
    return require_kyber_access(capability, **kwargs)


def _parse_compare(raw: Optional[str]) -> Any:
    """Decode the supplied Aether payload, refusing anything ambiguous."""
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > MAX_COMPARE_BYTES:
        raise BadRequestError(
            "Comparison payload is too large to send inline",
            details={
                "limit_bytes": MAX_COMPARE_BYTES,
                "detail": (
                    "request the digest without `compare` and run the comparison "
                    "client-side against it"
                ),
            },
        )
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise BadRequestError(
            "Comparison payload is not valid JSON",
            details={"detail": str(exc)},
        ) from None


@router.get("/{tenant_id}/mirror/{surface}")
async def read_tenant_mirror(
    request: Request,
    tenant_id: str = Path(min_length=1, max_length=128),
    surface: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            MIRROR_CAPABILITY,
            disclosure=DisclosureLevel.D3_TENANT_VISIBLE,
            action_class=ACTION_CLASS_READ,
            tenant_scope="required",
        )
    ),
) -> dict[str, Any]:
    """Exactly what the tenant sees on one surface, plus operator diagnostics.

    An unknown surface 404s and a parity-exempt surface is refused with the
    manifest's own reason; neither is answered with an empty payload, because a
    blank screen reads to an operator as "this tenant has no data".
    """
    envelope = await tenant_mirror_service.render(
        request, tenant_id=tenant_id, surface=surface
    )
    return APIResponse(
        data=envelope.model_dump(),
        meta={
            "granted_disclosure": _disclosure_token(context),
            "contract_version": envelope.contract_version,
            "parity_comparable": envelope.parity_comparable,
        },
    ).to_dict()


@router.get("/{tenant_id}/mirror/{surface}/parity")
async def read_tenant_mirror_parity(
    request: Request,
    tenant_id: str = Path(min_length=1, max_length=128),
    surface: str = Path(min_length=1, max_length=128),
    compare: Optional[str] = Query(
        default=None,
        description="Aether's own tenantVisible payload, JSON-encoded, for a located comparison",
    ),
    context: Any = Depends(
        _require(
            MIRROR_CAPABILITY,
            disclosure=DisclosureLevel.D3_TENANT_VISIBLE,
            action_class=ACTION_CLASS_READ,
            tenant_scope="required",
        )
    ),
) -> dict[str, Any]:
    """The mirror's parity digest, and the divergence when a payload is supplied.

    Without ``compare`` this is evidence an operator can carry elsewhere: the
    digest binds the canonical payload to the contract version, so it cannot be
    mistaken for parity under a different contract. With ``compare`` the answer
    names the JSON path of every disagreement, because "the digests differ" is
    not something anyone can act on during an incident.
    """
    aether_payload = _parse_compare(compare)

    # Exactly one tenant read either way. Rendering once for the digest and
    # again for the comparison would read the tenant twice and could return two
    # different answers for one question.
    if aether_payload is None:
        envelope = await tenant_mirror_service.render(
            request, tenant_id=tenant_id, surface=surface
        )
        data: dict[str, Any] = {
            "surface": envelope.surface_id,
            "tenant_id": envelope.tenant_id,
            "contract_version": envelope.contract_version,
            "parity_comparable": envelope.parity_comparable,
            "mirror_digest": tenant_mirror_service.digest(envelope).model_dump(),
            "comparison": None,
        }
    else:
        comparison = await tenant_mirror_service.check_parity(
            request,
            tenant_id=tenant_id,
            surface=surface,
            aether_payload=aether_payload,
        )
        data = {
            "surface": surface,
            "tenant_id": tenant_id,
            "contract_version": comparison.contract_version,
            "parity_comparable": True,
            "mirror_digest": comparison.mirror_digest.model_dump(),
            "comparison": comparison.model_dump(),
        }
    return APIResponse(
        data=data, meta={"granted_disclosure": _disclosure_token(context)}
    ).to_dict()


@router.get("/{tenant_id}/mirror/{surface}/masked")
async def read_tenant_mirror_masked(
    request: Request,
    tenant_id: str = Path(min_length=1, max_length=128),
    surface: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            MIRROR_MASKED_CAPABILITY,
            disclosure=DisclosureLevel.D2_TENANT_MASKED,
            action_class=ACTION_CLASS_READ,
            tenant_scope="required",
        )
    ),
) -> dict[str, Any]:
    """The same surface with tenant-identifying fields redacted.

    The masking is the gateway's, not this route's — ``D2`` is the gateway's own
    floor and it redacts on the way out, so a masked mirror cannot accidentally
    render more than a masked graph read would. The envelope comes back with
    ``parity_comparable: false``: redacted identifiers are *supposed* to differ
    from what the tenant sees, and digesting them would manufacture divergence.
    """
    envelope = await tenant_mirror_service.render(
        request, tenant_id=tenant_id, surface=surface
    )
    return APIResponse(
        data=envelope.model_dump(),
        meta={
            "granted_disclosure": _disclosure_token(context),
            "contract_version": envelope.contract_version,
            "parity_comparable": envelope.parity_comparable,
        },
    ).to_dict()


def _disclosure_token(context: Any) -> Optional[str]:
    """The level this response was rendered at, for the client to display."""
    granted = getattr(context, "granted_disclosure", None)
    if granted is None:
        return None
    try:
        return DisclosureLevel(int(granted)).name_token
    except (TypeError, ValueError):  # pragma: no cover - exotic context
        return None


__all__ = [
    "MAX_COMPARE_BYTES",
    "MIRROR_CAPABILITY",
    "MIRROR_MASKED_CAPABILITY",
    "router",
]
