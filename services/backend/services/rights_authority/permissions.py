"""Rights Authority — granular grant catalog and legacy-alias admission.

The ``/v1/rights`` surface used to gate every handler on the bare single-word
tenant scope ``read`` / ``write``. Those words are the *legacy* tenant
vocabulary: they say nothing about which rights operation a principal may
perform, so a principal admitted to any tenant read surface was also admitted
to the Rights Authority's resolution and revocation surfaces.

The dotted grant ids below are the primary vocabulary for this surface. The
``rights`` RBAC domain is registered in ``services/security/contracts.py``
``GovernanceDomain`` + ``ROLE_SPECS`` in ``services/security/access_control.py``
+ ``packages/shared/security-governance.ts`` — the same registration the
``data_exchange`` domain uses, so the dotted ids resolve against real role
authority rather than being edge cosmetics.

Real tenant JWTs / API keys today carry the legacy single-word permission
vocabulary and never a dotted grant id. ``require_rights`` therefore accepts,
for each dotted grant, the legacy single-word permission the route required
*before* this catalog existed — so an already-granted caller keeps working and
nothing that was previously reachable becomes unreachable. The aliases are
parity mappings measured from the pre-catalog routes:

- ``read``  — effective-rights resolution and the tenant-scoped decision read
              (both previously gated on ``read``).
- ``write`` — the §66 revocation pipeline (previously gated on ``write``), so a
              read-only principal can never revoke rights.

``Role.ADMIN`` still short-circuits through
``TenantContext.require_any_permission`` (an admin holds every grant).
"""

from __future__ import annotations

from typing import Final

from shared.auth.auth import TenantContext

#: Canonical granular grants of the Rights Authority tenant surface.  Every id
#: here is enforced by at least one ``/v1/rights`` handler (``routes.py``).
RIGHTS_PERMISSIONS: Final[tuple[str, ...]] = (
    "rights.decision.resolve",
    "rights.decision.read",
    "rights.revocation.run",
)

#: Legacy permission that confers each dotted grant for pre-existing tenant
#: sessions.  Key set must cover every registered grant (asserted below).
_LEGACY_ALIAS: dict[str, tuple[str, ...]] = {
    "rights.decision.resolve": ("read",),
    "rights.decision.read": ("read",),
    "rights.revocation.run": ("write",),
}

# Any grant added to RIGHTS_PERMISSIONS must carry a legacy alias, so a future
# grant never silently locks out every pre-existing tenant session.
assert set(_LEGACY_ALIAS) == set(RIGHTS_PERMISSIONS), (
    "rights grant catalog and legacy-alias table are out of sync"
)


def require_rights(tenant: TenantContext, *grants: str) -> TenantContext:
    """Require any of ``grants`` (dotted ``rights.*`` id) *or* the legacy
    alias(es) of each grant.  Returns the tenant for chaining.

    A grant id outside the catalog expands to itself alone — it carries no
    alias — so a typo in a route is denied to every caller that does not
    literally hold that string. Fail-closed: an unknown id can never be
    admitted by a broad legacy ``read`` / ``write`` scope.
    """
    expanded: list[str] = []
    for grant in grants:
        if grant not in expanded:
            expanded.append(grant)
        for alias in _LEGACY_ALIAS.get(grant, ()):
            if alias not in expanded:
                expanded.append(alias)
    tenant.require_any_permission(*expanded)
    return tenant
