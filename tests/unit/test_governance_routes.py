"""Tests for /v1/governance policy evaluation and audit."""

from __future__ import annotations

import asyncio
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def mod(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        m = importlib.import_module("services.governance.routes")
        importlib.reload(m)
        yield m


def make_req(tenant_id: str = "t-001"):
    return SimpleNamespace(
        state=SimpleNamespace(
            tenant=SimpleNamespace(
                tenant_id=tenant_id,
                require_permission=lambda p: None,
            )
        )
    )


def _eval_body(mod, tenant_id="t-001", context=None):
    return mod.PolicyEvaluationRequest(
        tenantId=tenant_id,
        principal=mod.EntityRef(kind="user", id="u-1"),
        action="data:read",
        resource=mod.EntityRef(kind="resource", id="res-1"),
        context=context or {},
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_evaluate_allows_by_default(mod):
    decision = asyncio.run(mod.evaluate_decision(_eval_body(mod), make_req()))
    assert decision.allowed is True
    assert decision.id is not None
    assert decision.tenantId == "t-001"


def test_evaluate_denies_when_context_has_deny(mod):
    decision = asyncio.run(mod.evaluate_decision(_eval_body(mod, context={"deny": True}), make_req()))
    assert decision.allowed is False


def test_list_decisions_filters_by_tenant(mod):
    asyncio.run(mod.evaluate_decision(_eval_body(mod, tenant_id="t-001"), make_req("t-001")))
    asyncio.run(mod.evaluate_decision(_eval_body(mod, tenant_id="t-002"), make_req("t-002")))
    results = asyncio.run(mod.list_decisions(make_req("t-001"), tenantId="t-001", principal_id=None, allowed=None, limit=50))
    assert len(results) == 1
    assert results[0].tenantId == "t-001"


def test_get_decision_returns_decision(mod):
    created = asyncio.run(mod.evaluate_decision(_eval_body(mod), make_req()))
    fetched = asyncio.run(mod.get_decision(created.id, make_req(), tenantId="t-001"))
    assert fetched.id == created.id
    assert fetched.action == "data:read"


def test_get_decision_wrong_tenant_raises_404(mod):
    created = asyncio.run(mod.evaluate_decision(_eval_body(mod, tenant_id="t-001"), make_req("t-001")))
    with pytest.raises(Exception) as exc:
        asyncio.run(mod.get_decision(created.id, make_req("t-002"), tenantId="t-002"))
    assert "not found" in str(exc.value).lower()


def test_audit_returns_decisions(mod):
    asyncio.run(mod.evaluate_decision(_eval_body(mod), make_req()))
    asyncio.run(mod.evaluate_decision(_eval_body(mod, context={"deny": True}), make_req()))
    results = asyncio.run(mod.audit_trail(make_req(), tenantId="t-001", limit=100, principal_id=None))
    assert len(results) == 2
    allowed_values = {d.allowed for d in results}
    assert True in allowed_values
    assert False in allowed_values
