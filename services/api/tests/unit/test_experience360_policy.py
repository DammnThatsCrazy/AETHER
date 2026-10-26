"""Focused tests for Experience 360 access-policy routing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from governance.security.access_control import ALL_DOMAINS
from shared.intelligence_projections.contracts import Experience360FrameRequest
from shared.intelligence_projections.generated_registry import (
    PRODUCT_360_SURFACE_DEFINITIONS,
)
from shared.intelligence_projections.policy import (
    AUTHORITY_DOMAIN_BY_REF,
    RequestAccessPolicyEvaluator,
)


@pytest.mark.asyncio
async def test_policy_evaluator_checks_every_authority_domain_before_slot_reads(
    monkeypatch,
) -> None:
    actor = SimpleNamespace(
        actor_id="user-1",
        actor_type="tenant_user",
        tenant_id="tenant-1",
        roles=["tenant_viewer"],
        ip_address="127.0.0.1",
        user_agent="test-agent",
    )
    calls: list[dict] = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            allowed=kwargs["domain"] != "integrations",
            policy_key="access_control.evaluate",
        )

    monkeypatch.setattr(
        "shared.intelligence_projections.policy.tenant_actor", lambda request: actor
    )
    monkeypatch.setattr("shared.intelligence_projections.policy.access_control.evaluate", evaluate)

    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId="tenant-1",
        subject={"kind": "agent", "id": "agent-1"},
        requestedSlotIds=["actor_attribution", "communications"],
    )
    result = await RequestAccessPolicyEvaluator(object()).evaluate(request)

    assert result.frameDisposition.state == "allowed"
    assert result.slotDispositions["actor_attribution"].state == "allowed"
    assert result.slotDispositions["communications"].state == "denied"
    # Communications now declares its observed-event graph authority in
    # addition to the integrations domain; policy must check both.
    assert {call["domain"] for call in calls} == {"profile", "graph", "integrations"}
    assert all(call["target_tenant"] == "tenant-1" for call in calls)
    assert all(call["resource_type"] == "experience360" for call in calls)


def test_every_catalog_authority_reference_has_an_explicit_access_domain() -> None:
    repository = Path(__file__).resolve().parents[4]
    registry_path = repository / "packages/shared/contracts/intelligence-projection-registry.json"
    contract = json.loads(registry_path.read_text(encoding="utf-8"))
    authority_refs = {
        reference
        for surface in contract["productSurfaces"]
        for slot in surface["domainSlots"]
        for reference in slot.get("canonicalAuthorityRefs", [])
    }

    assert authority_refs == set(AUTHORITY_DOMAIN_BY_REF)
    assert set(AUTHORITY_DOMAIN_BY_REF.values()) <= set(ALL_DOMAINS)
    assert set(PRODUCT_360_SURFACE_DEFINITIONS) == {
        surface["id"] for surface in contract["productSurfaces"]
    }


def test_economic360_bindings_declare_ai_execution_fact_authority() -> None:
    repository = Path(__file__).resolve().parents[4]
    registry_path = repository / "packages/shared/contracts/intelligence-projection-registry.json"
    contract = json.loads(registry_path.read_text(encoding="utf-8"))

    for surface in contract["productSurfaces"]:
        for slot in surface["domainSlots"]:
            binds_economic360 = any(
                binding.get("projectionId") == "economic360"
                for binding in slot.get("projectionBindings", [])
            )
            if binds_economic360:
                assert "ai_execution_facts" in slot.get("canonicalAuthorityRefs", []), (
                    f"{surface['id']}.{slot['id']} exposes Economic360 output but omits "
                    "the AI execution cost read authority"
                )
