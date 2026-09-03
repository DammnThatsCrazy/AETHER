"""Population360 P3.2 — membership writes are consent-gated.

A governed join evaluates *server-authoritative* consent for the member data
subject under the population's declared ``consent_purpose``
(``services.consent.authority.evaluate_consent``) — fail-closed, never merely a
tenant ``write`` permission. Joining is gated; leaving is always honored, so a
revoked subject can still exit a cohort.

Suites pin: (1) join without any server receipt is denied and writes nothing;
(2) a revoked receipt denies; (3) an unknown purpose denies; (4) a granted
receipt allows; (5) a batch route aborts wholesale (no partial join) when any
member is denied; (6) a leave is NOT blocked by a subsequently revoked receipt.
"""

from __future__ import annotations

import dataclasses

import pytest

from config.settings import settings
from repositories.graph_mutation_ledger import reset_graph_ledger_memory
from services.consent.authority import ConsentReceiptRepository
from services.population.governance import (
    MembershipConsentDeniedError,
    PopulationMembershipGovernor,
)
from services.population.models import PopulationType
from services.population.registry import (
    definition_repo,
    membership_repo,
    population_repo,
)
from shared.common.common import ForbiddenError
from shared.graph.graph import GraphClient


@pytest.fixture(autouse=True)
def _reset_stores():
    population_repo._store.clear()
    membership_repo._store.clear()
    definition_repo._store.clear()
    ConsentReceiptRepository()._store.clear()
    reset_graph_ledger_memory()
    yield
    population_repo._store.clear()
    membership_repo._store.clear()
    definition_repo._store.clear()
    ConsentReceiptRepository()._store.clear()
    reset_graph_ledger_memory()


@pytest.fixture()
def enforce_mode(monkeypatch):
    monkeypatch.setattr(
        settings,
        "temporal_observatory",
        dataclasses.replace(
            settings.temporal_observatory, mutation_gateway_mode="enforce"
        ),
    )
    return "enforce"


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


async def _population(tenant_id: str = "tenant_a", **overrides) -> dict:
    return await population_repo.create_population(
        name="Consent-gated segment",
        population_type=PopulationType.SEGMENT,
        definition={"filters": [{"field": "lifetime_value", "op": "gt", "value": 1000}]},
        source_tag="p3_2_test",
        tenant_id=tenant_id,
        **overrides,
    )


async def _grant(entity_id: str, tenant_id: str = "tenant_a", purpose: str = "analytics",
                 state: str = "granted") -> None:
    await ConsentReceiptRepository().record(
        receipt_id=f"rcpt_{tenant_id}_{entity_id}_{state}",
        tenant_id=tenant_id,
        purpose=purpose,
        state=state,
        subject_id=entity_id,
    )


@pytest.mark.asyncio
async def test_join_without_any_receipt_is_denied(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)

    with pytest.raises(MembershipConsentDeniedError) as excinfo:
        await governor.add_membership(population=pop, entity_id="entity_1",
                                      tenant_id="tenant_a")
    assert excinfo.value.reason_code == "consent_receipt_missing"

    # Fail-closed: nothing was written anywhere.
    assert await membership_repo.get_members(pop["id"]) == []
    edges = await graph.get_edges(pop["id"], "MEMBER_OF", direction="in",
                                  include_revoked=True)
    assert edges == []


@pytest.mark.asyncio
async def test_revoked_receipt_denies(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)
    await _grant("entity_1", state="revoked")

    with pytest.raises(MembershipConsentDeniedError) as excinfo:
        await governor.add_membership(population=pop, entity_id="entity_1",
                                      tenant_id="tenant_a")
    assert excinfo.value.reason_code == "consent_revoked"


@pytest.mark.asyncio
async def test_unknown_population_purpose_denies(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a", consent_purpose="not_a_registry_purpose")
    governor = PopulationMembershipGovernor(graph_client=graph)

    with pytest.raises(MembershipConsentDeniedError) as excinfo:
        await governor.add_membership(population=pop, entity_id="entity_1",
                                      tenant_id="tenant_a")
    assert excinfo.value.reason_code == "consent_unknown"
    assert excinfo.value.purpose == "not_a_registry_purpose"


@pytest.mark.asyncio
async def test_granted_receipt_allows_join(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)
    await _grant("entity_1")

    row = await governor.add_membership(population=pop, entity_id="entity_1",
                                        tenant_id="tenant_a")
    assert row["membership_state"] == "active"


@pytest.mark.asyncio
async def test_route_batch_aborts_wholesale_when_any_member_denied():
    """A denied subject fails the whole batch before any partial join lands."""
    from unittest.mock import AsyncMock

    from services.population.models import MembershipAdd
    from services.population.routes import add_members

    pop = await _population("tenant_a")
    await _grant("entity_1")  # entity_2 has NO receipt -> would be denied
    graph = await _graph()

    with pytest.raises(ForbiddenError) as excinfo:
        await add_members(
            population_id=pop["id"],
            body=MembershipAdd(entity_ids=["entity_1", "entity_2"],
                               source_tag="p3_2"),
            request=_request("tenant_a"),
            graph=graph,
            producer=AsyncMock(),
        )
    assert excinfo.value.details.get("reason_code") == "consent_receipt_missing"

    # entity_1 was granted but the batch never partially landed.
    assert await membership_repo.get_members(pop["id"]) == []
    edges = await graph.get_edges(pop["id"], "MEMBER_OF", direction="in",
                                  include_revoked=True)
    assert edges == []


@pytest.mark.asyncio
async def test_leave_is_not_blocked_by_revoked_receipt(enforce_mode):
    """Joining is gated; leaving is always honored."""
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)
    await _grant("entity_1", state="granted")

    await governor.add_membership(population=pop, entity_id="entity_1",
                                  tenant_id="tenant_a")

    # Subject revokes AFTER joining: an add would now be refused...
    await _grant("entity_1", state="revoked")
    with pytest.raises(MembershipConsentDeniedError):
        await governor.add_membership(population=pop, entity_id="entity_1",
                                      tenant_id="tenant_a")

    # ...but the leave is honored, not blocked by the revoked grant.
    row = await governor.remove_membership(population=pop, entity_id="entity_1",
                                           tenant_id="tenant_a",
                                           reason="revoked_consent")
    assert row["membership_state"] == "left"
    assert await membership_repo.count_active_members(pop["id"]) == 0


def _request(tenant_id: str):
    from unittest.mock import MagicMock

    req = MagicMock()
    req.state.tenant = _Tenant(tenant_id)
    return req


class _Tenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.user_id = "u1"

    def require_permission(self, perm: str) -> None:
        return None
