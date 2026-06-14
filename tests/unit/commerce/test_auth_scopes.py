"""Unit tests for commerce permission scopes and Kyber roles."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")


def test_permissions_has_all_commerce_scopes():
    from shared.auth.auth import Permissions
    required = [
        "commerce:challenge", "commerce:verify", "commerce:settle",
        "commerce:approve", "commerce:review", "commerce:policy",
        "commerce:admin", "commerce:read",
        "approvals:read", "approvals:write",
        "entitlements:read", "entitlements:write",
        "resources:admin",
    ]
    defined = {v for k, v in vars(Permissions).items() if not k.startswith("_")}
    for scope in required:
        assert scope in defined, f"Missing permission scope: {scope}"


def test_kyber_role_enum_exists():
    from shared.auth.auth import KyberRole
    assert KyberRole.VIEWER.value == "kyber:viewer"
    assert KyberRole.OPERATOR.value == "kyber:operator"
    assert KyberRole.APPROVER.value == "kyber:approver"
    assert KyberRole.ADMIN.value == "kyber:admin"


def test_kyber_role_permissions_map_exists():
    from shared.auth.auth import KYBER_ROLE_PERMISSIONS, KyberRole, Permissions
    assert KyberRole.VIEWER in KYBER_ROLE_PERMISSIONS
    assert KyberRole.OPERATOR in KYBER_ROLE_PERMISSIONS
    assert KyberRole.APPROVER in KYBER_ROLE_PERMISSIONS
    assert KyberRole.ADMIN in KYBER_ROLE_PERMISSIONS


def test_viewer_has_only_read_permissions():
    from shared.auth.auth import KYBER_ROLE_PERMISSIONS, KyberRole, Permissions
    viewer_perms = KYBER_ROLE_PERMISSIONS[KyberRole.VIEWER]
    assert Permissions.COMMERCE_READ in viewer_perms
    assert Permissions.APPROVALS_READ in viewer_perms
    assert Permissions.ENTITLEMENTS_READ in viewer_perms
    # Viewer must NOT have write/admin scopes
    assert Permissions.COMMERCE_ADMIN not in viewer_perms
    assert Permissions.APPROVALS_WRITE not in viewer_perms
    assert Permissions.COMMERCE_APPROVE not in viewer_perms


def test_operator_has_settle_and_verify():
    from shared.auth.auth import KYBER_ROLE_PERMISSIONS, KyberRole, Permissions
    op_perms = KYBER_ROLE_PERMISSIONS[KyberRole.OPERATOR]
    assert Permissions.COMMERCE_SETTLE in op_perms
    assert Permissions.COMMERCE_VERIFY in op_perms
    # Operator cannot approve
    assert Permissions.COMMERCE_APPROVE not in op_perms


def test_approver_can_approve():
    from shared.auth.auth import KYBER_ROLE_PERMISSIONS, KyberRole, Permissions
    approver_perms = KYBER_ROLE_PERMISSIONS[KyberRole.APPROVER]
    assert Permissions.COMMERCE_APPROVE in approver_perms
    assert Permissions.APPROVALS_WRITE in approver_perms
    assert Permissions.COMMERCE_REVIEW in approver_perms
    # Approver should NOT have admin
    assert Permissions.COMMERCE_ADMIN not in approver_perms


def test_admin_has_all_commerce_scopes():
    from shared.auth.auth import KYBER_ROLE_PERMISSIONS, KyberRole, Permissions
    admin_perms = KYBER_ROLE_PERMISSIONS[KyberRole.ADMIN]
    all_scopes = [
        Permissions.COMMERCE_READ, Permissions.COMMERCE_CHALLENGE,
        Permissions.COMMERCE_VERIFY, Permissions.COMMERCE_SETTLE,
        Permissions.COMMERCE_APPROVE, Permissions.COMMERCE_REVIEW,
        Permissions.COMMERCE_POLICY, Permissions.COMMERCE_ADMIN,
        Permissions.APPROVALS_READ, Permissions.APPROVALS_WRITE,
        Permissions.ENTITLEMENTS_READ, Permissions.ENTITLEMENTS_WRITE,
        Permissions.RESOURCES_ADMIN,
    ]
    for scope in all_scopes:
        assert scope in admin_perms, f"Admin missing scope: {scope}"


def test_roles_are_additive_viewer_subset_of_operator():
    from shared.auth.auth import KYBER_ROLE_PERMISSIONS, KyberRole
    viewer = set(KYBER_ROLE_PERMISSIONS[KyberRole.VIEWER])
    operator = set(KYBER_ROLE_PERMISSIONS[KyberRole.OPERATOR])
    # All viewer permissions should be present in operator
    assert viewer.issubset(operator)


def test_tenant_context_has_permission_check():
    from shared.auth.auth import TenantContext, Role
    ctx = TenantContext(
        tenant_id="t1",
        permissions=["commerce:read", "approvals:read"],
    )
    assert ctx.has_permission("commerce:read")
    assert ctx.has_permission("approvals:read")
    assert not ctx.has_permission("commerce:admin")


def test_admin_role_bypasses_permission_check():
    from shared.auth.auth import TenantContext, Role
    ctx = TenantContext(tenant_id="t1", role=Role.ADMIN, permissions=[])
    assert ctx.has_permission("commerce:admin")
    assert ctx.has_permission("resources:admin")
