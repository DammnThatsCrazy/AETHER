"""Tests for /v1/investigations CRUD and status transitions."""

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
        m = importlib.import_module("services.investigation.routes")
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


class _NoOpProducer:
    async def publish(self, *args, **kwargs):
        pass


_producer = _NoOpProducer()


def _create_body(mod, tenant_id="t-001", title="Test Case", created_by="user_1"):
    return mod.CreateCaseRequest(tenantId=tenant_id, title=title, createdBy=created_by)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_create_investigation_returns_open_case(mod):
    body = _create_body(mod)
    case = asyncio.run(mod.create_case(body, make_req(), _producer))
    assert case.status == "open"
    assert case.tenantId == "t-001"
    assert case.title == "Test Case"
    assert case.id is not None


def test_list_investigations_filters_by_tenant(mod):
    asyncio.run(mod.create_case(_create_body(mod, tenant_id="t-001", title="A"), make_req("t-001"), _producer))
    asyncio.run(mod.create_case(_create_body(mod, tenant_id="t-002", title="B"), make_req("t-002"), _producer))
    results = asyncio.run(mod.list_cases(make_req("t-001"), tenantId="t-001", status=None, limit=50))
    assert len(results) == 1
    assert results[0].tenantId == "t-001"


def test_list_investigations_filters_by_status(mod):
    asyncio.run(mod.create_case(_create_body(mod, title="Open1"), make_req(), _producer))
    case2 = asyncio.run(mod.create_case(_create_body(mod, title="Open2"), make_req(), _producer))
    asyncio.run(
        mod.transition_status(
            case2.id,
            mod.StatusTransitionRequest(tenantId="t-001", status="closed"),
            make_req(),
            _producer,
        )
    )
    open_cases = asyncio.run(mod.list_cases(make_req(), tenantId="t-001", status="open", limit=50))
    assert len(open_cases) == 1
    assert open_cases[0].title == "Open1"


def test_get_investigation_returns_case(mod):
    created = asyncio.run(mod.create_case(_create_body(mod), make_req(), _producer))
    fetched = asyncio.run(mod.get_case(created.id, make_req(), tenantId="t-001"))
    assert fetched.id == created.id
    assert fetched.title == "Test Case"


def test_get_investigation_wrong_tenant_raises_404(mod):
    created = asyncio.run(mod.create_case(_create_body(mod, tenant_id="t-001"), make_req("t-001"), _producer))
    with pytest.raises(Exception) as exc:
        asyncio.run(mod.get_case(created.id, make_req("t-002"), tenantId="t-002"))
    assert "not found" in str(exc.value).lower()


def test_transition_status_updates_status(mod):
    created = asyncio.run(mod.create_case(_create_body(mod), make_req(), _producer))
    updated = asyncio.run(
        mod.transition_status(
            created.id,
            mod.StatusTransitionRequest(tenantId="t-001", status="active"),
            make_req(),
            _producer,
        )
    )
    assert updated.status == "active"
    assert updated.id == created.id


def test_add_evidence_appends_to_case(mod):
    created = asyncio.run(mod.create_case(_create_body(mod), make_req(), _producer))
    evidence_body = mod.AddEvidenceRequest(
        tenantId="t-001",
        evidence=[mod.EvidenceRef(id="ev-1", type="event", source="stream-a")],
    )
    updated = asyncio.run(mod.add_evidence(created.id, evidence_body, make_req(), _producer))
    assert len(updated.evidence) == 1
    assert updated.evidence[0].id == "ev-1"


def test_add_annotation_creates_annotation(mod):
    created = asyncio.run(mod.create_case(_create_body(mod), make_req(), _producer))
    annotation_body = mod.AddAnnotationRequest(
        tenantId="t-001",
        body="Suspicious pattern observed",
        authorId="analyst_1",
    )
    updated = asyncio.run(mod.add_annotation(created.id, annotation_body, make_req(), _producer))
    assert len(updated.annotations) == 1
    ann = updated.annotations[0]
    assert ann.id is not None
    assert ann.authorId == "analyst_1"
    import uuid
    uuid.UUID(ann.id)
