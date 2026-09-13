"""Envelope-edge authorization (coordinator integration, M3) — DB-free.

``services/data_exchange/authz.py`` resolves each dotted ``data_exchange.*``
grant *or* the legacy single-word permission the proxied canonical seam admits
(read / write / admin), so existing tenant JWTs/API keys keep working without
weakening canonical parity.  ``Role.ADMIN`` short-circuits as always.
"""

from __future__ import annotations

import pytest

from services.data_exchange.authz import _LEGACY_ALIAS, require_data_exchange
from services.data_exchange.policy import DATA_EXCHANGE_PERMISSIONS
from shared.auth.auth import Role, TenantContext
from shared.common.common import ForbiddenError


def _tenant(*permissions: str, role: Role = Role.VIEWER) -> TenantContext:
    return TenantContext(tenant_id="tenant-a", role=role, permissions=list(permissions))


# ── dotted grant id (the primary vocabulary) ────────────────────────────────


def test_dotted_grant_is_required_first() -> None:
    tenant = _tenant("data_exchange.import.commit")
    require_data_exchange(tenant, "data_exchange.import.commit")  # no raise


def test_legacy_alias_conferring_the_same_capability_passes() -> None:
    # canonical /v1/imports commit is a "write" tenant action
    require_data_exchange(_tenant("write"), "data_exchange.import.commit")


def test_unrelated_permissions_deny() -> None:
    tenant = _tenant("data_exchange.read", "write")
    with pytest.raises(ForbiddenError):
        require_data_exchange(tenant, "data_exchange.transfer.download")


def test_egress_is_never_weaker_than_canonical_admin_seam() -> None:
    # canonical /v1/exports gates everything on "admin"; a plain "write" tenant
    # must not be able to create an export through the envelope.
    tenant = _tenant("write")
    with pytest.raises(ForbiddenError):
        require_data_exchange(tenant, "data_exchange.export.create")
    require_data_exchange(_tenant("admin"), "data_exchange.export.create")


def test_admin_role_short_circuits() -> None:
    tenant = _tenant(role=Role.ADMIN)
    require_data_exchange(tenant, "data_exchange.report.create")  # no raise


def test_multiple_grants_any_match() -> None:
    require_data_exchange(
        _tenant("data_exchange.import.create"), "data_exchange.transfer.upload",
        "data_exchange.import.create",
    )
    require_data_exchange(
        _tenant("write"), "data_exchange.transfer.upload", "data_exchange.import.create"
    )


# ── catalog ↔ alias completeness (drift guard) ──────────────────────────────


def test_every_registered_grant_carries_a_legacy_alias() -> None:
    missing = set(DATA_EXCHANGE_PERMISSIONS) - set(_LEGACY_ALIAS)
    assert not missing, f"grants without a legacy alias: {sorted(missing)}"
    stale = set(_LEGACY_ALIAS) - set(DATA_EXCHANGE_PERMISSIONS)
    assert not stale, f"aliases without a registered grant: {sorted(stale)}"


def test_alias_values_are_the_legacy_single_word_vocabulary() -> None:
    allowed = {"read", "write", "admin"}
    assert all(set(a) <= allowed for a in _LEGACY_ALIAS.values())
