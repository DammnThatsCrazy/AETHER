"""Route policy middleware hook (PR 2c) — observe vs enforced.

The hook classifies each request against the route registry. Observe-mode
(default) never blocks; enforced mode denies unclassified routes and Kyber
routes reached by non-operators. The per-route canonical Kyber gate is
unconditional regardless — this hook is the belt-and-suspenders runtime layer.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from contextlib import contextmanager
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from shared.auth.auth import Role, TenantContext  # noqa: E402


def _is_denial(result) -> bool:
    # Robust to split-brain module generations across the suite: a denial is a
    # returned AetherError-like object (has an HTTP-status .code and .to_dict()).
    return result is not None and hasattr(result, "code") and hasattr(result, "to_dict")


class _Req:
    class _Url:
        path = "/"


def _req():
    return _Req()


@contextmanager
def _route_flags(**overrides):
    import config.settings as cs
    original = cs.settings.route_registry
    object.__setattr__(cs.settings, "route_registry", dataclasses.replace(original, **overrides))
    try:
        yield
    finally:
        object.__setattr__(cs.settings, "route_registry", original)


def _hook():
    import middleware.middleware as mw
    return mw._evaluate_route_policy


_ADMIN = TenantContext(tenant_id="t", role=Role.ADMIN, permissions=["admin"])
_OPERATOR = TenantContext(tenant_id="t", role=Role.EDITOR, permissions=["kyber:operator"])


def test_observe_mode_never_blocks():
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=False):
        hook = _hook()
        assert hook(_req(), "/v1/kyber/x", _ADMIN) is None        # observed, not blocked
        assert hook(_req(), "/v1/unknown-surface/y", _ADMIN) is None


def test_enforced_mode_denies_unclassified_and_kyber_mismatch():
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        hook = _hook()
        assert _is_denial(hook(_req(), "/v1/unknown-surface/y", _ADMIN))
        assert _is_denial(hook(_req(), "/v1/kyber/x", _ADMIN))                  # admin != operator
        assert hook(_req(), "/v1/kyber/x", _OPERATOR) is None                   # operator allowed
        assert hook(_req(), "/v1/profile/x", _ADMIN) is None                    # classified, non-kyber


def test_disabled_hook_is_noop():
    with _route_flags(policy_enforcement_enabled=False, route_registry_enforced=True):
        hook = _hook()
        assert hook(_req(), "/v1/unknown-surface/y", _ADMIN) is None
