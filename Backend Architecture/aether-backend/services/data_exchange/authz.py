"""Data Exchange Plane — envelope-edge authorization (coordinator integration).

Every envelope route resolves ``request.state.tenant`` and re-asserts the
caller holds the relevant ``data_exchange.*`` grant at the edge.  The dotted
grant ids are the primary vocabulary (``policy.py`` is the source of grant
names; the ``data_exchange`` RBAC domain is registered in
``services/security/contracts.py`` ``GovernanceDomain`` + ``ROLE_SPECS`` +
``packages/shared/security-governance.ts``).

Real tenant JWTs / API keys today carry the legacy single-word permission
vocabulary (``read`` / ``write`` / ``admin`` / ...) and never a dotted grant
id.  To keep the envelope reachable by *exactly* the callers the canonical
seams admit — and no more — ``require_data_exchange`` also accepts, for each
dotted grant, the legacy single-word permission the **canonical seam the
envelope proxies** requires.  The aliases below are parity mappings, measured
from the canonical routes:

- ``read``        — metadata reads / lists / previews (canonical ``/v1/imports``
                    and the tenant read surface gate on ``read``).
- ``write``       — import mutations (canonical import create/upload/map/commit
                    gate on ``write``) and ingress byte transfer (upload).
- ``admin``       — approve / rollback (canonical ``admin``) and *egress*
                    (canonical ``/v1/exports`` gates everything on ``admin``),
                    so PDF reports / export + transfer downloads are never
                    reachable by a weaker legacy role than the canonical egress
                    seam.

``Role.ADMIN`` still short-circuits through
``TenantContext.require_any_permission`` (an admin holds every grant).
"""

from __future__ import annotations

from shared.auth.auth import TenantContext

from .policy import DATA_EXCHANGE_PERMISSIONS

#: Legacy permission that confers each dotted grant for pre-existing tenant
#: sessions.  Key set must cover every registered grant (asserted below).
_LEGACY_ALIAS: dict[str, tuple[str, ...]] = {
    "data_exchange.read": ("read",),
    "data_exchange.import.create": ("write",),
    "data_exchange.import.map": ("write",),
    "data_exchange.import.approve": ("admin",),
    "data_exchange.import.commit": ("write",),
    "data_exchange.import.rollback": ("admin",),
    "data_exchange.export.create": ("admin",),
    "data_exchange.export.download": ("admin",),
    "data_exchange.report.create": ("admin",),
    "data_exchange.report.delete": ("admin",),
    "data_exchange.settings.manage": ("admin",),
    "data_exchange.transfer.upload": ("write",),
    "data_exchange.transfer.download": ("admin",),
}

# Any grant added to DATA_EXCHANGE_PERMISSIONS must carry a legacy alias, so a
# future grant never silently locks out every pre-existing tenant session.
assert set(_LEGACY_ALIAS) == set(DATA_EXCHANGE_PERMISSIONS), (
    "data_exchange grant catalog and legacy-alias table are out of sync"
)


def require_data_exchange(tenant: TenantContext, *grants: str) -> TenantContext:
    """Require any of ``grants`` (dotted ``data_exchange.*`` id) *or* the
    legacy alias(es) of each grant.  Returns the tenant for chaining."""
    expanded: list[str] = []
    for grant in grants:
        if grant not in expanded:
            expanded.append(grant)
        for alias in _LEGACY_ALIAS.get(grant, ()):
            if alias not in expanded:
                expanded.append(alias)
    tenant.require_any_permission(*expanded)
    return tenant
