"""Agent ↔ human must never merge — Scenario D (Blueprint Iota §8.3, §14).

An agent identity (source_kind=agent / canonical entity_type=agent) and a
human person must never auto-merge, even with a matching email or user_id.
The veto AGENT_PERSON_MERGE_ATTEMPT blocks it.
"""
from __future__ import annotations

import os
import sys

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.models import IdentitySignalType  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from services.identity.veto_engine import evaluate_vetoes  # noqa: E402

TENANT = "tenant_agent_human_no_merge"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def source_registry():
    from services.identity.repository import IdentityResolutionRepository

    return SourceIdentityRegistry(IdentityResolutionRepository())


@pytest.mark.asyncio
async def test_agent_human_veto_blocks_merge():
    vetoes = await evaluate_vetoes(
        tenant_id=TENANT,
        candidate_tenant_id=TENANT,
        candidate_entity_types=["agent"],
        candidate_statuses=["active"],
        candidate_verified_emails=[],
        candidate_authenticated_user_ids=[("user_agent_123", "agent_entity_1")],
        candidate_device_ids=[],
        candidate_has_revoked_consent=False,
        candidate_is_deleted=False,
        candidate_is_suppressed=False,
        candidate_source_namespaces=[],
        current_entity_type="person",
        current_authenticated_user_ids=["user_agent_123"],
    )
    types = {v.veto_type.value for v in vetoes}
    assert "agent_person_merge_attempt" in types


@pytest.mark.asyncio
async def test_human_agent_veto_symmetric():
    vetoes = await evaluate_vetoes(
        tenant_id=TENANT,
        candidate_tenant_id=TENANT,
        candidate_entity_types=["person"],
        candidate_statuses=["active"],
        candidate_verified_emails=[],
        candidate_authenticated_user_ids=[("user_human_1", "person_entity_1")],
        candidate_device_ids=[],
        candidate_has_revoked_consent=False,
        candidate_is_deleted=False,
        candidate_is_suppressed=False,
        candidate_source_namespaces=[],
        current_entity_type="agent",
        current_authenticated_user_ids=["user_human_1"],
    )
    types = {v.veto_type.value for v in vetoes}
    assert "agent_person_merge_attempt" in types


@pytest.mark.asyncio
async def test_non_merge_eligible_agent_signals_excluded():
    # agent_id / deployment_id etc are observational, not identity evidence
    from services.identity.merge_policy import MergePolicyContext, evaluate

    ctx = MergePolicyContext(
        tenant_id=TENANT,
        source_tenant_id=TENANT,
        matching_signal_types=[IdentitySignalType.AGENT_ID],
        consent_snapshot={"purposes": {"identity": True}},
        existing_entity_ids=["agent_entity_1"],
    )
    res = evaluate(ctx)
    # agent-only signal must not produce MERGE
    assert res.decision.value != "merge"
    assert any("non_merge_eligible" in code for code in res.reason_codes) or res.confidence_tier.value in ("blocked", "weak")


@pytest.mark.asyncio
async def test_agent_and_human_source_identities_coexist(source_registry):
    human = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        user_id="human_user_1",
    )
    agent = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="agent:runtime",
        source_kind="agent",
        source_namespace="agent:runtime",
        agent_id="agent_001",
    )
    assert human.id != agent.id
    assert human.user_id == "human_user_1"
    assert agent.agent_id == "agent_001"
