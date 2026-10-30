"""POST /v1/experience360/frames is a read: read permission, read attribution, MCP read allowlist."""
from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

import middleware.middleware as mw
from config.settings import settings


def _request(method="POST", path="/v1/experience360/frames"):
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": [], "server": ("api.example.test", 443),
        "client": ("192.0.2.10", 1234),
    }
    return Request(scope)


class _Ctx:
    tenant_id = "tenant-a"
    user_id = "user-a"
    credential_class = "legacy"
    permissions = ["read"]

    def __init__(self, perms):
        self.permissions = perms

    def has_permission(self, name):
        return name in self.permissions


def _enforced(monkeypatch):
    rr = SimpleNamespace(policy_enforcement_enabled=True, route_registry_enforced=True)
    monkeypatch.setattr(settings, "route_registry", rr, raising=False)


def test_frames_post_needs_only_read(monkeypatch):
    _enforced(monkeypatch)
    denial = mw._evaluate_route_policy(_request(), "/v1/experience360/frames", _Ctx(["read"]))
    assert denial is None


def test_frames_post_still_denied_without_read(monkeypatch):
    _enforced(monkeypatch)
    denial = mw._evaluate_route_policy(_request(), "/v1/experience360/frames", _Ctx([]))
    assert denial is not None


def test_other_posts_still_require_write(monkeypatch):
    _enforced(monkeypatch)
    denial = mw._evaluate_route_policy(_request(path="/v1/continuations"), "/v1/continuations", _Ctx(["read"]))
    assert denial is not None


def test_read_semantic_set_is_exact_and_mcp_allowlisted():
    assert mw._READ_SEMANTIC_POST_ROUTES == {("POST", "/v1/experience360/frames")}
    assert "/v1/experience360/frames" in mw._MCP_OAUTH_READ_ROUTES
    # write-capable POSTs must never join the delegated-MCP read allowlist
    assert "/v1/continuations" not in mw._MCP_OAUTH_READ_ROUTES


async def test_frames_attribution_is_recorded_as_read(monkeypatch):
    import governance.security.audit_ledger as audit_ledger
    recorded = {}

    class Ledger:
        async def record(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(audit_event_id="audit-1")

    monkeypatch.setattr(audit_ledger, "AuditLedger", Ledger)
    request = _request()
    request.scope["headers"] = [(b"x-aether-access-surface", b"cli")]
    request = Request(request.scope)
    from shared.auth.auth import Role
    request.state.tenant = SimpleNamespace(tenant_id="tenant-a", user_id="u", role=Role.EDITOR, permissions=[])
    request.state.request_id = "r1"
    request.state.access_route_template = "/v1/experience360/frames"
    from starlette.responses import Response
    refs = await mw._record_access_interaction(request, Response(status_code=200))
    assert refs.get("X-Aether-Audit-Event-ID") == "audit-1"
    assert recorded["resource_id"] == "experience360.frame.read"
    assert recorded["action"] == "read"
