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

    async def find_by_email(self, email):
        return next((u for u in self.rows.values() if u.get("email") == email), None)

    async def update(self, user_id, changes):
        self.rows[user_id].update(changes)
        return self.rows[user_id]

    async def insert(self, user_id, record):
        self.rows[user_id] = dict(record)
        return self.rows[user_id]


class _Orgs:
    def __init__(self, invitations=None) -> None:
        self.invitations = list(invitations or [])
        self.members: list = []

    async def find_pending_invitations_for_email(self, email):
        return [i for i in self.invitations if i["email"] == email and i["status"] == "pending"]

    async def add_member(self, tenant_id, **kwargs):
        self.members.append({"tenant_id": tenant_id, **kwargs})

    async def update_invitation(self, tenant_id, invitation_id, changes):
        for invitation in self.invitations:
            if invitation["invitation_id"] == invitation_id:
                invitation.update(changes)


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
        user_repo=users, organization_repo=_Orgs(),
    )

    assert (membership.tenant_id, membership.user_id, membership.how) == (
        OPERATOR, "u-admin", "linked_existing_user"
    )
    assert users.rows["u-admin"]["auth0_sub"] == "google|1"


async def test_invited_teammate_joins_the_inviting_tenant():
    from services.auth.sso_membership import resolve_sso_membership

    users, orgs = _Users(), _Orgs([_invite("advisor@example.test", role="member")])
    membership = await resolve_sso_membership(
        sub="google|2", email="advisor@example.test", email_verified=True, name="A",
        user_repo=users, organization_repo=orgs,
    )

    assert membership.tenant_id == OPERATOR and membership.how == "accepted_invitation"
    user = users.rows[membership.user_id]
    assert user["auth0_sub"] == "google|2" and user["role"] == "editor"
    assert orgs.members[0]["tenant_id"] == OPERATOR
    assert orgs.invitations[0]["status"] == "accepted"


async def test_unverified_or_expired_or_uninvited_sign_ins_resolve_nothing():
    from services.auth.sso_membership import resolve_sso_membership

    users = _Users([{"user_id": "u-admin", "tenant_id": OPERATOR, "email": "founder@olympus.test"}])
    orgs = _Orgs([_invite("late@example.test", hours=-1)])

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
