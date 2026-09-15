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

BACKEND = Path(__file__).resolve().parents[2] / "services" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from shared.auth.auth import (  # noqa: E402
    CREDENTIAL_CLASS_PUBLISHABLE,
    PUBLISHABLE_KEY_PERMISSIONS,
    Role,
    TenantContext,
)


def _is_denial(result) -> bool:
    # Robust to split-brain module generations across the suite: a denial is a
    # returned AetherError-like object (has an HTTP-status .code and .to_dict()).
    return result is not None and hasattr(result, "code") and hasattr(result, "to_dict")


class _Req:
    class _Url:
        path = "/"

    method = "GET"
    headers = {}

    class _State:
        request_id = "corr-test"

    state = _State()


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


def test_tenant_organization_membership_and_credential_state_fail_closed():
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        hook = _hook()
        for field in (
            "tenant_status", "organization_status", "membership_status", "credential_status"
        ):
            context = dataclasses.replace(_ADMIN, **{field: "suspended"})
            denial = hook(_req(), "/v1/profile/{entity_id}", context)
            assert _is_denial(denial), field


def test_public_ingest_identifier_cannot_cross_credential_boundary():
    context = TenantContext(
        tenant_id="t", credential_class="public_ingest_identifier", permissions=["ingest"]
    )
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        ingest_request = _req()
        ingest_request.method = "POST"
        assert _hook()(ingest_request, "/v1/batch", context) is None
        assert _is_denial(_hook()(_req(), "/v1/profile/{entity_id}", context))


def test_tenant_header_must_agree_with_authenticated_context():
    request = _req()
    request.headers = {"X-Tenant-ID": "other-tenant"}
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        assert _is_denial(_hook()(request, "/v1/profile/{entity_id}", _ADMIN))


def test_service_credential_requires_explicit_scope():
    context = TenantContext(
        tenant_id="t", credential_class="service_credential", permissions=[]
    )
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        assert _is_denial(_hook()(_req(), "/v1/profile/{entity_id}", context))


# ── Publishable keys ─────────────────────────────────────────────────────────
#
# A publishable key ships inside a page's HTML via the CDN loader, so it is
# public the moment it is issued. Two things must therefore hold that do not
# hold for a secret key: it may only reach ingestion, and it may only ever
# write for the sites it was issued for.

_PUBLISHABLE = TenantContext(
    tenant_id="t",
    credential_class=CREDENTIAL_CLASS_PUBLISHABLE,
    permissions=PUBLISHABLE_KEY_PERMISSIONS,
    site_ids=["site_a"],
)


def test_publishable_key_is_confined_to_ingestion():
    ingest_request = _req()
    ingest_request.method = "POST"
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        assert _hook()(ingest_request, "/v1/batch", _PUBLISHABLE) is None
        # Same key, same permissions, but off the ingestion surface.
        assert _is_denial(_hook()(_req(), "/v1/profile/{entity_id}", _PUBLISHABLE))
        assert _is_denial(_hook()(_req(), "/v1/exports/x", _PUBLISHABLE))


def test_publishable_key_cannot_write_for_another_site():
    """The whole point of the binding: a key copied off one page is inert elsewhere."""
    request = _req()
    request.method = "POST"
    request.headers = {"X-Aether-Site": "site_b"}
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        assert _is_denial(_hook()(request, "/v1/batch", _PUBLISHABLE))


def test_publishable_key_may_write_for_its_own_site():
    request = _req()
    request.method = "POST"
    request.headers = {"X-Aether-Site": "site_a"}
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        assert _hook()(request, "/v1/batch", _PUBLISHABLE) is None


def test_publishable_key_without_a_declared_site_is_not_rejected_here():
    """An undeclared site is scoped at attribution time, not refused at the edge.

    The SDK's own batches do not carry X-Aether-Site, so rejecting an absent
    header would break the install path this key exists to serve.
    """
    request = _req()
    request.method = "POST"
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        assert _hook()(request, "/v1/batch", _PUBLISHABLE) is None


def test_site_binding_does_not_constrain_a_secret_key():
    """A secret key is not public, so the binding does not apply to it."""
    request = _req()
    request.method = "POST"
    request.headers = {"X-Aether-Site": "site_b"}
    secret = TenantContext(tenant_id="t", permissions=["read", "write", "ingest"])
    with _route_flags(policy_enforcement_enabled=True, route_registry_enforced=True):
        assert _hook()(request, "/v1/batch", secret) is None
