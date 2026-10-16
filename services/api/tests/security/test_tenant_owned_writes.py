"""Writes keyed by a reused id never replace another tenant's row.

Every test runs against the in-memory backend and, when
``REPOSITORY_TEST_DATABASE_URL`` (or ``DATABASE_URL``) points at a database,
against PostgreSQL, where the ownership predicate lives in SQL. Each test uses
its own tenants and ids, so the shared database needs no truncation.
"""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

import repositories.repos as repos  # noqa: E402
from repositories.commerce_repos import ResourcesRepository  # noqa: E402
from repositories.repos import (  # noqa: E402
    BaseRepository,
    BehaviorProfileRepository,
    DelegationRepository,
    EntityRepository,
    EventEnvelopeRepository,
    IdentityRepository,
    JourneyChainRepository,
    TenantOwnedRepository,
    UserRepository,
)
from shared.common.common import ConflictError  # noqa: E402
from shared.events.events import Topic  # noqa: E402

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

PG_URL = os.getenv("REPOSITORY_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@pytest.fixture(params=["inmem", "pg"])
async def backend(request, monkeypatch):
    """Route every repository's pool to the requested backend."""
    pool = None
    if request.param == "pg":
        if asyncpg is None or not PG_URL:
            pytest.skip("REPOSITORY_TEST_DATABASE_URL not set")
        try:
            pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=4)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"postgres unavailable: {exc}")

    async def _pool():
        return pool

    monkeypatch.setattr(repos, "get_pool", _pool)
    try:
        yield SimpleNamespace(kind=request.param, pool=pool)
    finally:
        if pool is not None:
            await pool.close()


def _ids() -> tuple[str, str, str]:
    token = uuid.uuid4().hex[:10]
    return f"tenant_a_{token}", f"tenant_b_{token}", token


# ── client-chosen ids: first tenant keeps the id ─────────────────────────────


async def test_entity_id_reused_by_another_tenant_conflicts_and_keeps_the_row(backend):
    a, b, token = _ids()
    entities = EntityRepository()
    entity_id = f"acme-{token}"
    await entities.create_entity(entity_id, a, "organization", display_name="Acme A",
                                 metadata={"crm": "a-only"})

    with pytest.raises(ConflictError) as raised:
        await entities.create_entity(entity_id, b, "organization", display_name="Taken by B")
    assert str(raised.value) == str(ConflictError())  # the same text as any conflict

    row = await entities.find_by_id(entity_id)
    assert row["tenant_id"] == a
    assert row["display_name"] == "Acme A" and row["metadata"] == {"crm": "a-only"}
    assert [e["entity_id"] for e in await entities.list_by_tenant(b)] == []
    if backend.pool is not None:
        column = await backend.pool.fetchval("SELECT tenant_id FROM entities WHERE id = $1", entity_id)
        assert column == a


async def test_same_tenant_rewrite_still_replaces_its_own_row(backend):
    a, _, token = _ids()
    entities = EntityRepository()
    entity_id = f"acme-{token}"
    await entities.create_entity(entity_id, a, "organization", display_name="v1")
    await entities.create_entity(entity_id, a, "organization", display_name="v2")
    assert (await entities.find_by_id(entity_id))["display_name"] == "v2"


async def test_update_cannot_move_a_row_to_another_tenant(backend):
    a, b, token = _ids()
    entities = EntityRepository()
    entity_id = f"acme-{token}"
    await entities.create_entity(entity_id, a, "organization", display_name="A")

    with pytest.raises(ConflictError):
        await entities.update(entity_id, {"tenant_id": b, "display_name": "B"})
    with pytest.raises(ConflictError):
        await entities.update(entity_id, {"tenantId": b, "display_name": "B"})
    row = await entities.find_by_id(entity_id)
    assert row["tenant_id"] == a and row["display_name"] == "A"

    await entities.update(entity_id, {"display_name": "A2"})
    assert (await entities.find_by_id(entity_id))["display_name"] == "A2"


async def test_delegation_id_reused_by_another_tenant_conflicts(backend):
    a, b, token = _ids()
    delegations = DelegationRepository()
    delegation_id = f"del-{token}"
    await delegations.grant(delegation_id, a, "grantor-a", "grantee-a", {"actions": ["read"]})
    with pytest.raises(ConflictError):
        await delegations.grant(delegation_id, b, "grantor-b", "grantee-b", {"actions": ["*"]})
    row = await delegations.find_by_id(delegation_id)
    assert row["tenant_id"] == a and row["scope"] == {"actions": ["read"]}


async def test_wallet_id_reused_by_another_tenant_conflicts_with_the_generic_text(backend):
    from repositories.repos import WalletRepository

    a, b, token = _ids()
    wallets = WalletRepository()
    wallet_id = f"wallet-{token}"
    await wallets.link_wallet(wallet_id, "owner-a", a, "eth", "0xa")
    with pytest.raises(ConflictError) as raised:
        await wallets.link_wallet(wallet_id, "owner-b", b, "eth", "0xb")
    assert str(raised.value) == str(ConflictError())
    assert (await wallets.find_by_id(wallet_id))["tenant_id"] == a


async def test_x402_resource_id_reused_by_another_tenant_conflicts(backend):
    a, b, token = _ids()
    resources = ResourcesRepository()
    resource_id = f"res-{token}"
    await resources.create({"resource_id": resource_id, "tenant_id": a, "price_usd": 5.0})
    with pytest.raises(ConflictError):
        await resources.create({"resource_id": resource_id, "tenant_id": b, "price_usd": 0.0})
    row = await resources.get(resource_id)
    assert row["tenant_id"] == a and row["price_usd"] == 5.0


async def test_record_naming_no_tenant_cannot_replace_an_owned_row(backend):
    a, _, token = _ids()
    entities = EntityRepository()
    entity_id = f"acme-{token}"
    await entities.create_entity(entity_id, a, "organization", display_name="A")
    with pytest.raises(ConflictError):
        await entities.insert(entity_id, {"display_name": "unowned"})
    assert (await entities.find_by_id(entity_id))["display_name"] == "A"


async def test_users_table_keeps_moving_a_principal_between_tenants(backend):
    a, b, token = _ids()
    users = UserRepository()
    user_id = f"user-{token}"
    await users.insert(user_id, {"tenant_id": a, "email": f"{token}@example.com", "status": "active"})
    await users.update(user_id, {"tenant_id": b})
    assert (await users.find_by_id(user_id))["tenant_id"] == b


async def test_tenant_owned_upsert_refuses_a_row_without_an_owner(backend):
    a, _, token = _ids()

    class _Registry(TenantOwnedRepository):
        def __init__(self) -> None:
            super().__init__("tenant_owned_write_probe")

    registry = _Registry()
    record_id = f"legacy-{token}"
    if backend.pool is not None:
        await registry._ensure_table()
        await backend.pool.execute(
            "INSERT INTO tenant_owned_write_probe (id, data, tenant_id) VALUES ($1, $2::jsonb, NULL)",
            record_id, json.dumps({"id": record_id, "label": "legacy"}),
        )
    else:
        registry._store[record_id] = {"id": record_id, "label": "legacy"}

    with pytest.raises(ConflictError):
        await registry.upsert(record_id, {"label": "adopted"}, a)
    assert (await BaseRepository.find_by_id(registry, record_id))["label"] == "legacy"


async def test_profiles_for_one_user_id_coexist_across_tenants(backend):
    a, b, token = _ids()

    class _Cache:
        async def get_json(self, key):
            return None

        async def set_json(self, key, value, ttl=None):
            return None

        async def delete(self, key):
            return None

    from shared.graph.graph import GraphClient, user_vertex_id

    graph = GraphClient()
    identity = IdentityRepository(graph, _Cache())
    user_id = f"user-{token}"
    await identity.upsert_profile(a, user_id, {"email": "a@example.com"})
    await identity.upsert_profile(b, user_id, {"email": "b@example.com"})
    await identity.upsert_profile(a, user_id, {"name": "A"})

    profile_a = await identity.get_profile(a, user_id)
    assert profile_a["email"] == "a@example.com" and profile_a["name"] == "A"
    assert profile_a["user_id"] == user_id
    assert (await identity.get_profile(b, user_id))["email"] == "b@example.com"
    vertex_b = await graph.get_vertex(user_vertex_id(b, user_id))
    assert vertex_b.properties["tenant_id"] == b and vertex_b.properties["user_id"] == user_id
    assert await graph.get_vertex(user_id) is None


async def test_restated_behavioral_signals_coexist_across_tenants(backend):
    from repositories.repos import SignalRepository

    a, b, token = _ids()
    signals = SignalRepository()
    signal_id = f"CHURN:entity-{token}:identity-restatement"
    for tenant in (a, b):
        await signals.upsert_signal({
            "signal_id": signal_id, "entity_id": f"entity-{token}", "tenant_id": tenant,
        })
    for tenant in (a, b):
        rows = await signals.list_for_entity(f"entity-{token}", tenant)
        assert [(r["signal_id"], r["tenant_id"]) for r in rows] == [(signal_id, tenant)]
    assert await signals.delete_for_entity(f"entity-{token}", a) == 1
    assert await signals.list_for_entity(f"entity-{token}", a) == []
    assert len(await signals.list_for_entity(f"entity-{token}", b)) == 1


async def test_provenance_records_for_one_entity_coexist_across_tenants(monkeypatch):
    from shared.cis.provenance import ProvenanceRecord, ProvenanceTracker

    monkeypatch.setenv("AETHER_ENV", "local")
    a, b, token = _ids()
    tracker = ProvenanceTracker()
    entity_id = f"entity-{token}"
    for tenant, origin in ((a, "agent-a"), (b, "agent-b")):
        await tracker.record(ProvenanceRecord(
            entity_id=entity_id, entity_type="node", tenant_id=tenant,
            lineage_hash="h", origin_agent_id=origin,
        ))
    await tracker.update_contamination_score(entity_id, b, 0.9)
    mine = await tracker.get(entity_id, a)
    assert mine.origin_agent_id == "agent-a" and mine.contamination_score == 0.0
    assert (await tracker.get(entity_id, b)).contamination_score == 0.9
# ── tenant-derived keys: the same natural id coexists per tenant ────────────


async def test_behavior_profiles_for_one_entity_coexist_across_tenants(backend):
    from workers.profile360_workers import workers as profile_workers

    a, b, token = _ids()
    profiles = BehaviorProfileRepository()
    user_id = f"user-{token}"
    await profiles.upsert_snapshot(user_id, a, "w0", "w1", risk_score=0.91,
                                   anomaly_flags=["a_only_flag"], top_patterns=["a_pattern"])

    await profile_workers.IntentInferrer(profiles).handle(SimpleNamespace(
        tenant_id=b, topic=Topic.AGENT_EXECUTION_COMPLETED,
        payload={"user_id": user_id, "action": "checkout"}, envelope=None,
    ))

    mine = await profiles.find_for_entity(a, user_id)
    theirs = await profiles.find_for_entity(b, user_id)
    assert mine["tenant_id"] == a and mine["risk_score"] == 0.91
    assert mine["anomaly_flags"] == ["a_only_flag"]
    assert theirs["tenant_id"] == b and theirs["risk_score"] == 0.0
    assert theirs["anomaly_flags"] == [] and theirs["top_patterns"] == []


async def test_journey_chains_for_one_entity_coexist_across_tenants(backend):
    from workers.profile360_workers import workers as profile_workers

    a, b, token = _ids()
    chains = JourneyChainRepository()
    user_id = f"user-{token}"
    linker = profile_workers.JourneyChainLinker(chains)
    for tenant, session in ((a, "s-a"), (b, "s-b")):
        await linker.handle(SimpleNamespace(
            tenant_id=tenant, topic=Topic.AGENT_EXECUTION_COMPLETED, event_id=session,
            payload={"user_id": user_id, "session_id": session}, envelope=None,
        ))

    mine = await chains.find_for_entity(a, user_id)
    theirs = await chains.find_for_entity(b, user_id)
    assert mine["chain_id"] == f"journey_chain:{a}:{user_id}"
    assert mine["first_journey_id"] == "s-a" and mine["journey_count"] == 1
    assert theirs["first_journey_id"] == "s-b" and theirs["journey_count"] == 1


async def test_event_envelopes_with_one_id_coexist_across_tenants(backend):
    a, b, token = _ids()
    envelopes = EventEnvelopeRepository()
    event_id = f"evt-{token}"
    for tenant in (a, b):
        await envelopes.create({"id": event_id, "tenantId": tenant, "type": "x",
                                "replayable": True, "payload": {"secret": tenant}})

    for tenant in (a, b):
        rows = await envelopes.list_replayable(tenant)
        assert [r["payload"]["secret"] for r in rows] == [tenant]
        assert rows[0]["envelope_id"] == event_id
    if backend.pool is not None:
        columns = await backend.pool.fetch(
            "SELECT tenant_id FROM event_envelopes WHERE data->>'envelope_id' = $1", event_id,
        )
        assert sorted(r["tenant_id"] for r in columns) == sorted([a, b])


async def test_x402_seeds_and_resources_coexist_per_tenant(backend, monkeypatch):
    if backend.kind == "inmem":
        pytest.skip("local mode keeps commerce objects in per-tenant TenantCollections")
    import value.x402.commerce_store as commerce_store
    import value.x402.facilitators as facilitators
    from value.x402.commerce_models import ProtectedResource, ResourceClass

    monkeypatch.setattr(commerce_store, "_is_local", lambda: False)
    monkeypatch.setattr(facilitators, "_is_local_env", lambda: False)
    store = commerce_store.CommerceStore()
    monkeypatch.setattr(facilitators, "get_commerce_store", lambda: store)

    a, b, token = _ids()
    for tenant in (a, b, a):
        await facilitators.seed_facilitators_and_assets(tenant)
    registry = facilitators.FacilitatorRegistry()
    for tenant in (a, b):
        chosen = await registry.select_for(tenant, "USDC", "eip155:8453")
        assert chosen is not None and chosen.facilitator_id == "fac_circle_v2"

    resource_id = f"res-{token}"
    for tenant, price in ((a, 5.0), (b, 0.0)):
        await store.put_resource(ProtectedResource(
            resource_id=resource_id, tenant_id=tenant, name="paid", path_pattern="/paid",
            resource_class=next(iter(ResourceClass)), price_usd=price,
        ))
    assert (await store.get_resource(a, resource_id)).price_usd == 5.0
    assert (await store.get_resource(b, resource_id)).price_usd == 0.0
    assert await store.resources.delete(b, resource_id)
    assert (await store.get_resource(a, resource_id)).price_usd == 5.0
    assert await store.get_resource(b, resource_id) is None
