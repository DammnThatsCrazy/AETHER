"""Kyber operator gate consolidation (PR 2a) — semantic coverage.

`test_kyber_boundary.py` proves every mounted ``/kyber`` route *names* the guard.
This test proves the consolidated guards are actually the canonical fail-closed
gate: a regular Aether tenant — even one holding the ``admin`` permission or
``Role.ADMIN`` — is REJECTED, and only a ``kyber:operator`` (or allowlisted
tenant id) is accepted. It closes the audit gap where several operator routes
gated on ``require_permission("admin")`` (privilege escalation) or on the
never-set ``is_platform_admin`` flag (locked out real operators).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from shared.auth.auth import Role, TenantContext  # noqa: E402

# Assert denial by exception TYPE NAME rather than class identity: other tests in
# the suite evict/re-import backend modules, so ``shared.common.common`` may have
# several live generations and isinstance against one of them is unreliable.
_DENIAL_NAMES = {"ForbiddenError", "UnauthorizedError"}


def _assert_denied(fn, arg):
    try:
        fn(arg)
    except Exception as exc:  # noqa: BLE001
        assert type(exc).__name__ in _DENIAL_NAMES, f"unexpected exception {type(exc).__name__}: {exc}"
        return
    raise AssertionError("expected a denial, but the gate allowed the request")


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def _req(tenant):
    class _State:
        pass

    class _Req:
        pass

    r = _Req()
    r.state = _State()
    r.state.tenant = tenant
    r.client = None                # _client_meta: request.client.host if request.client
    r.headers = _Headers()         # _client_meta: request.headers.get("user-agent")
    return r


def _tenant(perms, role=Role.EDITOR, tenant_id="tenant-x"):
    return TenantContext(tenant_id=tenant_id, role=role, permissions=list(perms))


_ADMIN = _tenant(["admin", "read", "write"])
_ROLE_ADMIN = _tenant([], role=Role.ADMIN)          # has_permission() → True for everything
_OPERATOR = _tenant(["kyber:operator"])


def test_canonical_is_kyber_operator_logic():
    from services.security.request_context import is_kyber_operator
    assert is_kyber_operator(_ADMIN) is False
    assert is_kyber_operator(_ROLE_ADMIN) is False   # Role.ADMIN is NOT an operator
    assert is_kyber_operator(_OPERATOR) is True
    assert is_kyber_operator(None) is False


# Each former-pattern gate must now reject tenant admins and accept operators.
# (Gates without a feature-flag guard — directly callable.)
_GATES = [
    ("services.reliability.routes", "_require_kyber_operator"),        # was Pattern C (leak)
    ("services.ml_serving.kyber_ml_admin", "_require_kyber_operator"), # was Pattern C (leak)
    ("services.admin.routes", "_require_kyber_operator"),              # was Pattern C (rebound)
    ("services.kyber_operator.routes", "_require_kyber_operator"),     # was Pattern B (dead flag)
]


@pytest.mark.parametrize("module_name,gate_name", _GATES)
def test_gate_rejects_tenant_admin(module_name, gate_name):
    import importlib
    gate = getattr(importlib.import_module(module_name), gate_name)
    _assert_denied(gate, _req(_ADMIN))
    _assert_denied(gate, _req(_ROLE_ADMIN))


@pytest.mark.parametrize("module_name,gate_name", _GATES)
def test_gate_accepts_operator(module_name, gate_name):
    import importlib
    gate = getattr(importlib.import_module(module_name), gate_name)
    # Must not raise for a genuine operator.
    gate(_req(_OPERATOR))


def test_gate_requires_authentication():
    import importlib
    gate = importlib.import_module("services.reliability.routes")._require_kyber_operator
    _assert_denied(gate, _req(None))
