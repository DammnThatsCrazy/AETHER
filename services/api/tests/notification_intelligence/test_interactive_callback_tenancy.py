"""Interactive callbacks and Slack OAuth act only inside the bound tenant.

* Slack interactive: the Slack team that sent the click must be an active
  Slack channel binding of the notification's tenant.
* Telegram: the tenant is the authenticated caller's, and it must own the
  notification; the route is 404 when disabled.
* Slack OAuth: the completing session must be the one that started the flow,
  and a Slack team stays bound to at most one tenant.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import time
import types
import urllib.parse

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SIGNING_SECRET = "slack-app-signing-secret"
NOTIF = "11111111-2222-3333-4444-555555555555"


class _Notifs:
    def __init__(self):
        self.rows = {NOTIF: {"notification_id": NOTIF, "tenant_id": "tenant-B", "state": "operator_review"}}

    async def find_by_id(self, notification_id):
        return self.rows.get(notification_id)


class _Channels:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def create(self, data):
        self.rows[data["id"]] = dict(data)
        return data

    async def find_many(self, filters=None, limit=50, **kw):
        rows = list(self.rows.values())
        for k, v in (filters or {}).items():
            rows = [r for r in rows if r.get(k) == v]
        return rows[:limit]

    async def list_for_tenant(self, tenant_id, user_id=None, active_only=True, limit=100):
        return [
            r for r in self.rows.values()
            if r["tenant_id"] == tenant_id and (r.get("active") or not active_only)
        ]

    def bind_slack(self, tenant_id: str, team_id: str, *, active: bool = True) -> None:
        cid = f"ch-{len(self.rows)}"
        self.rows[cid] = {
            "id": cid, "tenant_id": tenant_id, "user_id": "u", "channel_type": "slack",
            "active": active, "channel_config": {"workspace_id": team_id},
        }

    def slack_tenants_for(self, team_id: str) -> set[str]:
        return {
            r["tenant_id"] for r in self.rows.values()
            if (r.get("channel_config") or {}).get("workspace_id") == team_id
        }


class _States:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def create(self, data):
        self.rows[data["state"]] = data

    async def find_by_id(self, state):
        return self.rows.get(state)

    async def delete(self, state):
        self.rows.pop(state, None)


class _Sink:
    def __init__(self):
        self.rows: list[dict] = []

    async def create(self, data):
        self.rows.append(data)

    async def insert(self, _id, data):
        self.rows.append(data)


@pytest.fixture
def env(monkeypatch):
    import journeys.notification_intelligence.routes as routes
    from config.settings import settings
    from shared.common.common import AetherError

    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "csec")
    monkeypatch.setattr(settings, "delivery", dataclasses.replace(
        settings.delivery, inbound_telegram_callback_enabled=True,
    ))

    e = types.SimpleNamespace(
        notifs=_Notifs(), channels=_Channels(), states=_States(),
        actions=_Sink(), advanced=[], who={"t": "tenant-A", "u": "user-A"},
    )

    class _Engine:
        def __init__(self, **kw):
            pass

        async def advance(self, notification_id, state, **kw):
            e.advanced.append(notification_id)

    monkeypatch.setattr(routes, "_notif_repo", e.notifs)
    monkeypatch.setattr(routes, "_channel_repo", e.channels)
    monkeypatch.setattr(routes, "_oauth_state_repo", e.states)
    monkeypatch.setattr(routes, "_action_repo", e.actions)
    monkeypatch.setattr(routes, "_webhook_inbox_repo", _Sink())
    monkeypatch.setattr(routes, "LifecycleEngine", _Engine)

    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _errors(_request, exc):
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _session(request, call_next):
        request.state.tenant = types.SimpleNamespace(
            tenant_id=e.who["t"], user_id=e.who["u"], role="admin",
            require_permission=lambda _p: None,
        )
        return await call_next(request)

    app.include_router(routes.router)
    e.client = TestClient(app)
    return e


# ── Slack interactive ─────────────────────────────────────────────────────────


def _slack_click(env, team_id: str, action_id: str) -> int:
    payload = {"type": "block_actions", "team": {"id": team_id}, "user": {"id": "U1"},
               "actions": [{"action_id": action_id}]}
    body = "payload=" + urllib.parse.quote(json.dumps(payload))
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(SIGNING_SECRET.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return env.client.post(
        "/v1/notifications/slack/callback", content=body.encode(),
        headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig},
    ).status_code


def test_slack_click_from_unbound_team_is_ignored(env):
    env.channels.bind_slack("tenant-B", "T-B")
    assert _slack_click(env, "T-OTHER", f"suppress:{NOTIF}:tenant-B") == 200
    assert env.advanced == []
    assert env.actions.rows == []


def test_slack_click_from_inactive_binding_is_ignored(env):
    env.channels.bind_slack("tenant-B", "T-B", active=False)
    _slack_click(env, "T-B", f"suppress:{NOTIF}:tenant-B")
    assert env.advanced == []


def test_slack_click_team_bound_to_another_tenant_is_ignored(env):
    env.channels.bind_slack("tenant-A", "T-A")
    _slack_click(env, "T-A", f"suppress:{NOTIF}:tenant-B")
    assert env.advanced == []


def test_slack_click_from_bound_team_acts_in_notification_tenant(env):
    env.channels.bind_slack("tenant-B", "T-B")
    # The tenant segment of the action id is not trusted.
    _slack_click(env, "T-B", f"suppress:{NOTIF}:tenant-A")
    assert env.advanced == [NOTIF]
    assert [a["tenant_id"] for a in env.actions.rows] == ["tenant-B"]


# ── Telegram ──────────────────────────────────────────────────────────────────


def _telegram(env, data: str) -> int:
    return env.client.post(
        "/v1/notifications/telegram/callback",
        json={"callback_query": {"data": data, "from": {"id": 666}}},
    ).status_code


def test_telegram_caller_cannot_act_on_another_tenants_notification(env):
    env.who.update(t="tenant-A")
    assert _telegram(env, f"approve:{NOTIF}:tenant-B") == 200
    assert env.advanced == []


def test_telegram_acts_for_the_owning_session(env):
    env.who.update(t="tenant-B")
    _telegram(env, f"approve:{NOTIF}:tenant-A")
    assert env.advanced == [NOTIF]


def test_telegram_route_is_404_when_disabled(env, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "delivery", dataclasses.replace(
        settings.delivery, inbound_telegram_callback_enabled=False,
    ))
    env.who.update(t="tenant-B")
    assert _telegram(env, f"approve:{NOTIF}:tenant-B") == 404
    assert env.advanced == []


def test_telegram_route_is_404_by_default(env, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "delivery", type(settings.delivery)())
    env.who.update(t="tenant-B")
    assert _telegram(env, f"approve:{NOTIF}:tenant-B") == 404
    assert env.advanced == []


# ── Slack OAuth ───────────────────────────────────────────────────────────────


@pytest.fixture
def slack_oauth(env, monkeypatch):
    import httpx
    import repositories.repos as repos
    import dependencies.providers as providers

    team = {"id": "T-TEAM", "name": "Team"}

    class _Resp:
        def json(self):
            return {"ok": True, "access_token": "xoxb-1", "team": dict(team),
                    "incoming_webhook": {"channel_id": "C1", "channel": "#ops"}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *a, **k):
            return _Resp()

    class _Vault:
        async def upsert(self, *a, **k):
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(repos, "ProvidersRepository", _Vault)
    monkeypatch.setattr(providers, "get_producer", lambda: (_ for _ in ()).throw(RuntimeError("off")))
    env.team = team
    return env


def _start(env, tenant: str, user: str) -> str:
    env.who.update(t=tenant, u=user)
    url = env.client.get("/v1/notifications/channels/slack/connect").json()["data"]["redirect_url"]
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]


def _finish(env, state: str, tenant: str, user: str) -> int:
    env.who.update(t=tenant, u=user)
    return env.client.get(
        f"/v1/notifications/channels/slack/callback?code=x&state={state}", follow_redirects=False,
    ).status_code


def test_slack_oauth_completed_by_another_session_is_rejected(slack_oauth):
    env = slack_oauth
    state = _start(env, "tenant-A", "user-A")

    assert _finish(env, state, "tenant-B", "user-B") == 403
    assert _finish(env, state, "tenant-A", "user-B") == 403
    assert env.channels.rows == {}
    # The rightful session can still finish.
    assert _finish(env, state, "tenant-A", "user-A") == 302
    assert env.channels.slack_tenants_for("T-TEAM") == {"tenant-A"}


def test_slack_team_bound_to_another_tenant_is_rejected(slack_oauth):
    env = slack_oauth
    assert _finish(env, _start(env, "tenant-A", "user-A"), "tenant-A", "user-A") == 302
    assert _finish(env, _start(env, "tenant-C", "user-C"), "tenant-C", "user-C") == 403
    assert env.channels.slack_tenants_for("T-TEAM") == {"tenant-A"}
    # The owning tenant may add another channel in the same team.
    assert _finish(env, _start(env, "tenant-A", "user-A2"), "tenant-A", "user-A2") == 302
