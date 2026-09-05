"""Noesis relationship / spine dispatch (Wave 3a) — flag gate + adapter wiring.

The relationship / spine intent family is gated on the Social360 relationship
noesis flag (``settings.social360.noesis_enabled``) read in the service layer:

* OFF  → an honest ``service_disabled`` degraded response (the economic-family
  shape) — the adapter is never constructed.
* ON   → the ``_relationship_spine_dispatch`` routes to the relationship spine
  adapter's per-intent method and wraps its envelope into a NoesisResponse.

The tests monkeypatch the flag and swap in a fake adapter class so they never
import ``services.relationship_intelligence`` (built concurrently).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")

import config.settings as settings_module  # noqa: E402
import services.noesis.adapters.relationship_spine_adapter as adapter_module  # noqa: E402
from services.noesis.models import NoesisQueryRequest, QueryPlan  # noqa: E402
from services.noesis.service import NoesisService, Scope  # noqa: E402
from shared.graph.graph import GraphClient  # noqa: E402


class _FakeRelationshipSpineAdapter:
    """Stands in for RelationshipSpineNoesisAdapter so no read package is needed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, int]] = []

    async def _envelope(self, name: str, tenant_id: str, target: str | None, limit: int) -> dict:
        self.calls.append((name, tenant_id, target, limit))
        return {
            "answer": f"fake {name} digest",
            "results": [{"intent": name, "tenant_id": tenant_id, "subject": target or "current"}],
            "sources": ["relationship_spine"],
            "sufficient": True,
            "degraded": False,
            "reason": None,
        }

    async def relationship_explain(self, tenant_id: str, target: str | None = None, limit: int = 10) -> dict:
        return await self._envelope("relationship_explain", tenant_id, target, limit)

    async def influence_path(self, tenant_id: str, target: str | None = None, limit: int = 10) -> dict:
        return await self._envelope("influence_path", tenant_id, target, limit)

    async def engagement_fidelity(self, tenant_id: str, target: str | None = None, limit: int = 10) -> dict:
        return await self._envelope("engagement_fidelity", tenant_id, target, limit)

    async def incentive_context_explain(self, tenant_id: str, target: str | None = None, limit: int = 10) -> dict:
        return await self._envelope("incentive_context_explain", tenant_id, target, limit)


def _service() -> NoesisService:
    return NoesisService(graph=MagicMock(spec=GraphClient), analytics=MagicMock())


def _scope() -> Scope:
    return Scope(surface="aether", effective_tenant_id="tenant-a", cross_tenant=False, debug_allowed=False)


def _body(message: str = "Show the influence path between ent_1 and ent_4") -> NoesisQueryRequest:
    return NoesisQueryRequest(message=message, surface="aether")


def _set_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    fake_settings = SimpleNamespace(
        social360=SimpleNamespace(noesis_enabled=enabled),
    )
    monkeypatch.setattr(settings_module, "settings", fake_settings)


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, instance: _FakeRelationshipSpineAdapter) -> None:
    monkeypatch.setattr(adapter_module, "RelationshipSpineNoesisAdapter", lambda: instance)


RELATIONSHIP_INTENTS = (
    "relationship_explain",
    "influence_path",
    "engagement_fidelity",
    "incentive_context_explain",
)


@pytest.mark.asyncio
async def test_flag_off_returns_service_disabled_without_constructing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_flag(monkeypatch, enabled=False)
    instance = _FakeRelationshipSpineAdapter()
    _patch_adapter(monkeypatch, instance)
    svc = _service()

    for intent in RELATIONSHIP_INTENTS:
        plan = QueryPlan(intent=intent, target="ent_1", tenant_id="tenant-a", confidence=0.9)
        response = await svc._dispatch(plan, _scope(), _body())

        assert response.intent == intent
        assert response.error is not None
        assert response.error.code == "service_disabled"
        assert "not enabled" in response.answer.lower()
        assert response.results == []
        # The adapter was never constructed while the surface is OFF.
        assert instance.calls == []


@pytest.mark.asyncio
async def test_flag_on_routes_each_intent_to_the_adapter_method(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_flag(monkeypatch, enabled=True)
    instance = _FakeRelationshipSpineAdapter()
    _patch_adapter(monkeypatch, instance)
    svc = _service()

    for intent in RELATIONSHIP_INTENTS:
        plan = QueryPlan(intent=intent, target="ent_1", tenant_id="tenant-a", limit=7, confidence=0.9)
        response = await svc._dispatch(plan, _scope(), _body())

        assert response.intent == intent
        assert response.error is None
        assert response.answer == f"fake {intent} digest"
        assert response.results == [
            {"intent": intent, "tenant_id": "tenant-a", "subject": "ent_1"}
        ]
        # The dispatch passed the effective tenant, target and limit through.
        assert instance.calls[-1] == (intent, "tenant-a", "ent_1", 7)
        assert len(instance.calls) == RELATIONSHIP_INTENTS.index(intent) + 1


@pytest.mark.asyncio
async def test_flag_on_degrades_honestly_when_adapter_returns_degraded_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_flag(monkeypatch, enabled=True)

    class _DegradedAdapter:
        async def engagement_fidelity(self, tenant_id: str, target: str | None = None, limit: int = 10) -> dict:
            return {
                "answer": "The relationship intelligence surface has no persisted evidence for that subject yet.",
                "results": [],
                "sources": ["relationship_spine"],
                "sufficient": False,
                "degraded": True,
                "reason": "no_data",
            }

    monkeypatch.setattr(adapter_module, "RelationshipSpineNoesisAdapter", lambda: _DegradedAdapter())
    svc = _service()

    plan = QueryPlan(intent="engagement_fidelity", target="p_missing", tenant_id="tenant-a", confidence=0.9)
    response = await svc._dispatch(plan, _scope(), _body())

    assert response.error is None
    assert response.intent == "engagement_fidelity"
    assert response.results == []
    assert response.evidence.sufficient is False
    assert response.evidence.insufficient_reason == "no_data"
    assert "no persisted evidence" in response.answer.lower()
