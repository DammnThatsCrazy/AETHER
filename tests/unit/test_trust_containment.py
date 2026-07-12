"""Trust-containment guarantees (PR 1).

Proves the founding-tenant P0 auth guarantees with the trust-plane flags forced
ON, and proves the legacy (flag-off) responses are preserved so existing
frontends and tests do not regress.

Robust to suite ordering: rather than re-importing modules with a mutated env
(which fails once the backend modules are already cached by earlier tests), the
tests override the LIVE ``settings.trust_plane`` singleton — the route handlers
read those flags at call time — and restore it afterwards.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# Ensure backend modules are importable when this file runs in isolation.
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _crypto_ok() -> bool:
    """Some environments ship a broken system `cryptography` whose Rust bindings
    panic on import. The backend auth routes import it transitively, so skip the
    whole module when it is unavailable (CI ships a working build)."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
        return True
    except BaseException:  # noqa: BLE001 - PanicException is not an Exception
        return False


pytestmark = pytest.mark.skipif(not _crypto_ok(), reason="cryptography unavailable")


# Other tests in the suite evict and re-import backend modules, which can leave
# several distinct generations of `config.settings` / `repositories.repos` /
# `shared.common` alive at once (each cached module binds whichever generation
# existed at its import time — a split-brain in-memory store / exception types).
# To be fully robust to ordering, force a SINGLE consistent generation at the
# start of each trust test: evict backend modules, then import them fresh so the
# routes, repos, settings, and exception types all agree.
_BACKEND_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


@contextmanager
def trust_flags(**overrides):
    """Force a fresh, consistent backend and override trust-plane flags."""
    _evict_backend()
    settings_mod = importlib.import_module("config.settings")
    repos = importlib.import_module("repositories.repos")
    repos.reset_in_memory_stores()
    settings = settings_mod.settings
    original = settings.trust_plane
    object.__setattr__(settings, "trust_plane", dataclasses.replace(original, **overrides))
    try:
        yield
    finally:
        object.__setattr__(settings, "trust_plane", original)


_ON = dict(
    trust_plane_enabled=True,
    human_sessions_enabled=True,
    service_credentials_enabled=True,
    public_ingest_identifier_enabled=True,
    legacy_tenant_registration_enabled=False,
)
_OFF = dict(
    human_sessions_enabled=False,
    legacy_tenant_registration_enabled=True,
)


def _run(coro):
    return asyncio.run(coro)


async def _seed_password_user(repos, tenant_id, email, password, status="active"):
    from shared.auth.password import hash_password
    await repos.AdminRepository().insert(tenant_id, {
        "name": "Test", "contact_email": email, "plan_tier": "P1", "status": status,
    })
    await repos.UserRepository().insert(f"user-{tenant_id}", {
        "user_id": f"user-{tenant_id}", "tenant_id": tenant_id, "email": email,
        "name": "Test", "password_hash": hash_password(password),
        "status": "active", "auth_method": "password",
    })


class FakeClient:
    host = "127.0.0.1"


class FakeRequest:
    def __init__(self):
        self.headers = {}
        self.client = FakeClient()


# ═══════════════════════════════════════════════════════════════════════════
# FLAGS ON — founding-tenant posture guarantees
# ═══════════════════════════════════════════════════════════════════════════


class TestHumanAuthIssuesSessionsNotKeys:

    def test_login_returns_session_not_api_key(self):
        with trust_flags(**_ON):
            from fastapi import Response
            auth = importlib.import_module("services.auth.routes")
            repos = importlib.import_module("repositories.repos")
            _run(_seed_password_user(repos, "t-login", "l@x.io", "pw12345678"))

            resp = _run(auth.login(auth.LoginRequest(email="l@x.io", password="pw12345678"), Response()))
            data = resp["data"]
            assert "api_key" not in data
            assert data["session"]["token"].startswith("sess_")
            assert not data["session"]["token"].startswith("ak_")

    def test_verify_email_returns_session_not_api_key(self, monkeypatch):
        with trust_flags(**_ON):
            from fastapi import Response
            ver = importlib.import_module("shared.auth.verification")

            async def _ok(*a, **k):
                return True
            monkeypatch.setattr(ver, "verify_otp", _ok)

            auth = importlib.import_module("services.auth.routes")
            resp = _run(auth.verify_email(auth.VerifyEmailRequest(email="v@x.io", code="123456"), Response()))
            data = resp["data"]
            assert "api_key" not in data
            assert data["session"]["token"].startswith("sess_")

    def test_sso_callback_returns_session_and_active_limited_tenant(self, monkeypatch):
        with trust_flags(**_ON):
            from fastapi import Response
            a0 = importlib.import_module("shared.auth.auth0_validator")

            async def _claims(token):
                return {"sub": "sub-1", "email": "s@x.io", "name": "S", "email_verified": True}
            monkeypatch.setattr(a0, "validate_auth0_token", _claims)

            auth = importlib.import_module("services.auth.routes")
            repos = importlib.import_module("repositories.repos")
            resp = _run(auth.sso_callback(auth.SSOCallbackRequest(token="tok"), Response()))
            data = resp["data"]
            assert "api_key" not in data
            assert data["session"]["token"].startswith("sess_")

            # First SSO login must NOT auto-activate a claimed domain.
            tenant = _run(repos.AdminRepository().find_by_id(data["tenant_id"]))
            assert tenant["status"] == "active_limited"


class TestLegacyContainment:

    def test_legacy_registration_contained_no_key(self):
        with trust_flags(**_ON):
            reg = importlib.import_module("services.registration.routes")
            resp = _run(reg.register_tenant(
                reg.TenantRegistration(name="Acme", contact_email="a@x.io", plan_tier="P1"),
                FakeRequest(),
            ))
            data = resp["data"]
            assert "api_key" not in data
            assert data["status"] == "pending"
            assert data["public_ingest_identifier"].startswith("pik_")

    def test_recovery_creates_no_key(self):
        with trust_flags(**_ON):
            reg = importlib.import_module("services.registration.routes")
            repos = importlib.import_module("repositories.repos")
            _run(repos.AdminRepository().insert("t-rec", {
                "name": "Rec", "contact_email": "r@x.io", "plan_tier": "P1", "status": "active",
            }))
            resp = _run(reg.recover_api_key(reg.RecoverRequest(contact_email="r@x.io"), FakeRequest()))
            assert "api_key" not in resp["data"]
            keys = _run(repos.APIKeyRepository().find_many(filters={"tenant_id": "t-rec"}, limit=10))
            assert keys == []


class TestSessionAndCredentialSemantics:

    def test_revoked_session_fails_validation(self):
        with trust_flags(**_ON):
            sessions = importlib.import_module("services.auth.sessions")
            svc = sessions.SessionService()
            issue = _run(svc.create_session("t-1", "p-1"))
            assert _run(svc.validate_session(issue.token))["tenant_id"] == "t-1"
            _run(svc.revoke_session(issue.session_id))
            with pytest.raises(sessions.SessionValidationError):
                _run(svc.validate_session(issue.token))

    def test_expired_session_fails_validation(self):
        with trust_flags(**_ON):
            sessions = importlib.import_module("services.auth.sessions")
            svc = sessions.SessionService()
            issue = _run(svc.create_session("t-2", "p-2", absolute_minutes=-1))
            with pytest.raises(sessions.SessionValidationError):
                _run(svc.validate_session(issue.token))

    def test_public_ingest_identifier_is_ingest_only(self):
        with trust_flags(**_ON):
            sessions = importlib.import_module("services.auth.sessions")
            mw = importlib.import_module("middleware.middleware")
            auth_mod = importlib.import_module("shared.auth.auth")

            pik = _run(sessions.PublicIngestService().issue_identifier("t-ing"))
            assert pik["permissions"] == ["ingest"]

            class H(dict):
                def get(self, k, d=None):
                    return super().get(k, d)

            class Req:
                headers = H({"X-Ingest-Key": pik["identifier"]})
                cookies: dict = {}

            ctx = _run(mw._authenticate_async(
                Req(), auth_mod.JWTHandler(secret="x"), auth_mod.APIKeyValidator()
            ))
            assert ctx.has_permission("ingest") is True
            assert ctx.has_permission("analytics") is False
            assert ctx.has_permission("admin") is False

    def test_service_credential_is_scoped(self):
        with trust_flags(**_ON):
            sessions = importlib.import_module("services.auth.sessions")
            svc = sessions.ServiceCredentialService()
            acct = _run(svc.create_service_account("t-1", "ci"))
            raw, cred = _run(svc.issue_credential(
                "t-1", acct["id"], purpose="ci", permissions=["ingest", "read"]
            ))
            assert raw.startswith("svc_")
            assert _run(svc.validate_credential(raw))["permissions"] == ["ingest", "read"]
            assert _run(svc.revoke_credential(cred["id"])) is True
            with pytest.raises(sessions.SessionValidationError):
                _run(svc.validate_credential(raw))


class TestStatusEnforcement:

    def test_inactive_tenant_blocks_login(self):
        with trust_flags(**_ON):
            from fastapi import Response
            auth = importlib.import_module("services.auth.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")
            _run(_seed_password_user(repos, "t-inactive", "i@x.io", "pw12345678", status="inactive"))
            with pytest.raises(common.BadRequestError):
                _run(auth.login(auth.LoginRequest(email="i@x.io", password="pw12345678"), Response()))


# ═══════════════════════════════════════════════════════════════════════════
# FLAGS OFF — legacy behavior preserved (no regression)
# ═══════════════════════════════════════════════════════════════════════════


class TestLegacyPreserved:

    def test_login_returns_api_key_when_flag_off(self):
        with trust_flags(**_OFF):
            from fastapi import Response
            auth = importlib.import_module("services.auth.routes")
            repos = importlib.import_module("repositories.repos")
            _run(_seed_password_user(repos, "t-legacy", "lg@x.io", "pw12345678"))
            resp = _run(auth.login(auth.LoginRequest(email="lg@x.io", password="pw12345678"), Response()))
            assert "api_key" in resp["data"]
            assert resp["data"]["api_key"].startswith("ak_")

    def test_legacy_registration_returns_api_key_when_flag_on(self):
        with trust_flags(**_OFF):
            reg = importlib.import_module("services.registration.routes")
            resp = _run(reg.register_tenant(
                reg.TenantRegistration(name="Acme", contact_email="lg2@x.io", plan_tier="P1"),
                FakeRequest(),
            ))
            assert "api_key" in resp["data"]
