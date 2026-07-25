"""Kyber operator gate → workforce identity plane migration.

``require_kyber_operator`` / ``is_kyber_operator`` are a compatibility adapter:
~158 call sites across 37 modules call them, so their names, signatures and
exception types are frozen while the identity underneath changes. These tests
pin the three resolution outcomes (workforce session → legacy tenant path →
deny), the middleware capability boundary that carries declared authority to
those call sites without editing them, and the staging/production fail-closed
settings validation.

``Settings()`` validation runs in a fresh SUBPROCESS with an explicit
environment (the pattern from tests/unit/test_runtime_roles.py) so a production
construction can never leak ``AETHER_ENV`` into the parent interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

_DEPENDENCIES_MODULE = "services.kyber.access.dependencies"


# ---------------------------------------------------------------------------
# Fakes — Workers A/B/C's packages may be incomplete while this suite runs, so
# the workforce plane is injected rather than imported.
# ---------------------------------------------------------------------------


class FakeKyberContext:
    """Stand-in for Worker C's KyberAccessContext."""

    def __init__(
        self,
        *,
        operator_id: str = "op-1",
        capabilities: set[str] | None = None,
        max_action_class: int = 0,
        tenant_scopes: set[str] | None = None,
        role_template_ids: tuple[str, ...] = (),
        authenticated: bool = True,
    ) -> None:
        self.operator_id = operator_id
        self.capabilities = frozenset(capabilities or set())
        self.max_action_class = max_action_class
        self.active_tenant_scopes = frozenset(tenant_scopes or set())
        self.role_template_ids = role_template_ids
        self.authenticated = authenticated


class FakeRequest:
    def __init__(self, tenant=None, *, method: str = "GET", path: str = "/v1/kyber/x"):
        self.state = types.SimpleNamespace(tenant=tenant, request_id="req-migration-test")
        self.method = method
        self.url = types.SimpleNamespace(path=path)
        self.headers: dict[str, str] = {}
        self.client = None


@pytest.fixture
def workforce_session(monkeypatch):
    """Install a fake ``services.kyber.access.dependencies`` for one test."""

    def install(ctx):
        module = types.ModuleType(_DEPENDENCIES_MODULE)
        module.current_kyber_context = lambda request: ctx  # noqa: ARG005
        monkeypatch.setitem(sys.modules, _DEPENDENCIES_MODULE, module)
        return ctx

    return install


@pytest.fixture
def kyber_flags(monkeypatch):
    """Override ``settings.kyber_workforce`` fields for one test."""
    from config.settings import settings

    original = settings.kyber_workforce

    def override(**kwargs):
        monkeypatch.setattr(settings, "kyber_workforce", replace(original, **kwargs))
        return settings.kyber_workforce

    yield override
    monkeypatch.setattr(settings, "kyber_workforce", original)


def _tenant(permissions: list[str], tenant_id: str = "tenant-a"):
    from shared.auth.auth import Role, TenantContext

    return TenantContext(tenant_id=tenant_id, role=Role.ADMIN, permissions=permissions)


# ---------------------------------------------------------------------------
# 1. Adapter resolution order
# ---------------------------------------------------------------------------


def test_aether_role_admin_tenant_is_still_denied(kyber_flags):
    """The core boundary: a tenant Role.ADMIN is not, and never becomes, an operator."""
    from services.security.request_context import is_kyber_operator, require_kyber_operator

    kyber_flags(workforce_identity_enabled=True, legacy_operator_identity_allowed=True)
    tenant = _tenant(["read", "write", "admin"])

    assert is_kyber_operator(tenant) is False
    with pytest.raises(Exception) as exc_info:
        require_kyber_operator(FakeRequest(tenant))
    assert type(exc_info.value).__name__ == "ForbiddenError"


def test_legacy_operator_permission_allowed_when_legacy_identity_is_on(kyber_flags):
    from config.settings import settings
    from services.security.request_context import is_kyber_operator, require_kyber_operator

    kyber_flags(legacy_operator_identity_allowed=True)
    operator = _tenant(
        ["read", settings.security_governance.kyber_operator_permission], "olympus-ops"
    )

    assert is_kyber_operator(operator) is True
    actor = require_kyber_operator(FakeRequest(operator))
    assert actor.actor_type == 'olympus_operator'
    assert actor.tenant_id is None


def test_legacy_operator_permission_denied_when_legacy_identity_is_off(kyber_flags):
    """Flipping one flag retires legacy operator identity across all call sites."""
    from config.settings import settings
    from services.security.request_context import is_kyber_operator, require_kyber_operator

    kyber_flags(legacy_operator_identity_allowed=False)
    operator = _tenant(
        ["read", settings.security_governance.kyber_operator_permission], "olympus-ops"
    )

    assert is_kyber_operator(operator) is False
    with pytest.raises(Exception) as exc_info:
        require_kyber_operator(FakeRequest(operator))
    assert type(exc_info.value).__name__ == "ForbiddenError"
    assert "legacy_identity_disabled" in str(exc_info.value)


def test_workforce_session_is_allowed_with_no_tenant_at_all(kyber_flags, workforce_session):
    """A workforce principal carries no Aether tenant and needs no permission."""
    from services.security.request_context import is_kyber_operator, require_kyber_operator

    kyber_flags(workforce_identity_enabled=True, legacy_operator_identity_allowed=False)
    workforce_session(FakeKyberContext(operator_id="op-founder"))
    request = FakeRequest(tenant=None)

    assert is_kyber_operator(None, request=request) is True
    actor = require_kyber_operator(request)
    assert actor.actor_id == "op-founder"
    assert actor.actor_type == 'olympus_operator'
    assert actor.tenant_id is None
    assert actor.roles


def test_workforce_session_ignored_when_the_plane_is_disabled(kyber_flags, workforce_session):
    """The master switch is a real rollback: sessions stop being consulted."""
    from services.security.request_context import kyber_access_context

    kyber_flags(workforce_identity_enabled=False)
    workforce_session(FakeKyberContext())

    assert kyber_access_context(FakeRequest(tenant=None)) is None


def test_missing_worker_package_degrades_to_deny(kyber_flags, monkeypatch):
    """An absent dependencies module must resolve to 'no session', never to access."""
    from services.security.request_context import is_kyber_operator, kyber_access_context

    kyber_flags(workforce_identity_enabled=True, legacy_operator_identity_allowed=False)
    monkeypatch.setitem(sys.modules, _DEPENDENCIES_MODULE, None)

    request = FakeRequest(tenant=None)
    assert kyber_access_context(request) is None
    assert is_kyber_operator(None, request=request) is False


# ---------------------------------------------------------------------------
# 2. Middleware capability boundary
# ---------------------------------------------------------------------------


def _declared_policy(path: str, method: str):
    from services.security.route_registry import classify

    policy = classify(path, method)
    assert policy is not None and policy.required_capability, f"{method} {path} is undeclared"
    return policy


def test_middleware_denies_when_the_declared_capability_is_missing(
    kyber_flags, workforce_session, monkeypatch
):
    from config.settings import settings
    from middleware import middleware as mw

    kyber_flags(workforce_identity_enabled=True, backend_authz_enforced=True)
    monkeypatch.setattr(
        settings, "route_registry", replace(settings.route_registry, route_registry_enforced=True)
    )
    workforce_session(FakeKyberContext(capabilities={"kyber.workforce.self.read"}))

    path = "/v1/admin/kyber/security/audit-events"
    denial = mw._evaluate_kyber_capability(
        FakeRequest(method="GET", path=path), path, _declared_policy(path, "GET")
    )

    assert denial is not None
    assert "ROUTE_POLICY_KYBER_CAPABILITY_REQUIRED" in str(denial)


def test_middleware_allows_when_the_declared_capability_is_held(
    kyber_flags, workforce_session, monkeypatch
):
    from config.settings import settings
    from middleware import middleware as mw

    kyber_flags(workforce_identity_enabled=True, backend_authz_enforced=True)
    monkeypatch.setattr(
        settings, "route_registry", replace(settings.route_registry, route_registry_enforced=True)
    )
    workforce_session(FakeKyberContext(capabilities={"kyber.audit.read"}))

    path = "/v1/admin/kyber/security/audit-events"
    assert mw._evaluate_kyber_capability(
        FakeRequest(method="GET", path=path), path, _declared_policy(path, "GET")
    ) is None


def test_middleware_denies_when_the_action_class_exceeds_the_ceiling(
    kyber_flags, workforce_session, monkeypatch
):
    from config.settings import settings
    from middleware import middleware as mw

    kyber_flags(workforce_identity_enabled=True, backend_authz_enforced=True)
    monkeypatch.setattr(
        settings, "route_registry", replace(settings.route_registry, route_registry_enforced=True)
    )
    workforce_session(FakeKyberContext(
        capabilities={"kyber.command.recompute"},
        max_action_class=1,
        tenant_scopes={"tenant-a"},
    ))

    path = "/v1/kyber/measurement/tenants/{tenant_id_param}/recompute-all"
    policy = _declared_policy(path, "POST")
    assert policy.action_class == 3

    denial = mw._evaluate_kyber_capability(
        FakeRequest(method="POST", path="/v1/kyber/measurement/tenants/tenant-a/recompute-all"),
        path,
        policy,
    )
    assert denial is not None


def test_middleware_denies_a_tenant_scoped_capability_without_a_matching_scope(
    kyber_flags, workforce_session, monkeypatch
):
    from config.settings import settings
    from middleware import middleware as mw

    kyber_flags(workforce_identity_enabled=True, backend_authz_enforced=True)
    monkeypatch.setattr(
        settings, "route_registry", replace(settings.route_registry, route_registry_enforced=True)
    )
    workforce_session(FakeKyberContext(
        capabilities={"kyber.tenant.mirror.read"}, tenant_scopes={"tenant-other"}
    ))

    path = "/v1/kyber/tenants/{tenant_id}/operational-envelope"
    request = FakeRequest(method="GET", path="/v1/kyber/tenants/tenant-a/operational-envelope")

    assert mw._evaluate_kyber_capability(request, path, _declared_policy(path, "GET")) is not None

    workforce_session(FakeKyberContext(
        capabilities={"kyber.tenant.mirror.read"}, tenant_scopes={"tenant-a"}
    ))
    assert mw._evaluate_kyber_capability(request, path, _declared_policy(path, "GET")) is None


def test_middleware_observe_mode_allows_but_increments_the_metric(
    kyber_flags, workforce_session, monkeypatch
):
    from config.settings import settings
    from middleware import middleware as mw

    kyber_flags(workforce_identity_enabled=True, backend_authz_enforced=True)
    monkeypatch.setattr(
        settings, "route_registry", replace(settings.route_registry, route_registry_enforced=False)
    )
    workforce_session(FakeKyberContext(capabilities=set()))

    seen: list[str] = []

    class _Metrics:
        def increment(self, name, labels=None):  # noqa: ANN001, ARG002
            seen.append(name)

    monkeypatch.setattr(mw, "metrics", _Metrics())

    path = "/v1/admin/kyber/security/audit-events"
    denial = mw._evaluate_kyber_capability(
        FakeRequest(method="GET", path=path), path, _declared_policy(path, "GET")
    )

    assert denial is None
    assert "route_policy_kyber_capability_observed" in seen


def test_middleware_capability_path_is_off_when_backend_authz_is_rolled_back(
    kyber_flags, workforce_session, monkeypatch
):
    """KYBER_BACKEND_AUTHZ_ENFORCED=false restores pre-migration behaviour exactly."""
    from config.settings import settings
    from middleware import middleware as mw

    kyber_flags(workforce_identity_enabled=True, backend_authz_enforced=False)
    monkeypatch.setattr(
        settings, "route_registry", replace(settings.route_registry, route_registry_enforced=True)
    )
    workforce_session(FakeKyberContext(capabilities=set()))

    path = "/v1/admin/kyber/security/audit-events"
    assert mw._evaluate_kyber_capability(
        FakeRequest(method="GET", path=path), path, _declared_policy(path, "GET")
    ) is None


def test_undeclared_kyber_route_needs_no_capability(kyber_flags, workforce_session, monkeypatch):
    from config.settings import settings
    from middleware import middleware as mw
    from services.security.route_registry import classify

    kyber_flags(workforce_identity_enabled=True, backend_authz_enforced=True)
    monkeypatch.setattr(
        settings, "route_registry", replace(settings.route_registry, route_registry_enforced=True)
    )
    workforce_session(FakeKyberContext(capabilities=set()))

    path = "/v1/kyber/some-undeclared-surface"
    policy = classify(path, "GET")
    assert policy is not None and policy.required_capability is None
    assert mw._evaluate_kyber_capability(FakeRequest(method="GET", path=path), path, policy) is None


# ---------------------------------------------------------------------------
# 3. Settings fail-closed validation (subprocess-isolated)
# ---------------------------------------------------------------------------

_SECRET_ENV = {
    "JWT_SECRET": "test-secret",
    "DATABASE_URL": "postgresql://aether:test@localhost:5432/aether",
    "BYOK_ENCRYPTION_KEY": "test-byok-key",
    "WATERMARK_SECRET_KEY": "test-watermark-secret",
    "CANARY_SECRET_SEED": "test-canary-seed",
    "EXTRACTION_CANARY_SEED": "test-extraction-canary-seed",
    "SDK_CONFIG_SECRET": "test-sdk-config-secret",
}

# A production environment that satisfies every OTHER fail-closed guard, so a
# failure below is attributable to the Kyber workforce flags under test.
_PROD_ENV = {
    "AETHER_ENV": "production",
    "AETHER_ROLE": "api",
    "CACHE_BACKEND": "redis",
    "DATABASE_BACKEND": "postgres",
    "KYBER_WORKFORCE_IDENTITY_ENABLED": "true",
    "KYBER_DEVICE_TRUST_REQUIRED": "true",
    "KYBER_BACKEND_AUTHZ_ENFORCED": "true",
    "KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED": "false",
    "KYBER_BOOTSTRAP_ENABLED": "false",
    "KYBER_GOOGLE_CLIENT_ID": "client-id",
    "KYBER_GOOGLE_REDIRECT_URI": "https://kyber.example.com/auth/callback",
    "KYBER_WEBAUTHN_RP_ID": "kyber.example.com",
    "KYBER_WEBAUTHN_ORIGIN": "https://kyber.example.com",
}


def _construct_settings(overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AETHER_", "KYBER_", "CACHE_BACKEND", "DATABASE_BACKEND"))
    }
    env.update(_SECRET_ENV)
    env.update(_PROD_ENV)
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", "import config.settings as s; s.Settings(); print('SETTINGS_OK')"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND),
    )


def test_production_accepts_a_fully_enforced_workforce_configuration():
    proc = _construct_settings({})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SETTINGS_OK" in proc.stdout


@pytest.mark.parametrize(
    "overrides",
    [
        {"KYBER_WORKFORCE_IDENTITY_ENABLED": "false"},
        {"KYBER_BACKEND_AUTHZ_ENFORCED": "false"},
        {"KYBER_DEVICE_TRUST_REQUIRED": "false"},
        {"KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED": "true"},
        {"KYBER_BOOTSTRAP_ENABLED": "true"},
        {"KYBER_GOOGLE_CLIENT_ID": ""},
        {"KYBER_GOOGLE_REDIRECT_URI": ""},
        {"KYBER_WEBAUTHN_RP_ID": ""},
        {"KYBER_WEBAUTHN_ORIGIN": ""},
    ],
    ids=[
        "identity_disabled", "authz_observe", "no_device_trust", "legacy_identity_allowed",
        "bootstrap_open", "no_google_client_id", "no_google_redirect_uri",
        "no_webauthn_rp_id", "no_webauthn_origin",
    ],
)
def test_production_rejects_unsafe_workforce_flags(overrides):
    proc = _construct_settings(overrides)
    assert proc.returncode != 0, f"{overrides} was accepted in production"
    assert "KYBER_WORKFORCE_ENFORCEMENT_REQUIRED" in (proc.stdout + proc.stderr)


def test_staging_rejects_unsafe_workforce_flags():
    proc = _construct_settings({"AETHER_ENV": "staging", "KYBER_BACKEND_AUTHZ_ENFORCED": "false"})
    assert proc.returncode != 0
    assert "KYBER_WORKFORCE_ENFORCEMENT_REQUIRED" in (proc.stdout + proc.stderr)


def test_local_defaults_keep_the_legacy_path_available():
    """Local/dev keep legacy operator identity so existing flows are untouched."""
    from config.settings import KyberWorkforceConfig

    proc = subprocess.run(
        [
            sys.executable, "-c",
            "import config.settings as s; c = s.Settings().kyber_workforce; "
            "print(c.workforce_identity_enabled, c.legacy_operator_identity_allowed, "
            "c.backend_authz_enforced)",
        ],
        capture_output=True, text=True, cwd=str(BACKEND),
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith(("AETHER_", "KYBER_"))},
            **_SECRET_ENV,
            "AETHER_ENV": "local",
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "False True False"
    assert KyberWorkforceConfig is not None
