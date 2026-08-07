"""
Integration tests for read-completeness metadata (Task K).

Capped GET/list endpoints used to return a bare list: a truncated result
was indistinguishable from a complete one (false certainty). The routers
under test now attach an additive `meta` block —
``{"limit": N, "returned": len(rows), "truncated": bool, "has_more": bool}``
— to the existing ``APIResponse`` envelope (or, for the couple of routes
that predate that envelope, at the top level of their existing flat dict)
without changing the shape of ``data``.

Covers a representative endpoint per distinct fetch pattern in each of the
three in-scope routers:

  services/lake/routes.py
    - audit_source_tag   (EXACT — already over-fetches beyond the page cap)
    - query_gold         (HEURISTIC — GoldRepository.get_metrics() has a
                           fixed internal cap with no adjustable limit)

  services/intelligence/routes.py
    - anomaly_alerts          (EXACT — Gold `get_highlights(limit=...)`)
    - list_outcomes           (EXACT — repository `list_for_tenant(limit=...)`)
    - list_playbook_runs      (EXACT — nested resource, `find_many(limit=...)`)

  services/profile/routes.py
    - get_profile_outcomes  (EXACT — tenant+entity scoped `list_for_tenant`)
    - get_flows             (EXACT — dual from/to fetch merged before slice)
    - get_split_history     (EXACT — IdentityResolutionRepository)
    - get_owned_agents      (HEURISTIC — AgentConfigRepository.list_for_owner()
                              has a fixed internal cap with no adjustable
                              limit, and tenant-filters *after* fetching)

Endpoints that delegate their fetch entirely to Profile360Aggregator /
IntelligenceAggregator / ProfileComposer / AgentProfile360Composer (all
defined outside the three in-scope router files) are out of scope for this
change — see the comment above `_probe_completeness` in
services/profile/routes.py.

Route functions are invoked directly as coroutines (bypassing the ASGI/HTTP
layer), mirroring the existing tests/intelligence/test_reliability.py
pattern: the tenant/permission boundary is a lightweight stand-in, not the
transport, and this suite is about the response `meta`, not routing/auth.
Because FastAPI's `Query(...)` defaults are only resolved by FastAPI's own
dependency-injection call path, every `limit` is passed explicitly here.

Run (from Backend Architecture/aether-backend):
    AETHER_ENV=local python -m pytest tests/integration/test_read_completeness.py -q -n0
"""

from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.lake import bronze_market, gold_identity  # noqa: E402
from repositories.repos import (  # noqa: E402
    AgentConfigRepository,
    DelegationRepository,
    TransferRepository,
    reset_in_memory_stores,
)
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.intelligence.repositories import (  # noqa: E402
    OutcomeRepository,
    PlaybookRepository,
    PlaybookRunRepository,
)
from services.intelligence import routes as intel_routes  # noqa: E402
from services.lake import routes as lake_routes  # noqa: E402
from services.profile import routes as profile_routes  # noqa: E402


# ── Test scaffolding ─────────────────────────────────────────────────────

class _Tenant:
    """Authenticated-caller stand-in — mirrors tests/intelligence/test_reliability.py."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.user_id = "read-completeness-test-user"

    def require_permission(self, permission: str) -> None:
        return None


def _req(tenant_id: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant(tenant_id)))


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def clean():
    reset_in_memory_stores()


# ═══════════════════════════════════════════════════════════════════════════
# Helper-contract unit tests — lock down the exact/heuristic formulas
# themselves, independent of any endpoint plumbing.
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mod", [intel_routes, lake_routes, profile_routes])
def test_probe_completeness_contract(mod):
    """Exact mode: fetched = rows returned by a limit+1 probe."""
    assert mod._probe_completeness(10, 10) == {
        "limit": 10, "returned": 10, "truncated": False, "has_more": False,
    }
    assert mod._probe_completeness(10, 11) == {
        "limit": 10, "returned": 10, "truncated": True, "has_more": True,
    }
    assert mod._probe_completeness(10, 3) == {
        "limit": 10, "returned": 3, "truncated": False, "has_more": False,
    }


@pytest.mark.parametrize("mod", [intel_routes, lake_routes, profile_routes])
def test_heuristic_completeness_contract(mod):
    """Heuristic mode: truncated iff the result exactly fills the limit."""
    assert mod._heuristic_completeness(10, 10) == {
        "limit": 10, "returned": 10, "truncated": True, "has_more": True,
    }
    assert mod._heuristic_completeness(10, 9) == {
        "limit": 10, "returned": 9, "truncated": False, "has_more": False,
    }
    assert mod._heuristic_completeness(10, 0) == {
        "limit": 10, "returned": 0, "truncated": False, "has_more": False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# services/lake/routes.py
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_lake_audit_source_tag_exact_truncation():
    """query_by_source_tag() already fetches beyond the 50-row page cap
    (its own default limit=100), so audit_source_tag()'s completeness is
    exact, not a guess."""
    tag = _unique("audit-over")
    await bronze_market.ingest_batch(records=[{} for _ in range(51)], source="test", source_tag=tag)

    resp = await lake_routes.audit_source_tag("market", tag, _req(_unique("tenant")))
    meta = resp["meta"]
    assert meta["limit"] == 50
    assert meta["returned"] == 50
    assert meta["truncated"] is True
    assert meta["has_more"] is True
    assert len(resp["data"]["records"]) == 50  # data shape/size unchanged

    tag = _unique("audit-under")
    await bronze_market.ingest_batch(records=[{} for _ in range(10)], source="test", source_tag=tag)

    resp = await lake_routes.audit_source_tag("market", tag, _req(_unique("tenant")))
    meta = resp["meta"]
    assert meta["returned"] == 10
    assert meta["truncated"] is False
    assert meta["has_more"] is False


@pytest.mark.asyncio
async def test_lake_query_gold_heuristic_truncation():
    """GoldRepository.get_metrics() enforces a fixed internal cap (200) with
    no adjustable limit parameter — heuristic completeness only."""
    tenant_id = _unique("tenant")
    entity_id = _unique("entity")
    for i in range(200):
        await gold_identity.materialize(
            metric_name=f"metric-{i}", entity_id=entity_id, entity_type="wallet",
            value={"i": i}, tenant_id=tenant_id,
        )

    resp = await lake_routes.query_gold("identity", entity_id, _req(tenant_id))
    meta = resp["meta"]
    assert meta["limit"] == 200
    assert meta["returned"] == 200
    assert meta["truncated"] is True
    assert meta["has_more"] is True

    tenant_id = _unique("tenant")
    entity_id = _unique("entity")
    for i in range(5):
        await gold_identity.materialize(
            metric_name=f"metric-{i}", entity_id=entity_id, entity_type="wallet",
            value={"i": i}, tenant_id=tenant_id,
        )

    resp = await lake_routes.query_gold("identity", entity_id, _req(tenant_id))
    meta = resp["meta"]
    assert meta["returned"] == 5
    assert meta["truncated"] is False
    assert meta["has_more"] is False


# ═══════════════════════════════════════════════════════════════════════════
# services/intelligence/routes.py
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_intelligence_alerts_exact_truncation():
    """anomaly_alerts() probes gold_identity.get_highlights() with limit+1."""
    tenant_id = _unique("tenant")
    for i in range(51):
        await gold_identity.materialize(
            metric_name="anomaly_alert", entity_id=_unique("wallet"), entity_type="wallet",
            value={"score": i}, tenant_id=tenant_id,
        )

    resp = await intel_routes.anomaly_alerts(_req(tenant_id), limit=50)
    meta = resp["meta"]
    assert meta["limit"] == 50
    assert meta["returned"] == 50
    assert meta["truncated"] is True
    assert meta["has_more"] is True
    assert resp["data"]["count"] == 50

    tenant_id = _unique("tenant")
    for i in range(7):
        await gold_identity.materialize(
            metric_name="anomaly_alert", entity_id=_unique("wallet"), entity_type="wallet",
            value={"score": i}, tenant_id=tenant_id,
        )

    resp = await intel_routes.anomaly_alerts(_req(tenant_id), limit=50)
    meta = resp["meta"]
    assert meta["returned"] == 7
    assert meta["truncated"] is False
    assert meta["has_more"] is False


@pytest.mark.asyncio
async def test_intelligence_outcomes_exact_truncation():
    """list_outcomes() probes OutcomeRepository.list_for_tenant() with limit+1."""
    tenant_id = _unique("tenant")
    outcomes = OutcomeRepository()
    for _ in range(51):
        await outcomes.insert(str(uuid.uuid4()), {"tenant_id": tenant_id, "label": "success"})

    resp = await intel_routes.list_outcomes(_req(tenant_id), limit=50)
    meta = resp["meta"]
    assert meta["limit"] == 50
    assert meta["returned"] == 50
    assert meta["truncated"] is True
    assert meta["has_more"] is True

    tenant_id = _unique("tenant")
    for _ in range(9):
        await outcomes.insert(str(uuid.uuid4()), {"tenant_id": tenant_id, "label": "success"})

    resp = await intel_routes.list_outcomes(_req(tenant_id), limit=50)
    meta = resp["meta"]
    assert meta["returned"] == 9
    assert meta["truncated"] is False
    assert meta["has_more"] is False


@pytest.mark.asyncio
async def test_intelligence_playbook_runs_exact_truncation():
    """list_playbook_runs() probes PlaybookRunRepository.find_many() with limit+1."""
    playbooks = PlaybookRepository()
    runs = PlaybookRunRepository()

    tenant_id = _unique("tenant")
    playbook_id = str(uuid.uuid4())
    await playbooks.insert(playbook_id, {"tenant_id": tenant_id, "playbook_id": playbook_id, "name": "pb"})
    for _ in range(51):
        await runs.insert(str(uuid.uuid4()), {"tenant_id": tenant_id, "playbook_id": playbook_id})

    resp = await intel_routes.list_playbook_runs(playbook_id, _req(tenant_id), limit=50)
    meta = resp["meta"]
    assert meta["limit"] == 50
    assert meta["returned"] == 50
    assert meta["truncated"] is True
    assert meta["has_more"] is True

    tenant_id = _unique("tenant")
    playbook_id = str(uuid.uuid4())
    await playbooks.insert(playbook_id, {"tenant_id": tenant_id, "playbook_id": playbook_id, "name": "pb2"})
    for _ in range(4):
        await runs.insert(str(uuid.uuid4()), {"tenant_id": tenant_id, "playbook_id": playbook_id})

    resp = await intel_routes.list_playbook_runs(playbook_id, _req(tenant_id), limit=50)
    meta = resp["meta"]
    assert meta["returned"] == 4
    assert meta["truncated"] is False
    assert meta["has_more"] is False


# ═══════════════════════════════════════════════════════════════════════════
# services/profile/routes.py
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_profile_outcomes_exact_truncation():
    """get_profile_outcomes() probes OutcomeRepository.list_for_tenant()
    (tenant+entity scoped) with limit+1."""
    tenant_id = _unique("tenant")
    user_id = _unique("user")
    outcomes = OutcomeRepository()
    for _ in range(21):
        await outcomes.insert(str(uuid.uuid4()), {"tenant_id": tenant_id, "entity_id": user_id})

    resp = await profile_routes.get_profile_outcomes(user_id, _req(tenant_id), limit=20)
    meta = resp["meta"]
    assert meta["limit"] == 20
    assert meta["returned"] == 20
    assert meta["truncated"] is True
    assert meta["has_more"] is True

    tenant_id = _unique("tenant")
    user_id = _unique("user")
    for _ in range(3):
        await outcomes.insert(str(uuid.uuid4()), {"tenant_id": tenant_id, "entity_id": user_id})

    resp = await profile_routes.get_profile_outcomes(user_id, _req(tenant_id), limit=20)
    meta = resp["meta"]
    assert meta["returned"] == 3
    assert meta["truncated"] is False
    assert meta["has_more"] is False


@pytest.mark.asyncio
async def test_profile_flows_exact_truncation():
    """get_flows() probes TransferRepository.list_for_entity() with limit+1
    (list_for_entity merges from/to matches and applies `limit` as its own
    final slice, so passing limit+1 straight through is exact)."""
    tenant_id = _unique("tenant")
    user_id = _unique("user")
    transfers = TransferRepository()
    for _ in range(11):
        await transfers.record_transfer(
            transfer_id=str(uuid.uuid4()), tenant_id=tenant_id,
            from_entity_id=user_id, to_entity_id=_unique("counterparty"),
            asset_id="USDC", amount="1.00",
        )

    resp = await profile_routes.get_flows(user_id, _req(tenant_id), limit=10)
    meta = resp["meta"]
    assert meta["limit"] == 10
    assert meta["returned"] == 10
    assert meta["truncated"] is True
    assert meta["has_more"] is True

    tenant_id = _unique("tenant")
    user_id = _unique("user")
    for _ in range(4):
        await transfers.record_transfer(
            transfer_id=str(uuid.uuid4()), tenant_id=tenant_id,
            from_entity_id=user_id, to_entity_id=_unique("counterparty"),
            asset_id="USDC", amount="1.00",
        )

    resp = await profile_routes.get_flows(user_id, _req(tenant_id), limit=10)
    meta = resp["meta"]
    assert meta["returned"] == 4
    assert meta["truncated"] is False
    assert meta["has_more"] is False


@pytest.mark.asyncio
async def test_profile_split_history_exact_truncation():
    """get_split_history() probes IdentityResolutionRepository.get_split_history()
    with limit+1."""
    tenant_id = _unique("tenant")
    user_id = _unique("user")
    repo = IdentityResolutionRepository()
    for _ in range(11):
        await repo.create_split_event(
            tenant_id=tenant_id, original_entity_id=user_id,
            resulting_entity_ids=[_unique("child")], reason="test-split",
            actor_type="system", actor_id="test",
        )

    resp = await profile_routes.get_split_history(user_id, _req(tenant_id), limit=10)
    meta = resp["meta"]
    assert meta["limit"] == 10
    assert meta["returned"] == 10
    assert meta["truncated"] is True
    assert meta["has_more"] is True
    assert len(resp["data"]["items"]) == 10  # data shape/size unchanged

    tenant_id = _unique("tenant")
    user_id = _unique("user")
    for _ in range(2):
        await repo.create_split_event(
            tenant_id=tenant_id, original_entity_id=user_id,
            resulting_entity_ids=[_unique("child")], reason="test-split",
            actor_type="system", actor_id="test",
        )

    resp = await profile_routes.get_split_history(user_id, _req(tenant_id), limit=10)
    meta = resp["meta"]
    assert meta["returned"] == 2
    assert meta["truncated"] is False
    assert meta["has_more"] is False


@pytest.mark.asyncio
async def test_profile_owned_agents_heuristic_truncation():
    """get_owned_agents() has no adjustable-limit read available
    (AgentConfigRepository.list_for_owner() enforces a fixed internal cap of
    200 with no limit parameter, and is not tenant-scoped in the query — the
    route filters by tenant afterward) — heuristic completeness only."""
    tenant_id = _unique("tenant")
    user_id = _unique("user")
    repo = AgentConfigRepository()
    for _ in range(200):
        await repo.register(
            agent_id=str(uuid.uuid4()), owner_entity_id=user_id,
            tenant_id=tenant_id, model="test-model",
        )

    resp = await profile_routes.get_owned_agents(user_id, _req(tenant_id))
    meta = resp["meta"]
    assert meta["limit"] == 200
    assert meta["returned"] == 200
    assert meta["truncated"] is True
    assert meta["has_more"] is True

    tenant_id = _unique("tenant")
    user_id = _unique("user")
    for _ in range(6):
        await repo.register(
            agent_id=str(uuid.uuid4()), owner_entity_id=user_id,
            tenant_id=tenant_id, model="test-model",
        )

    resp = await profile_routes.get_owned_agents(user_id, _req(tenant_id))
    meta = resp["meta"]
    assert meta["returned"] == 6
    assert meta["truncated"] is False
    assert meta["has_more"] is False


@pytest.mark.asyncio
async def test_profile_delegations_heuristic_truncation_nested_meta():
    """get_delegations() has two independently-capped lists (granted/
    received), neither with an adjustable limit — heuristic completeness,
    reported per list via a nested meta (an additive generalization of the
    single-list {limit, returned, truncated, has_more} shape)."""
    tenant_id = _unique("tenant")
    user_id = _unique("user")
    repo = DelegationRepository()
    for i in range(201):
        await repo.grant(str(uuid.uuid4()), tenant_id, user_id, _unique("grantee"), {"scope": "x"})

    resp = await profile_routes.get_delegations(
        user_id, _req(tenant_id), role="grantor", active=True, repo=repo,
    )
    meta = resp["meta"]
    assert meta["granted"] == {"limit": 200, "returned": 200, "truncated": True, "has_more": True}
    # role="grantor" means "received" was never queried — reported as the
    # untouched, not-truncated zero case rather than silently omitted.
    assert meta["received"] == {"limit": 200, "returned": 0, "truncated": False, "has_more": False}
    assert len(resp["data"]["granted"]) == 200
    assert resp["data"]["received"] == []

    tenant_id = _unique("tenant")
    user_id = _unique("user")
    for i in range(5):
        await repo.grant(str(uuid.uuid4()), tenant_id, user_id, _unique("grantee"), {"scope": "x"})

    resp = await profile_routes.get_delegations(
        user_id, _req(tenant_id), role="grantor", active=True, repo=repo,
    )
    meta = resp["meta"]
    assert meta["granted"] == {"limit": 200, "returned": 5, "truncated": False, "has_more": False}
