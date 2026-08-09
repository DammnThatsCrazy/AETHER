"""Entitlement enforcement seam for capability-execution paths (§7).

The canonical read paths already *consult* ``EntitlementService.evaluate``
advisably. This seam turns that advisory decision into enforcement: it calls
the deterministic, dimension-level :meth:`EntitlementService.enforce_dimension`
and, by default, raises :class:`EntitlementDeniedError` (HTTP 403) when the
tenant is not entitled — fail-closed, never a silent pass.

Execution paths wrap their dimension of work with :func:`enforce_entitlement`
(either directly, or via ``services/metering_evidence.hooks``
``meter_capability_usage`` which performs enforcement + metering together).
``fail_closed=False`` is for advisory callers that want the decision without
raising.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from services.billing.revops import (
    ENTITLEMENT_STATE_DENIED,
    EntitlementDeniedError,
    EntitlementService,
)


@dataclass
class EnforcementResult:
    """Outcome of an entitlement enforcement call.

    ``allowed`` is False only when ``state == "denied"``. ``reason`` is the
    machine-readable denial reason (``not_entitled`` | ``disabled`` |
    ``overage_not_allowed``) or the allowed state.
    """

    allowed: bool
    state: str
    reason: str
    dimension: str
    quantity: float
    included_quantity: float
    overage_quantity: float
    entitlement: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def enforce_entitlement(
    tenant_id: str,
    dimension: str,
    quantity: float,
    *,
    entitlements: EntitlementService | None = None,
    package_id: str | None = None,
    fail_closed: bool = True,
) -> EnforcementResult:
    """Enforce dimension-level entitlement for a capability execution.

    Fail-closed by default: raises :class:`EntitlementDeniedError` when the
    tenant is not entitled. With ``fail_closed=False`` returns the decision
    (``allowed=False`` + ``reason``) without raising, for advisory callers.
    """
    svc = entitlements or EntitlementService()
    decision = await svc.enforce_dimension(tenant_id, dimension, quantity, package_id)
    denied = decision['state'] == ENTITLEMENT_STATE_DENIED
    result = EnforcementResult(
        allowed=not denied,
        state=decision['state'],
        reason=decision['reason'],
        dimension=dimension,
        quantity=float(quantity or 0),
        included_quantity=decision['included_quantity'],
        overage_quantity=decision['overage_quantity'],
        entitlement=decision['entitlement'],
    )
    if denied and fail_closed:
        raise EntitlementDeniedError(dimension, decision['reason'])
    return result


__all__ = [
    "EnforcementResult",
    "enforce_entitlement",
]
