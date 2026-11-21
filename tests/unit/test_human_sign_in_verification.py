"""First-sign-up email code and opt-in two-step verification for Aether sign-in.

* A first-time Auth0 sign-up is asked for a code emailed to its address; no
  tenant or user exists until the code (bound to the Auth0 subject) is entered.
* A user who enrols an authenticator from profile settings is stopped after
  every first factor (password or SSO) with a short-lived challenge, and a
  session is issued only for a current code or an unused recovery code.
"""

from __future__ import annotations

import importlib
import time
from types import SimpleNamespace

import pytest

from tests.unit.test_trust_containment import (  # noqa: F401 - shared harness
    FakeRequest,
    _ON,
    _crypto_ok,
    _run,
    _seed_password_user,
    trust_flags,
)

pytestmark = pytest.mark.skipif(not _crypto_ok(), reason="cryptography unavailable")


def _sso_claims(monkeypatch, sub="sub-new", email="new@x.io"):
    a0 = importlib.import_module("shared.auth.auth0_validator")

    async def _claims(token):
        return {"sub": sub, "email": email, "name": "New", "email_verified": True}

    monkeypatch.setattr(a0, "validate_auth0_token", _claims)


class _Req(FakeRequest):
    def __init__(self, tenant_id, user_id):
        super().__init__()
        self.cookies = {}
        self.state = SimpleNamespace(tenant=SimpleNamespace(tenant_id=tenant_id, user_id=user_id))


def _enrol(me, tenant_id, user_id):
    from tenancy.auth import mfa
    req = _Req(tenant_id, user_id)
    started = _run(me.start_my_mfa_enrolment(req))["data"]
    assert started["otpauth_uri"].startswith("otpauth://totp/Aether")
    code = mfa.totp(started["secret"])
    confirmed = _run(me.confirm_my_mfa_enrolment(me.MfaCodeRequest(code=code), req))["data"]
    assert confirmed["enabled"] is True and len(confirmed["recovery_codes"]) == mfa.RECOVERY_CODE_COUNT
    return started["secret"], confirmed["recovery_codes"], req


class TestFirstSignUpEmailCode:

    def test_wrong_code_creates_nothing_and_the_right_one_provisions(self, monkeypatch):
        with trust_flags(**_ON):
            from fastapi import Response
            ver = importlib.import_module("shared.auth.verification")
            monkeypatch.setattr(ver, "generate_otp", lambda: "135790")
            _sso_claims(monkeypatch)
            auth = importlib.import_module("tenancy.auth.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")

            asked = _run(auth.sso_callback(auth.SSOCallbackRequest(token="t"), Response()))["data"]
            assert asked == {**asked, "signup_verification_required": True, "email": "new@x.io"}
            with pytest.raises(common.BadRequestError):
                _run(auth.sso_callback(auth.SSOCallbackRequest(token="t", signup_code="000000"), Response()))
            assert _run(repos.UserRepository().find_by_auth0_sub("sub-new")) is None

            done = _run(auth.sso_callback(auth.SSOCallbackRequest(token="t", signup_code="135790"), Response()))["data"]
            assert done["session"]["token"].startswith("sess_")
            user = _run(repos.UserRepository().find_by_auth0_sub("sub-new"))
            assert user["email_verified"] is True

    def test_a_code_for_one_subject_cannot_finish_another_sign_up(self, monkeypatch):
        with trust_flags(**_ON):
            from fastapi import Response
            ver = importlib.import_module("shared.auth.verification")
            monkeypatch.setattr(ver, "generate_otp", lambda: "112233")
            auth = importlib.import_module("tenancy.auth.routes")
            common = importlib.import_module("shared.common.common")
            _sso_claims(monkeypatch, sub="sub-a", email="a@x.io")
            _run(auth.sso_callback(auth.SSOCallbackRequest(token="t"), Response()))
            _sso_claims(monkeypatch, sub="sub-b", email="a@x.io")
            with pytest.raises(common.BadRequestError):
                _run(auth.sso_callback(auth.SSOCallbackRequest(token="t", signup_code="112233"), Response()))

    def test_returning_users_are_never_asked(self, monkeypatch):
        with trust_flags(**_ON):
            from fastapi import Response
            ver = importlib.import_module("shared.auth.verification")
            monkeypatch.setattr(ver, "generate_otp", lambda: "424242")
            _sso_claims(monkeypatch, sub="sub-r", email="r@x.io")
            auth = importlib.import_module("tenancy.auth.routes")
            _run(auth.sso_callback(auth.SSOCallbackRequest(token="t"), Response()))
            _run(auth.sso_callback(auth.SSOCallbackRequest(token="t", signup_code="424242"), Response()))
            again = _run(auth.sso_callback(auth.SSOCallbackRequest(token="t"), Response()))["data"]
            assert "signup_verification_required" not in again
            assert again["session"]["token"].startswith("sess_")

    def test_can_be_switched_off(self, monkeypatch):
        with trust_flags(**_ON, sso_signup_email_code_required=False):
            from fastapi import Response
            _sso_claims(monkeypatch, sub="sub-off", email="off@x.io")
            auth = importlib.import_module("tenancy.auth.routes")
            data = _run(auth.sso_callback(auth.SSOCallbackRequest(token="t"), Response()))["data"]
            assert data["session"]["token"].startswith("sess_")


class TestTwoStepVerification:

    def test_password_sign_in_stops_for_the_authenticator(self):
        with trust_flags(**_ON):
            from fastapi import Response
            from tenancy.auth import mfa
            auth = importlib.import_module("tenancy.auth.routes")
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")
            _run(_seed_password_user(repos, "t-mfa", "m@x.io", "pw12345678"))
            secret, _, _ = _enrol(me, "t-mfa", "user-t-mfa")

            first = _run(auth.login(auth.LoginRequest(email="m@x.io", password="pw12345678"), Response()))["data"]
            assert first["mfa_required"] is True and "session" not in first
            with pytest.raises(common.BadRequestError):
                _run(auth.verify_mfa(auth.MfaVerifyRequest(challenge=first["mfa_challenge"], code="000000"),
                                     Response(), FakeRequest()))
            # The enrolment code's time step is spent, so use the next one.
            code = mfa.totp(secret, time.time() + mfa.PERIOD)
            done = _run(auth.verify_mfa(auth.MfaVerifyRequest(challenge=first["mfa_challenge"], code=code),
                                        Response(), FakeRequest()))["data"]
            assert done["session"]["token"].startswith("sess_")
            # The challenge is single use and the code cannot be replayed.
            with pytest.raises(common.BadRequestError):
                _run(auth.verify_mfa(auth.MfaVerifyRequest(challenge=first["mfa_challenge"], code=code),
                                     Response(), FakeRequest()))

    def test_recovery_code_works_once(self):
        with trust_flags(**_ON):
            from fastapi import Response
            auth = importlib.import_module("tenancy.auth.routes")
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")
            _run(_seed_password_user(repos, "t-rc", "rc@x.io", "pw12345678"))
            _, codes, _ = _enrol(me, "t-rc", "user-t-rc")

            def sign_in():
                return _run(auth.login(auth.LoginRequest(email="rc@x.io", password="pw12345678"), Response()))["data"]

            done = _run(auth.verify_mfa(auth.MfaVerifyRequest(challenge=sign_in()["mfa_challenge"], code=codes[0]),
                                        Response(), FakeRequest()))["data"]
            assert done["recovery_codes_remaining"] == len(codes) - 1
            with pytest.raises(common.BadRequestError):
                _run(auth.verify_mfa(auth.MfaVerifyRequest(challenge=sign_in()["mfa_challenge"], code=codes[0]),
                                     Response(), FakeRequest()))

    def test_too_many_wrong_codes_end_the_challenge(self):
        with trust_flags(**_ON):
            from fastapi import Response
            from tenancy.auth import mfa
            auth = importlib.import_module("tenancy.auth.routes")
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")
            _run(_seed_password_user(repos, "t-x", "x@x.io", "pw12345678"))
            secret, _, _ = _enrol(me, "t-x", "user-t-x")
            challenge = _run(auth.login(auth.LoginRequest(email="x@x.io", password="pw12345678"), Response()))["data"]["mfa_challenge"]
            for _ in range(mfa.CHALLENGE_MAX_ATTEMPTS):
                with pytest.raises(common.BadRequestError):
                    _run(auth.verify_mfa(auth.MfaVerifyRequest(challenge=challenge, code="000000"), Response(), FakeRequest()))
            with pytest.raises(common.BadRequestError, match="expired"):
                _run(auth.verify_mfa(auth.MfaVerifyRequest(challenge=challenge, code=mfa.totp(secret, time.time() + 30)),
                                     Response(), FakeRequest()))

    def test_sso_sign_in_is_also_stopped(self, monkeypatch):
        with trust_flags(**_ON, sso_signup_email_code_required=False):
            from fastapi import Response
            _sso_claims(monkeypatch, sub="sub-m", email="sm@x.io")
            auth = importlib.import_module("tenancy.auth.routes")
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            created = _run(auth.sso_callback(auth.SSOCallbackRequest(token="t"), Response()))["data"]
            user = _run(repos.UserRepository().find_by_auth0_sub("sub-m"))
            _enrol(me, created["tenant_id"], user["user_id"])
            again = _run(auth.sso_callback(auth.SSOCallbackRequest(token="t"), Response()))["data"]
            assert again["mfa_required"] is True and "session" not in again

    def test_secret_is_stored_sealed_and_disable_needs_a_code(self):
        with trust_flags(**_ON):
            from tenancy.auth import mfa
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")
            _run(_seed_password_user(repos, "t-d", "d@x.io", "pw12345678"))
            secret, codes, req = _enrol(me, "t-d", "user-t-d")
            stored = _run(repos.UserRepository().find_by_id("user-t-d"))
            assert stored["mfa_totp_secret"] != secret
            assert all(code not in str(stored) for code in codes)
            assert _run(me.get_my_mfa(req))["data"] == {**_run(me.get_my_mfa(req))["data"], "enabled": True}
            with pytest.raises(common.BadRequestError):
                _run(me.disable_my_mfa(me.MfaCodeRequest(code="000000"), req))
            _run(me.disable_my_mfa(me.MfaCodeRequest(code=codes[1]), req))
            assert _run(me.get_my_mfa(req))["data"]["enabled"] is False
            assert mfa.is_enabled(_run(repos.UserRepository().find_by_id("user-t-d"))) is False

    def test_api_keys_cannot_manage_two_step(self):
        with trust_flags(**_ON):
            me = importlib.import_module("tenancy.me.routes")
            common = importlib.import_module("shared.common.common")
            with pytest.raises(common.ForbiddenError):
                _run(me.start_my_mfa_enrolment(_Req("t-k", None)))


class _SharedCache:
    """Stands in for the platform CacheClient shared by every API process."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=0):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def set_nx(self, key, value, ttl=0):
        if key in self.store:
            return False
        self.store[key] = value
        return True


def _slow_user_reads(monkeypatch, repos):
    """Yield inside every user read so overlapping requests really interleave."""
    import asyncio

    original = repos.UserRepository.find_by_id

    async def slow(self, user_id):
        await asyncio.sleep(0.01)
        return await original(self, user_id)

    monkeypatch.setattr(repos.UserRepository, "find_by_id", slow)


class TestTwoStepHardening:
    """Codex findings on #899: fail closed, shared state, single-use factors."""

    def test_sign_in_refuses_when_the_user_record_cannot_be_read(self, monkeypatch):
        with trust_flags(**_ON):
            from fastapi import Response
            auth = importlib.import_module("tenancy.auth.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")

            async def broken(self, user_id):
                raise RuntimeError("database unavailable")

            monkeypatch.setattr(repos.UserRepository, "find_by_id", broken)
            with pytest.raises(common.ServiceUnavailableError):
                _run(auth._finish_sign_in(
                    Response(), tenant_id="t-f", user_id="user-t-f", plan_tier_value="alpha",
                    method="sso", message="ok", legacy_label="Login session",
                ))

    def test_challenges_live_in_the_shared_cache(self, monkeypatch):
        with trust_flags(**_ON):
            from fastapi import Response
            from tenancy.auth import mfa
            auth = importlib.import_module("tenancy.auth.routes")
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            shared = _SharedCache()
            monkeypatch.setattr(mfa, "get_cache", lambda: shared)
            _run(_seed_password_user(repos, "t-sc", "sc@x.io", "pw12345678"))
            secret, _, _ = _enrol(me, "t-sc", "user-t-sc")

            challenge = _run(auth.login(auth.LoginRequest(email="sc@x.io", password="pw12345678"), Response()))["data"]["mfa_challenge"]
            # Another process has an empty local memory; only the shared cache holds it.
            mfa._MEM.clear()
            assert any(k.startswith("auth:mfa:challenge:") for k in shared.store)
            done = _run(auth.verify_mfa(
                auth.MfaVerifyRequest(challenge=challenge, code=mfa.totp(secret, time.time() + mfa.PERIOD)),
                Response(), FakeRequest()))["data"]
            assert done["session"]["token"].startswith("sess_")
            assert not any(k.startswith("auth:mfa:lock:") for k in shared.store)

    def test_registry_cache_is_the_platform_cache_client(self):
        from shared.cache.cache import CacheClient
        from tenancy.auth import mfa
        assert isinstance(mfa.get_cache(), CacheClient)

    def test_overlapping_verifies_issue_one_session(self, monkeypatch):
        import asyncio

        with trust_flags(**_ON):
            from fastapi import Response
            from tenancy.auth import mfa
            auth = importlib.import_module("tenancy.auth.routes")
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            common = importlib.import_module("shared.common.common")
            shared = _SharedCache()
            monkeypatch.setattr(mfa, "get_cache", lambda: shared)
            _run(_seed_password_user(repos, "t-cc", "cc@x.io", "pw12345678"))
            _, codes, _ = _enrol(me, "t-cc", "user-t-cc")
            challenge = _run(auth.login(auth.LoginRequest(email="cc@x.io", password="pw12345678"), Response()))["data"]["mfa_challenge"]
            _slow_user_reads(monkeypatch, repos)

            async def race():
                attempt = lambda: auth.verify_mfa(  # noqa: E731
                    auth.MfaVerifyRequest(challenge=challenge, code=codes[0]), Response(), FakeRequest())
                return await asyncio.gather(attempt(), attempt(), return_exceptions=True)

            results = _run(race())
            sessions = [r for r in results if isinstance(r, dict)]
            assert len(sessions) == 1, results
            assert all(isinstance(r, common.BadRequestError) for r in results if not isinstance(r, dict))

    def test_overlapping_recovery_codes_are_both_spent(self, monkeypatch):
        import asyncio

        with trust_flags(**_ON):
            from fastapi import Response
            from tenancy.auth import mfa
            auth = importlib.import_module("tenancy.auth.routes")
            me = importlib.import_module("tenancy.me.routes")
            repos = importlib.import_module("repositories.repos")
            shared = _SharedCache()
            monkeypatch.setattr(mfa, "get_cache", lambda: shared)
            _run(_seed_password_user(repos, "t-rr", "rr@x.io", "pw12345678"))
            _, codes, _ = _enrol(me, "t-rr", "user-t-rr")

            def sign_in():
                return _run(auth.login(auth.LoginRequest(email="rr@x.io", password="pw12345678"), Response()))["data"]["mfa_challenge"]

            first, second = sign_in(), sign_in()
            _slow_user_reads(monkeypatch, repos)

            async def race():
                return await asyncio.gather(
                    auth.verify_mfa(auth.MfaVerifyRequest(challenge=first, code=codes[0]), Response(), FakeRequest()),
                    auth.verify_mfa(auth.MfaVerifyRequest(challenge=second, code=codes[1]), Response(), FakeRequest()),
                )

            _run(race())
            stored = _run(repos.UserRepository().find_by_id("user-t-rr"))
            assert len(stored["mfa_recovery_hashes"]) == len(codes) - 2
            assert mfa.hash_recovery_code(codes[0]) not in stored["mfa_recovery_hashes"]
            assert mfa.hash_recovery_code(codes[1]) not in stored["mfa_recovery_hashes"]
