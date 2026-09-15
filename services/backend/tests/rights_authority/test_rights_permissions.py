"""Granular ``rights.*`` grant enforcement on the /v1/rights tenant surface.

Each endpoint declares the granular grant it performs; ``require_rights``
(``services/rights_authority/permissions.py``) admits a caller holding that
dotted grant *or* the legacy single-word scope the route required before the
catalog existed (``read`` / ``write``), so pre-existing tenant sessions keep
working.  ``Role.ADMIN`` short-circuits as always.
"""
from __future__ import annotations

import asyncio
from typing import get_args

import pytest
from fastapi import HTTPException

from services.rights_authority import routes as rr
from services.rights_authority.permissions import (
    RIGHTS_PERMISSIONS,
    _LEGACY_ALIAS,
    require_rights,
)
from shared.auth.auth import Role, TenantContext
from shared.common.common import ForbiddenError


def _tenant(*permissions: str, role: Role = Role.VIEWER) -> TenantContext:
    return TenantContext(tenant_id="tenant-a", role=role, permissions=list(permissions))


#: endpoint path → (the dependency the route is wired to, grant it enforces,
#: the legacy alias that must keep working).
_ENDPOINTS = (
    (
        "/v1/rights/decisions/effective",
        rr._resolve_dependency,
        "rights.decision.resolve",
        "read",
    ),
    (
        "/v1/rights/decisions/{decision_id}",
        rr._decision_read_dependency,
        "rights.decision.read",
        "read",
    ),
    (
        "/v1/rights/revocations",
        rr._revocation_dependency,
        "rights.revocation.run",
        "write",
    ),
)

_ALL_GRANTS = tuple(grant for _, _, grant, _ in _ENDPOINTS)


def _run(dependency, tenant: TenantContext) -> TenantContext:
    """Run a route's async permission dependency to completion.

    The tenant is passed explicitly, so the ``Depends(authenticate)`` default is
    overridden and only the granular-grant decision under test executes.
    """
    return asyncio.run(dependency(tenant=tenant))


def _route_dependency_calls(path: str) -> set[object]:
    """The top-level dependency callables FastAPI will run for ``path``."""
    route = next(r for r in rr.router.routes if getattr(r, "path", None) == path)
    return {dep.call for dep in route.dependant.dependencies}


# ── wiring: each endpoint is actually gated on its granular dependency ──────


@pytest.mark.parametrize("path,dependency,grant,alias", _ENDPOINTS)
def test_endpoint_is_wired_to_its_granular_dependency(path, dependency, grant, alias):
    """The declared grant is enforced by the route, not merely documented."""
    assert grant in RIGHTS_PERMISSIONS
    assert dependency in _route_dependency_calls(path), (
        f"{path} is not wired to the dependency enforcing {grant}"
    )


# ── allowed: dotted grant ───────────────────────────────────────────────────


@pytest.mark.parametrize("path,dependency,grant,alias", _ENDPOINTS)
def test_dotted_grant_admits(path, dependency, grant, alias):
    tenant = _run(dependency, _tenant(grant))
    assert tenant.tenant_id == "tenant-a"


# ── allowed: legacy single-word alias ───────────────────────────────────────


@pytest.mark.parametrize("path,dependency,grant,alias", _ENDPOINTS)
def test_legacy_alias_still_admits(path, dependency, grant, alias):
    _run(dependency, _tenant(alias))  # no raise


def test_legacy_read_and_write_scope_survive_the_catalog() -> None:
    """Both bare scopes the surface used before the catalog existed still work
    for exactly the operations they used to reach."""
    _run(rr._resolve_dependency, _tenant("read"))
    _run(rr._decision_read_dependency, _tenant("read"))
    _run(rr._revocation_dependency, _tenant("write"))


# ── denied ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path,dependency,grant,alias", _ENDPOINTS)
def test_unrelated_grant_denies(path, dependency, grant, alias):
    with pytest.raises(HTTPException) as exc:
        _run(dependency, _tenant("rights.something_else"))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("path,dependency,grant,alias", _ENDPOINTS)
def test_no_grant_at_all_denies(path, dependency, grant, alias):
    with pytest.raises(HTTPException) as exc:
        _run(dependency, _tenant())
    assert exc.value.status_code == 403


def test_read_scope_cannot_revoke_rights() -> None:
    """The security property the granular catalog preserves: a read-only
    principal that may resolve and read decisions may NOT revoke rights."""
    _run(rr._resolve_dependency, _tenant("read"))  # admitted
    _run(rr._decision_read_dependency, _tenant("read"))  # admitted
    with pytest.raises(HTTPException) as exc:
        _run(rr._revocation_dependency, _tenant("read"))
    assert exc.value.status_code == 403


def test_sibling_dotted_grant_does_not_leak_authority() -> None:
    """Holding one granular grant must not confer a different operation."""
    with pytest.raises(HTTPException):
        _run(rr._revocation_dependency, _tenant("rights.decision.resolve"))
    with pytest.raises(HTTPException):
        _run(rr._resolve_dependency, _tenant("rights.revocation.run"))


def test_unknown_grant_id_is_denied() -> None:
    """An id outside the catalog carries no legacy alias, so a caller holding
    only the legacy vocabulary is denied rather than admitted by a broad word."""
    with pytest.raises(ForbiddenError):
        require_rights(_tenant("read", "write"), "rights.not_a_catalog_grant")
    unknown_dependency = rr._requires_rights("rights.not_a_catalog_grant")
    with pytest.raises(HTTPException) as exc:
        _run(unknown_dependency, _tenant("read", "write"))
    assert exc.value.status_code == 403


# ── Role.ADMIN short-circuit (unchanged) ────────────────────────────────────


@pytest.mark.parametrize("path,dependency,grant,alias", _ENDPOINTS)
def test_admin_role_short_circuits(path, dependency, grant, alias):
    _run(dependency, _tenant(role=Role.ADMIN))  # no raise, no permissions listed


def test_admin_short_circuit_covers_unknown_ids_too() -> None:
    require_rights(_tenant(role=Role.ADMIN), "rights.not_a_catalog_grant")


# ── catalog ↔ alias completeness (drift guard) ──────────────────────────────


def test_every_registered_grant_carries_a_legacy_alias() -> None:
    missing = set(RIGHTS_PERMISSIONS) - set(_LEGACY_ALIAS)
    assert not missing, f"grants without a legacy alias: {sorted(missing)}"
    stale = set(_LEGACY_ALIAS) - set(RIGHTS_PERMISSIONS)
    assert not stale, f"aliases without a registered grant: {sorted(stale)}"


def test_alias_values_are_the_legacy_single_word_vocabulary() -> None:
    allowed = {"read", "write"}
    assert all(set(a) <= allowed for a in _LEGACY_ALIAS.values())


def test_every_enforced_grant_is_in_the_catalog() -> None:
    assert set(_ALL_GRANTS) <= set(RIGHTS_PERMISSIONS)


# ── the registered RBAC domain makes the grants real authority ──────────────


def test_rights_domain_is_registered_for_read_and_write_authority() -> None:
    """The dotted ids resolve against a real governance domain, not cosmetics:
    the domain is in the RBAC registry and at least one role holds it."""
    from services.security.access_control import ALL_DOMAINS, ROLE_GRANTS
    from services.security.contracts import GovernanceDomain

    assert "rights" in ALL_DOMAINS
    assert "rights" in set(get_args(GovernanceDomain))

    granted = {
        (grant.action, grant.scope)
        for grants in ROLE_GRANTS.values()
        for grant in grants
        if grant.domain == "rights"
    }
    assert ("read", "own_tenant") in granted
    assert ("write", "own_tenant") in granted
