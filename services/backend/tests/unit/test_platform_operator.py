"""Platform operators (Olympus staff/advisors) are not billed customers.

An operator tenant resolves to the top plan and bypasses the customer burst
limit, monthly quota/overage metering and the ML extraction budget; external
tenants keep every control. Staging sign-in is internal-only: an Auth0 login
must link to an existing user or accept an invitation, and never
self-provisions a tenant there.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

import middleware.middleware as mw
from config.settings import Environment, settings
from repositories.repos import reset_in_memory_stores
from shared.auth import platform_operator
from shared.auth.auth import PlanTier, TenantContext

OPERATOR = "tenant-olympus-ops"
CUSTOMER = "tenant-customer"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_in_memory_stores()
    platform_operator.reset_platform_operator_cache()
    monkeypatch.setattr(
        settings,
        "security_governance",
        dataclasses.replace(settings.security_governance, platform_operator_tenant_ids=[OPERATOR]),
    )
    yield
    platform_operator.reset_platform_operator_cache()
    reset_in_memory_stores()


# ── designation ──────────────────────────────────────────────────────────────


async def test_allowlisted_tenant_is_an_operator_and_others_are_not():
    assert await platform_operator.is_platform_operator(OPERATOR) is True
    assert await platform_operator.is_platform_operator(CUSTOMER) is False
    assert await platform_operator.is_platform_operator(None) is False


async def test_staging_first_admin_bootstrap_tenant_is_an_operator(monkeypatch):
    from repositories.repos import FirstAdminBootstrapRepository

    monkeypatch.setattr(settings, "env", Environment.STAGING)
    await FirstAdminBootstrapRepository().insert("staging", {"tenant_id": "tenant-bootstrap"})

    assert await platform_operator.is_platform_operator("tenant-bootstrap") is True
    assert await platform_operator.is_platform_operator(CUSTOMER) is False


async def test_bootstrap_tenant_is_not_an_operator_outside_staging():
    from repositories.repos import FirstAdminBootstrapRepository

    await FirstAdminBootstrapRepository().insert("staging", {"tenant_id": "tenant-bootstrap"})

    assert await platform_operator.is_platform_operator("tenant-bootstrap") is False


async def test_bootstrap_lookup_failure_grants_nothing(monkeypatch):
    from repositories import repos

    monkeypatch.setattr(settings, "env", Environment.STAGING)
    monkeypatch.setattr(
        repos.FirstAdminBootstrapRepository, "find_by_id",
        AsyncMock(side_effect=ConnectionError("db down")),
    )

    assert await platform_operator.is_platform_operator("tenant-bootstrap") is False


# ── middleware: customer controls ────────────────────────────────────────────


class _Limiter:
    def __init__(self) -> None:
        self.calls: list = []

    async def check(self, tenant_id, plan_tier):
        self.calls.append((tenant_id, plan_tier))
        return SimpleNamespace(allowed=False, limit=1, remaining=0, reset_at=0, retry_after=30)


class _Quota:
    def __init__(self) -> None:
        self.calls: list = []

    async def check_and_increment(self, tenant_id, plan_tier, path):
        self.calls.append((tenant_id, plan_tier, path))
        return SimpleNamespace(
            quota_limit=0, quota_used=1, remaining=0, reset="2026-10-01",
            included=False, overage_service="ingestion",
        )


def _client(monkeypatch, tenant_id: str):
    limiter, quota = _Limiter(), _Quota()
    registry = SimpleNamespace(
        jwt_handler=None, api_key_validator=None,
        rate_limiter=limiter, feature_gate=None, quota_engine=quota, quota_notifier=None,
    )
    seen: dict = {}

    async def _auth(request, jwt_handler, api_key_validator):
        return TenantContext(tenant_id=tenant_id, plan_tier=PlanTier.ALPHA)

    monkeypatch.setattr(mw, "get_registry", lambda: registry)
    monkeypatch.setattr(mw, "_authenticate_async", _auth)
    monkeypatch.setattr(mw, "_evaluate_route_policy", lambda *a, **k: None)

    app = FastAPI()

    @app.get("/v1/probe")
    async def probe(request: Request):
        seen["plan"] = request.state.plan_tier
        seen["operator"] = request.state.platform_operator
        return {"ok": True}

    mw.register_middleware(app)
    return TestClient(app), limiter, quota, seen


def test_operator_skips_burst_limit_and_quota_and_gets_the_top_plan(monkeypatch):
    client, limiter, quota, seen = _client(monkeypatch, OPERATOR)
    with client:
        response = client.get("/v1/probe", headers={"X-API-Key": "k"})

    assert response.status_code == 200
    assert seen == {"plan": PlanTier.OMEGA, "operator": True}
    assert limiter.calls == []
    assert quota.calls == []
    assert "X-Quota-Overage" not in response.headers


def test_customer_keeps_the_burst_limit(monkeypatch):
    client, limiter, quota, _ = _client(monkeypatch, CUSTOMER)
    with client:
        response = client.get("/v1/probe", headers={"X-API-Key": "k"})

    assert response.status_code == 429
    assert limiter.calls == [(CUSTOMER, PlanTier.ALPHA)]


# ── staging sign-in ──────────────────────────────────────────────────────────


class _Users:
    def __init__(self, users=None) -> None:
        self.rows = {u["user_id"]: dict(u) for u in (users or [])}

    async def find_by_id(self, user_id):
        return self.rows.get(user_id)

    async def find_by_email(self, email):
        return next((u for u in self.rows.values() if u.get("email") == email), None)

    async def update(self, user_id, changes):
        self.rows[user_id].update(changes)
        return self.rows[user_id]

    async def insert(self, user_id, record):
        self.rows[user_id] = dict(record)
        return self.rows[user_id]


async def _orgs(*invitations):
    """The real organization repository (in-memory), seeded with invitations."""
    from services.account_organization.repository import OrganizationRepository

    orgs = OrganizationRepository()
    for invitation in invitations:
        await orgs.create_invitation(invitation["tenant_id"], dict(invitation))
    return orgs


async def _members(orgs, tenant_id=OPERATOR):
    return await orgs.list_members(tenant_id, limit=50, offset=0)


def _invite(email: str, *, hours: int = 24, role: str = "admin") -> dict:
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    return {
        "invitation_id": f"invite-{email}", "tenant_id": OPERATOR, "email": email,
        "role": role, "status": "pending", "expires_at": expires.isoformat(),
    }


async def test_verified_email_links_the_existing_first_admin_user():
    from services.auth.sso_membership import resolve_sso_membership

    users = _Users([{"user_id": "u-admin", "tenant_id": OPERATOR, "email": "founder@olympus.test"}])
    membership = await resolve_sso_membership(
        sub="google|1", email="Founder@Olympus.test", email_verified=True, name="F",
        user_repo=users, organization_repo=await _orgs(),
    )

    assert (membership.tenant_id, membership.user_id, membership.how) == (
        OPERATOR, "u-admin", "linked_existing_user"
    )
    assert users.rows["u-admin"]["auth0_sub"] == "google|1"


async def test_invited_teammate_joins_the_inviting_tenant():
    from services.auth.sso_membership import resolve_sso_membership

    users, orgs = _Users(), await _orgs(_invite("advisor@example.test", role="member"))
    membership = await resolve_sso_membership(
        sub="google|2", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    )

    assert membership.tenant_id == OPERATOR and membership.how == "accepted_invitation"
    user = users.rows[membership.user_id]
    assert user["auth0_sub"] == "google|2" and user["role"] == "editor"
    [member] = await _members(orgs)
    assert (member["user_id"], member["role"]) == (membership.user_id, "member")
    invitation = await orgs.get_invitation(OPERATOR, "invite-advisor@example.test")
    assert invitation["status"] == "accepted" and invitation["provisioned_at"]


async def test_unverified_or_expired_or_uninvited_sign_ins_resolve_nothing():
    from services.auth.sso_membership import resolve_sso_membership

    users = _Users([{"user_id": "u-admin", "tenant_id": OPERATOR, "email": "founder@olympus.test"}])
    orgs = await _orgs(_invite("late@example.test", hours=-1))

    for email, verified in (
        ("founder@olympus.test", False),
        ("late@example.test", True),
        ("stranger@example.test", True),
    ):
        assert await resolve_sso_membership(
            sub="google|x", email=email, email_verified=verified, name="",
            user_repo=users, organization_repo=orgs,
        ) is None
    assert "auth0_sub" not in users.rows["u-admin"]


async def test_staging_refuses_self_signup_for_an_uninvited_sign_in(monkeypatch):
    from services.auth import routes as auth_routes
    from shared.common.common import ForbiddenError

    monkeypatch.setattr(
        settings, "trust_plane",
        dataclasses.replace(settings.trust_plane, sso_self_signup_enabled=False),
    )
    monkeypatch.setattr(
        "shared.auth.auth0_validator.validate_auth0_token",
        AsyncMock(return_value={"sub": "google|9", "email": "stranger@example.test", "email_verified": True}),
    )
    monkeypatch.setattr(
        "services.auth.sso_membership.resolve_sso_membership", AsyncMock(return_value=None)
    )
    inserted = AsyncMock()
    monkeypatch.setattr(auth_routes._repo, "insert", inserted)

    with pytest.raises(ForbiddenError, match="invitation only"):
        await auth_routes.sso_callback(auth_routes.SSOCallbackRequest(token="t"))
    inserted.assert_not_called()


async def test_a_revoked_or_already_claimed_invitation_provisions_nothing():
    """The claim is atomic and comes first: an invitation that stopped being
    pending between the read and the claim grants no access."""
    from services.auth.sso_membership import resolve_sso_membership

    users = _Users()
    orgs = await _orgs(_invite("advisor@example.test"))
    stale_read = [dict(await orgs.get_invitation(OPERATOR, "invite-advisor@example.test"))]
    await orgs.update_invitation(OPERATOR, "invite-advisor@example.test", {"status": "revoked"})
    orgs.find_pending_invitations_for_email = AsyncMock(return_value=stale_read)

    assert await resolve_sso_membership(
        sub="google|3", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    ) is None
    assert users.rows == {} and await _members(orgs) == []


async def test_retried_sign_in_converges_on_one_principal():
    from services.auth.sso_membership import resolve_sso_membership

    second_invite = {**_invite("advisor@example.test"), "invitation_id": "invite-second"}
    users, orgs = _Users(), await _orgs(_invite("advisor@example.test"), second_invite)
    first = await resolve_sso_membership(
        sub="google|4", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    )
    second = await resolve_sso_membership(
        sub="google|4", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    )

    assert first.user_id == second.user_id
    assert len(users.rows) == 1
    assert len(await _members(orgs)) == 1


async def test_an_invitation_expiring_before_the_claim_provisions_nothing():
    """Expiry is part of the atomic claim, not only the earlier read."""
    from services.auth.sso_membership import resolve_sso_membership

    users = _Users()
    orgs = await _orgs(_invite("advisor@example.test"))
    stale_read = [dict(await orgs.get_invitation(OPERATOR, "invite-advisor@example.test"))]
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    await orgs.update_invitation(OPERATOR, "invite-advisor@example.test", {"expires_at": past})
    orgs.find_pending_invitations_for_email = AsyncMock(return_value=stale_read)

    assert await resolve_sso_membership(
        sub="google|7", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    ) is None
    assert users.rows == {} and await _members(orgs) == []
    invitation = await orgs.get_invitation(OPERATOR, "invite-advisor@example.test")
    assert invitation["status"] == "pending"


async def test_a_sign_in_that_failed_after_the_claim_is_resumed():
    """The claim commits first; a failed membership or user write must not
    strand an accepted invitation without access."""
    from services.auth.sso_membership import resolve_sso_membership

    for failing in ("add_member", "user_insert"):
        reset_in_memory_stores()
        users, orgs = _Users(), await _orgs(_invite("advisor@example.test", role="viewer"))
        boom = AsyncMock(side_effect=RuntimeError("database unavailable"))
        target = orgs if failing == "add_member" else users
        attribute = "add_member" if failing == "add_member" else "insert"
        real = getattr(target, attribute)
        setattr(target, attribute, boom)
        with pytest.raises(RuntimeError):
            await resolve_sso_membership(
                sub="google|8", email="advisor@example.test", email_verified=True, name="A",
                user_repo=users, organization_repo=orgs,
            )
        invitation = await orgs.get_invitation(OPERATOR, "invite-advisor@example.test")
        assert invitation["status"] == "accepted" and not invitation.get("provisioned_at")
        assert users.rows == {}

        setattr(target, attribute, real)
        membership = await resolve_sso_membership(
            sub="google|8", email="advisor@example.test", email_verified=True, name="A",
            user_repo=users, organization_repo=orgs,
        )
        assert membership.tenant_id == OPERATOR, failing
        assert users.rows[membership.user_id]["role"] == "viewer"
        assert [m["user_id"] for m in await _members(orgs)] == [membership.user_id]
        invitation = await orgs.get_invitation(OPERATOR, "invite-advisor@example.test")
        assert invitation["provisioned_at"]


async def test_a_removed_half_provisioned_member_is_not_resumed():
    from services.auth.sso_membership import resolve_sso_membership

    users, orgs = _Users(), await _orgs(_invite("advisor@example.test"))
    real_insert = users.insert
    users.insert = AsyncMock(side_effect=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError):
        await resolve_sso_membership(
            sub="google|9", email="advisor@example.test", email_verified=True, name="A",
            user_repo=users, organization_repo=orgs,
        )
    [member] = await _members(orgs)
    await orgs.remove_member(OPERATOR, member["id"])
    users.insert = real_insert

    assert await resolve_sso_membership(
        sub="google|9", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    ) is None
    assert users.rows == {} and await _members(orgs) == []


async def test_sso_callback_reads_the_verified_email_from_userinfo(monkeypatch):
    """Access tokens for the API audience carry no email claims; without
    /userinfo every staging first sign-in would be refused."""
    from services.auth import routes as auth_routes

    monkeypatch.setattr(
        settings, "trust_plane",
        dataclasses.replace(settings.trust_plane, sso_self_signup_enabled=False, human_sessions_enabled=True),
    )
    monkeypatch.setattr(
        "shared.auth.auth0_validator.validate_auth0_token",
        AsyncMock(return_value={"sub": "google|5"}),
    )
    userinfo = AsyncMock(return_value={"sub": "google|5", "email": "team@olympus.test", "email_verified": True})
    monkeypatch.setattr("shared.auth.auth0_validator.fetch_auth0_userinfo", userinfo)
    resolved = AsyncMock(return_value=None)
    monkeypatch.setattr("services.auth.sso_membership.resolve_sso_membership", resolved)

    from shared.common.common import ForbiddenError

    with pytest.raises(ForbiddenError):
        await auth_routes.sso_callback(auth_routes.SSOCallbackRequest(token="t"))
    userinfo.assert_awaited_once_with("t")
    assert resolved.await_args.kwargs["email"] == "team@olympus.test"
    assert resolved.await_args.kwargs["email_verified"] is True


async def test_userinfo_for_another_subject_is_rejected(monkeypatch):
    from services.auth import routes as auth_routes
    from shared.common.common import BadRequestError

    monkeypatch.setattr(
        "shared.auth.auth0_validator.validate_auth0_token", AsyncMock(return_value={"sub": "google|6"}),
    )
    monkeypatch.setattr(
        "shared.auth.auth0_validator.fetch_auth0_userinfo",
        AsyncMock(return_value={"sub": "google|other", "email": "x@y.test", "email_verified": True}),
    )
    with pytest.raises(BadRequestError, match="subject mismatch"):
        await auth_routes.sso_callback(auth_routes.SSOCallbackRequest(token="t"))


async def test_userinfo_is_fetched_with_the_declared_http_client(monkeypatch):
    """/userinfo uses httpx (a declared backend dependency), not requests."""
    import httpx

    from shared.auth import auth0_validator

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"sub": "google|1", "email": "a@b.test", "email_verified": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(settings, "auth0", dataclasses.replace(settings.auth0, domain="tenant.auth0.test"))

    profile = await auth0_validator.fetch_auth0_userinfo("tok")

    assert profile["email"] == "a@b.test"
    assert seen == {"url": "https://tenant.auth0.test/userinfo", "auth": "Bearer tok"}


async def test_a_removed_member_can_be_invited_back_with_the_same_principal():
    from services.account_organization.grants import sync_user_grants
    from services.auth.sso_membership import resolve_sso_membership

    users, orgs = _Users(), await _orgs(_invite("advisor@example.test", role="member"))
    first = await resolve_sso_membership(
        sub="google|10", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    )
    [member] = await _members(orgs)
    await sync_user_grants(OPERATOR, first.user_id, None, user_repo=users)
    await orgs.remove_member(OPERATOR, member["id"])
    assert users.rows[first.user_id]["membership_status"] == "removed"

    await orgs.create_invitation(OPERATOR, {**_invite("advisor@example.test", role="viewer"),
                                            "invitation_id": "invite-again"})
    again = await resolve_sso_membership(
        sub="google|10", email="advisor@example.test", email_verified=True, name="A",
        user_id=first.user_id, user_repo=users, organization_repo=orgs,
    )

    assert again.user_id == first.user_id and len(users.rows) == 1
    user = users.rows[first.user_id]
    assert (user["membership_status"], user["role"]) == ("active", "viewer")
    assert [m["role"] for m in await _members(orgs)] == ["viewer"]


async def test_an_earlier_removal_does_not_block_resuming_a_re_invitation():
    from services.auth.sso_membership import resolve_sso_membership

    users, orgs = _Users(), await _orgs(_invite("advisor@example.test"))
    old = await orgs.add_member(OPERATOR, user_id="u-back", role="member")
    await orgs.remove_member(OPERATOR, old["id"])           # removed before the claim

    real_insert = users.insert
    users.insert = AsyncMock(side_effect=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError):
        await resolve_sso_membership(
            sub="google|11", email="advisor@example.test", email_verified=True, name="A",
            user_id="u-back", user_repo=users, organization_repo=orgs,
        )
    users.insert = real_insert

    membership = await resolve_sso_membership(
        sub="google|11", email="advisor@example.test", email_verified=True, name="A",
        user_id="u-back", user_repo=users, organization_repo=orgs,
    )
    assert membership is not None and membership.user_id == "u-back"
    assert users.rows["u-back"]["membership_status"] == "active"


async def test_sso_callback_routes_a_removed_member_through_invitations(monkeypatch):
    """A removed member's Auth0 link must not bypass a fresh invitation, and
    without one must never self-provision a second user for the same sub."""
    from repositories.repos import UserRepository
    from services.auth import routes as auth_routes

    await UserRepository().insert("u-removed", {
        "user_id": "u-removed", "tenant_id": OPERATOR, "email": "gone@example.test",
        "auth0_sub": "google|12", "status": "active", "membership_status": "removed",
    })
    monkeypatch.setattr(
        settings, "trust_plane",
        dataclasses.replace(settings.trust_plane, sso_self_signup_enabled=True),
    )
    monkeypatch.setattr(
        "shared.auth.auth0_validator.validate_auth0_token",
        AsyncMock(return_value={"sub": "google|12", "email": "gone@example.test", "email_verified": True}),
    )
    resolved = AsyncMock(return_value=None)
    monkeypatch.setattr("services.auth.sso_membership.resolve_sso_membership", resolved)
    provisioned = AsyncMock()
    monkeypatch.setattr(auth_routes._repo, "insert", provisioned)

    try:
        await auth_routes.sso_callback(auth_routes.SSOCallbackRequest(token="t"))
    except Exception:  # noqa: BLE001 — only the routing decision is under test
        pass

    assert resolved.await_args.kwargs["user_id"] == "u-removed"
    provisioned.assert_not_called()
