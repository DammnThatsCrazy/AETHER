"""Profile360Aggregator unit tests.

Verifies that the drill-down aggregator:
  * Returns the normalized envelope shape for every dimension
  * Filters cross-tenant rows
  * Degrades to empty items on repository failures (does not raise)
  * Aggregates inflow/outflow correctly
  * Aggregates platform / protocol breakdowns from analytics events
  * Resolves drill targets and respects tenant isolation
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.profile.aggregator import Profile360Aggregator


def _run(coro):
    return asyncio.run(coro)


# ── In-memory stub repositories ──────────────────────────────────────


class _Repo:
    """Minimal stand-in matching the BaseRepository surface the aggregator uses."""

    def __init__(self, rows=None):
        self._rows = list(rows or [])

    async def find_by_id(self, record_id):
        for r in self._rows:
            if r.get("id") == record_id or r.get("entity_id") == record_id \
                    or r.get("wallet_id") == record_id or r.get("transfer_id") == record_id \
                    or r.get("delegation_id") == record_id or r.get("chain_id") == record_id \
                    or r.get("intent_id") == record_id or r.get("execution_id") == record_id \
                    or r.get("agent_id") == record_id or r.get("settlement_id") == record_id:
                return r
        return None

    async def find_many(self, filters=None, limit=50, **_):
        f = filters or {}
        out = [r for r in self._rows if all(r.get(k) == v for k, v in f.items())]
        return out[:limit]

    async def list_for_owner(self, owner_id):
        return await self.find_many(filters={"owner_entity_id": owner_id}, limit=200)

    async def list_for_entity(self, entity_id, limit=100):
        return [
            r for r in self._rows
            if r.get("from_entity_id") == entity_id or r.get("to_entity_id") == entity_id
        ][:limit]

    async def list_for_agent(self, agent_id, limit=50):
        return [r for r in self._rows if r.get("agent_id") == agent_id][:limit]


class _Analytics:
    def __init__(self, events):
        self._events = list(events)

    async def query_events(self, tenant_id, filters, limit=50):
        out = []
        for e in self._events:
            if filters.get("user_id") and (e.get("properties") or {}).get("user_id") != filters["user_id"] \
                    and e.get("user_id") != filters["user_id"]:
                continue
            out.append(e)
        return out[:limit]


def _make_aggregator(*, tenant="t-a", entity="user-1"):
    agents = _Repo([
        {"id": "a-1", "agent_id": "a-1", "owner_entity_id": entity, "tenant_id": tenant, "model": "gpt"},
        {"id": "a-2", "agent_id": "a-2", "owner_entity_id": entity, "tenant_id": "t-other", "model": "gpt"},
    ])
    wallets = _Repo([
        {"id": "w-1", "wallet_id": "w-1", "owner_entity_id": entity, "tenant_id": tenant, "chain": "evm", "address": "0xabc", "linked_at": "2026-01-01T00:00:00Z"},
        {"id": "w-2", "wallet_id": "w-2", "owner_entity_id": entity, "tenant_id": tenant, "chain": "solana", "address": "sol123", "linked_at": "2026-02-01T00:00:00Z"},
        {"id": "w-x", "wallet_id": "w-x", "owner_entity_id": entity, "tenant_id": "t-other", "chain": "evm", "address": "0xleak"},
    ])
    transfers = _Repo([
        {"id": "tr-1", "transfer_id": "tr-1", "tenant_id": tenant, "from_entity_id": "other", "to_entity_id": entity, "amount": "100", "asset_id": "USD", "occurred_at": "2026-03-01T00:00:00Z"},
        {"id": "tr-2", "transfer_id": "tr-2", "tenant_id": tenant, "from_entity_id": entity, "to_entity_id": "other", "amount": "40", "asset_id": "USD", "occurred_at": "2026-03-02T00:00:00Z"},
        {"id": "tr-3", "transfer_id": "tr-3", "tenant_id": "t-other", "from_entity_id": entity, "to_entity_id": "leak", "amount": "999", "asset_id": "USD"},
    ])
    delegations = _Repo([
        {"id": "d-1", "delegation_id": "d-1", "tenant_id": tenant, "grantor_entity_id": entity, "grantee_entity_id": "a-1", "scope": {"actions": ["pay"]}, "starts_at": "2026-01-01T00:00:00Z", "ends_at": None, "revoked_at": None},
        {"id": "d-2", "delegation_id": "d-2", "tenant_id": tenant, "grantor_entity_id": "boss", "grantee_entity_id": entity, "scope": {"actions": ["read"]}, "starts_at": "2026-01-01T00:00:00Z", "revoked_at": "2026-04-01T00:00:00Z"},
    ])
    behavior = _Repo([
        {"id": entity, "entity_id": entity, "tenant_id": tenant, "automation_ratio": 0.42, "decision_latency_ms": 150, "risk_score": 0.15, "anomaly_flags": []},
    ])
    chains = _Repo([
        {"id": "c-1", "chain_id": "c-1", "entity_id": entity, "tenant_id": tenant, "first_journey_id": "j1", "last_journey_id": "j5", "journey_count": 5, "spans_started_at": "2026-01-01", "spans_last_seen_at": "2026-04-01"},
    ])
    intents = _Repo([
        {"id": "i-1", "intent_id": "i-1", "tenant_id": tenant, "agent_id": entity, "protocol": "x402", "amount": "5"},
        {"id": "i-2", "intent_id": "i-2", "tenant_id": tenant, "agent_id": entity, "protocol": "stripe", "amount": "10"},
    ])
    settlements = _Repo([
        {"id": "s-1", "settlement_id": "s-1", "tenant_id": tenant, "agent_id": entity, "amount": "9.50"},
    ])
    execs = _Repo([
        {"id": "e-1", "execution_id": "e-1", "tenant_id": tenant, "agent_id": entity, "status": "completed"},
    ])
    entities = _Repo([
        {"id": entity, "entity_id": entity, "tenant_id": tenant, "entity_type": "human", "display_name": "Alice"},
    ])
    clusters = _Repo([
        {"id": "cl-1", "cluster_id": "cl-1", "tenant_id": tenant, "entity_id": entity, "identifier_type": "device", "identifier_value": "device-A", "confidence": 0.95, "linked_at": "2026-01-01T00:00:00Z"},
    ])

    class _ClustersWrapper(_Repo):
        async def list_for_entity(self, eid):
            return [r for r in self._rows if r.get("entity_id") == eid]

    clusters = _ClustersWrapper([
        {"id": "cl-1", "cluster_id": "cl-1", "tenant_id": tenant, "entity_id": entity, "identifier_type": "device", "identifier_value": "device-A", "confidence": 0.95, "linked_at": "2026-01-01T00:00:00Z"},
    ])

    assets = _Repo([])

    analytics = _Analytics([
        {"id": "evt1", "event_type": "page_view", "user_id": entity, "created_at": "2026-04-01T00:00:00Z",
         "properties": {"user_id": entity, "platform": "ios", "device_id": "device-A", "session_id": "s1", "protocol": "web"}},
        {"id": "evt2", "event_type": "page_view", "user_id": entity, "created_at": "2026-04-02T00:00:00Z",
         "properties": {"user_id": entity, "platform": "ios", "device_id": "device-A", "session_id": "s1"}},
        {"id": "evt3", "event_type": "click", "user_id": entity, "created_at": "2026-04-03T00:00:00Z",
         "properties": {"user_id": entity, "platform": "web", "device_id": "device-B", "session_id": "s2"}},
        {"id": "evt4", "event_type": "reward_granted", "user_id": entity, "created_at": "2026-04-04T00:00:00Z",
         "properties": {"user_id": entity, "value": 5.0, "currency": "USD", "reason": "weekly"}},
    ])

    return Profile360Aggregator(
        entity_repo=entities,
        cluster_repo=clusters,
        delegation_repo=delegations,
        wallet_repo=wallets,
        asset_repo=assets,
        transfer_repo=transfers,
        agent_config_repo=agents,
        agent_exec_repo=execs,
        behavior_repo=behavior,
        journey_chain_repo=chains,
        payment_intent_repo=intents,
        settlement_repo=settlements,
        analytics_repo=analytics,
    )


# ── Tests ───────────────────────────────────────────────────────────


def test_summary_envelope_and_tenant_isolation():
    agg = _make_aggregator()
    out = _run(agg.summary("user-1", "t-a"))
    assert out["entity_id"] == "user-1"
    assert out["tenant_id"] == "t-a"
    assert out["kind"] == "summary"
    snap = out["snapshot"]
    # cross-tenant agent / wallet / transfer are filtered out
    assert snap["counts"]["agents"] == 1
    assert snap["counts"]["wallets"] == 2
    assert snap["counts"]["transfers"] == 2
    assert snap["counts"]["delegations_granted"] == 1
    assert snap["counts"]["delegations_received"] == 1
    assert snap["counts"]["active_delegations_received"] == 0  # revoked
    assert snap["financials"]["inflow_total"] == 100.0
    assert snap["financials"]["outflow_total"] == 40.0
    assert snap["financials"]["net"] == 60.0
    assert snap["behavior"]["automation_ratio"] == 0.42
    assert snap["behavior"]["computed"] is True
    assert "agents" in snap["links"]


def test_wallets_endpoint_filters_cross_tenant():
    agg = _make_aggregator()
    out = _run(agg.wallets("user-1", "t-a"))
    ids = {i["id"] for i in out["items"]}
    assert ids == {"w-1", "w-2"}
    assert out["summary"]["chains"] == ["evm", "solana"]
    assert out["pagination"]["count"] == 2


def test_relationships_includes_typed_edges():
    agg = _make_aggregator()
    out = _run(agg.relationships("user-1", "t-a"))
    types = {(r["type"], r["subType"]) for r in out["items"]}
    assert ("ownership", "owns_agent") in types
    assert ("ownership", "owns_wallet") in types
    assert ("delegation", "grants") in types
    assert ("delegation", "receives") in types
    assert ("financial_flow", "transfer_counterparty") in types
    # Counterparty surfaces the other party only
    counterparties = [r for r in out["items"] if r["subType"] == "transfer_counterparty"]
    assert counterparties[0]["to"] == "other"


def test_financials_aggregates_inflow_outflow_and_settlements():
    agg = _make_aggregator()
    out = _run(agg.financials("user-1", "t-a"))
    assert out["summary"]["inflow_total"] == 100.0
    assert out["summary"]["outflow_total"] == 40.0
    assert out["summary"]["net"] == 60.0
    assert out["summary"]["settlement_count"] == 1
    assert abs(out["summary"]["settled_total"] - 9.5) < 1e-6
    assert all(i["type"] == "transfer" for i in out["items"])


def test_platforms_and_protocols_breakdown_from_events():
    agg = _make_aggregator()
    plats = _run(agg.platforms("user-1", "t-a"))
    pids = {i["id"]: i["interactionCount"] for i in plats["items"]}
    assert pids == {"ios": 2, "web": 1}
    protos = _run(agg.protocols("user-1", "t-a"))
    pids = {i["id"] for i in protos["items"]}
    # event-stream protocol "web" plus intent-stream protocols x402+stripe
    assert {"web", "x402", "stripe"}.issubset(pids)


def test_sessions_and_devices_merge_sources():
    agg = _make_aggregator()
    sessions = _run(agg.sessions("user-1", "t-a"))
    sids = {i["id"] for i in sessions["items"]}
    assert sids == {"s1", "s2"}
    devices = _run(agg.devices("user-1", "t-a"))
    dids = {i["id"]: i["source"] for i in devices["items"]}
    # device-A is in the cluster repo → identity_cluster
    assert dids["device-A"] == "identity_cluster"
    # device-B only shows up in events → observed
    assert dids["device-B"] == "observed"


def test_journeys_and_rewards():
    agg = _make_aggregator()
    chains = _run(agg.journeys("user-1", "t-a"))
    assert len(chains["items"]) == 1
    assert chains["items"][0]["journeyCount"] == 5

    rewards = _run(agg.rewards("user-1", "t-a"))
    assert rewards["summary"]["reward_count"] == 1
    assert rewards["summary"]["total_value"] == 5.0


def test_drill_resolves_known_object_and_404s_other_tenant():
    agg = _make_aggregator()
    found = _run(agg.drill("user-1", "t-a", "wallet", "w-1"))
    assert found["found"] is True
    assert found["object"]["wallet_id"] == "w-1"

    not_found = _run(agg.drill("user-1", "t-a", "wallet", "w-x"))
    assert not_found["found"] is False

    missing = _run(agg.drill("user-1", "t-a", "wallet", "does-not-exist"))
    assert missing["found"] is False


def test_summary_masks_cross_tenant_entity_record():
    """find_by_id is not tenant-scoped; a same-id row owned by another
    tenant must not leak its display_name / metadata via /summary."""
    agg = _make_aggregator()
    # Replace the entity repo with a row that exists under a foreign tenant.
    agg._entities = _Repo([  # type: ignore[attr-defined]
        {"id": "user-1", "entity_id": "user-1", "tenant_id": "t-other",
         "entity_type": "human", "display_name": "Foreign Tenant Alice",
         "metadata": {"secret": "should-not-leak"}},
    ])
    out = _run(agg.summary("user-1", "t-a"))
    entity = out["snapshot"]["entity"]
    # Tenant guard tripped → entity reported as unknown, no foreign fields surfaced.
    assert entity["known"] is False
    assert entity["displayLabel"] == "user-1"
    assert entity["type"] == "unknown"
    assert "Foreign Tenant Alice" not in str(out)
    assert "should-not-leak" not in str(out)


def test_devices_and_sessions_read_top_level_device_id():
    """Canonical SDK events normalized by services/ingestion store device_id
    at the top level, not inside properties. The aggregator must read both."""

    class _AnalyticsTopLevel:
        async def query_events(self, tenant_id, filters, limit=50):
            # Top-level device_id / platform / session_id, NO properties duplicate.
            return [
                {"id": "ev1", "event_type": "page_view", "user_id": "user-1",
                 "device_id": "top-level-device", "platform": "ios",
                 "session_id": "s-top", "created_at": "2026-04-01T00:00:00Z",
                 "properties": {"user_id": "user-1"}},
                {"id": "ev2", "event_type": "click", "user_id": "user-1",
                 "device_id": "top-level-device", "platform": "ios",
                 "session_id": "s-top", "created_at": "2026-04-02T00:00:00Z",
                 "properties": {"user_id": "user-1"}},
            ]

    agg = _make_aggregator()
    agg._analytics = _AnalyticsTopLevel()  # type: ignore[attr-defined]
    # No identity-cluster entry for this device, so it must arrive via the
    # observed path only.
    agg._clusters = _Repo([])  # type: ignore[attr-defined]

    devices = _run(agg.devices("user-1", "t-a"))
    ids = {i["id"]: i["source"] for i in devices["items"]}
    assert "top-level-device" in ids
    assert ids["top-level-device"] == "observed"

    sessions = _run(agg.sessions("user-1", "t-a"))
    rollup = next(i for i in sessions["items"] if i["id"] == "s-top")
    assert "top-level-device" in rollup["devices"]
    assert "ios" in rollup["platforms"]


def test_protocols_total_interactions_includes_intent_merge():
    """summary.total_interactions must reflect both event-stream and
    payment-intent protocol items, including the case where the tenant has
    no protocol events at all and only intents contribute."""

    class _NoEvents:
        async def query_events(self, tenant_id, filters, limit=50):
            return []

    intents_only = _Repo([
        {"id": "i-only-1", "intent_id": "i-only-1", "tenant_id": "t-a",
         "agent_id": "user-1", "protocol": "x402"},
        {"id": "i-only-2", "intent_id": "i-only-2", "tenant_id": "t-a",
         "agent_id": "user-1", "protocol": "x402"},
        {"id": "i-only-3", "intent_id": "i-only-3", "tenant_id": "t-a",
         "agent_id": "user-1", "protocol": "stripe"},
    ])
    agg = _make_aggregator()
    agg._analytics = _NoEvents()  # type: ignore[attr-defined]
    agg._intents = intents_only   # type: ignore[attr-defined]

    out = _run(agg.protocols("user-1", "t-a"))
    items_total = sum(i["interactionCount"] for i in out["items"])
    assert items_total == 3
    assert out["summary"]["total_interactions"] == items_total
    assert out["summary"]["protocol_count"] == len(out["items"])
    # Items list and rollup must agree, otherwise the frontend drilldown
    # contradicts the dashboard summary.
    assert out["summary"]["total_interactions"] > 0


def test_protocols_total_interactions_merges_event_and_intent_counts():
    """When both events and intents contribute to the same protocol the
    total must equal the sum of merged interactionCount, not the
    event-only baseline."""
    agg = _make_aggregator()
    # Event stream provides 1 'web' protocol interaction; intents provide
    # x402 + stripe. The merge increments / adds entries — totals must reflect that.
    out = _run(agg.protocols("user-1", "t-a"))
    items_total = sum(i["interactionCount"] for i in out["items"])
    assert out["summary"]["total_interactions"] == items_total


def test_summary_excludes_expired_and_future_delegations_from_active_counts():
    """active_delegations_* must honor starts_at / ends_at, matching
    DelegationRepository.active_for."""
    past = "2020-01-01T00:00:00Z"
    future = "2099-01-01T00:00:00Z"
    delegations = _Repo([
        # 1: not yet started — future starts_at
        {"id": "d-future", "delegation_id": "d-future", "tenant_id": "t-a",
         "grantor_entity_id": "user-1", "grantee_entity_id": "a-1",
         "scope": {"actions": ["pay"]}, "starts_at": future, "ends_at": None,
         "revoked_at": None},
        # 2: expired — ends_at in the past
        {"id": "d-expired", "delegation_id": "d-expired", "tenant_id": "t-a",
         "grantor_entity_id": "user-1", "grantee_entity_id": "a-2",
         "scope": {"actions": ["pay"]}, "starts_at": past, "ends_at": past,
         "revoked_at": None},
        # 3: genuinely active
        {"id": "d-active", "delegation_id": "d-active", "tenant_id": "t-a",
         "grantor_entity_id": "user-1", "grantee_entity_id": "a-3",
         "scope": {"actions": ["pay"]}, "starts_at": past, "ends_at": future,
         "revoked_at": None},
        # 4: received and active
        {"id": "d-in", "delegation_id": "d-in", "tenant_id": "t-a",
         "grantor_entity_id": "boss", "grantee_entity_id": "user-1",
         "scope": {"actions": ["read"]}, "starts_at": past, "ends_at": future,
         "revoked_at": None},
        # 5: received but expired
        {"id": "d-in-exp", "delegation_id": "d-in-exp", "tenant_id": "t-a",
         "grantor_entity_id": "boss", "grantee_entity_id": "user-1",
         "scope": {"actions": ["read"]}, "starts_at": past, "ends_at": past,
         "revoked_at": None},
    ])
    agg = _make_aggregator()
    agg._delegations = delegations  # type: ignore[attr-defined]

    out = _run(agg.summary("user-1", "t-a"))
    counts = out["snapshot"]["counts"]
    # Total still includes everything (all non-revoked rows in the repo)
    assert counts["delegations_granted"] == 3
    assert counts["delegations_received"] == 2
    # But only the time-window-valid ones are reported as active.
    assert counts["active_delegations_granted"] == 1
    assert counts["active_delegations_received"] == 1


def test_drill_rejects_unrelated_same_tenant_object():
    """The drill endpoint lives under /v1/profile/{entity}/drill/..., so
    a wallet that belongs to another entity in the same tenant must NOT
    be returned. Otherwise tenant-mates can enumerate each other's
    wallets / delegations / transfers by id."""
    agg = _make_aggregator()
    # Inject a wallet owned by Bob (same tenant) and try to drill from Alice.
    agg._wallets = _Repo([  # type: ignore[attr-defined]
        {"id": "bob-wallet", "wallet_id": "bob-wallet",
         "owner_entity_id": "bob", "tenant_id": "t-a",
         "chain": "evm", "address": "0xbob"},
        {"id": "alice-wallet", "wallet_id": "alice-wallet",
         "owner_entity_id": "user-1", "tenant_id": "t-a",
         "chain": "evm", "address": "0xalice"},
    ])
    bobs = _run(agg.drill("user-1", "t-a", "wallet", "bob-wallet"))
    assert bobs["found"] is False
    assert bobs["object"] is None
    alices = _run(agg.drill("user-1", "t-a", "wallet", "alice-wallet"))
    assert alices["found"] is True


def test_drill_rejects_unrelated_delegation_transfer_execution():
    """Same association guard for delegations, transfers, executions, and
    journey chains — drill must require profile membership, not just
    tenant match."""
    agg = _make_aggregator()
    agg._delegations = _Repo([  # type: ignore[attr-defined]
        {"id": "d-other", "delegation_id": "d-other", "tenant_id": "t-a",
         "grantor_entity_id": "bob", "grantee_entity_id": "carol",
         "scope": {}, "revoked_at": None},
    ])
    agg._transfers = _Repo([  # type: ignore[attr-defined]
        {"id": "tr-other", "transfer_id": "tr-other", "tenant_id": "t-a",
         "from_entity_id": "bob", "to_entity_id": "carol",
         "amount": "5", "asset_id": "USD"},
    ])
    agg._agent_execs = _Repo([  # type: ignore[attr-defined]
        {"id": "ex-other", "execution_id": "ex-other", "tenant_id": "t-a",
         "agent_id": "bob-agent", "status": "completed"},
    ])
    agg._journeys = _Repo([  # type: ignore[attr-defined]
        {"id": "c-other", "chain_id": "c-other", "tenant_id": "t-a",
         "entity_id": "bob"},
    ])

    for ot, oid in [
        ("delegation", "d-other"),
        ("transfer", "tr-other"),
        ("agent_execution", "ex-other"),
        ("journey", "c-other"),
    ]:
        out = _run(agg.drill("user-1", "t-a", ot, oid))
        assert out["found"] is False, f"drill leaked {ot}/{oid}"


def test_relationships_active_flag_honors_delegation_time_window():
    """Each delegation edge's `active` flag must match the canonical
    DelegationRepository.active_for predicate (not revoked AND in
    starts_at..ends_at window) so the relationship list agrees with
    the /summary counts."""
    past = "2020-01-01T00:00:00Z"
    future = "2099-01-01T00:00:00Z"
    delegations = _Repo([
        # granted but not yet started
        {"id": "d-future", "delegation_id": "d-future", "tenant_id": "t-a",
         "grantor_entity_id": "user-1", "grantee_entity_id": "x",
         "scope": {}, "starts_at": future, "ends_at": None, "revoked_at": None},
        # granted and expired
        {"id": "d-expired", "delegation_id": "d-expired", "tenant_id": "t-a",
         "grantor_entity_id": "user-1", "grantee_entity_id": "y",
         "scope": {}, "starts_at": past, "ends_at": past, "revoked_at": None},
        # granted and currently active
        {"id": "d-active-out", "delegation_id": "d-active-out", "tenant_id": "t-a",
         "grantor_entity_id": "user-1", "grantee_entity_id": "z",
         "scope": {}, "starts_at": past, "ends_at": future, "revoked_at": None},
        # received and active
        {"id": "d-active-in", "delegation_id": "d-active-in", "tenant_id": "t-a",
         "grantor_entity_id": "boss", "grantee_entity_id": "user-1",
         "scope": {}, "starts_at": past, "ends_at": future, "revoked_at": None},
        # received and expired
        {"id": "d-expired-in", "delegation_id": "d-expired-in", "tenant_id": "t-a",
         "grantor_entity_id": "boss", "grantee_entity_id": "user-1",
         "scope": {}, "starts_at": past, "ends_at": past, "revoked_at": None},
    ])
    agg = _make_aggregator()
    agg._delegations = delegations  # type: ignore[attr-defined]

    out = _run(agg.relationships("user-1", "t-a"))
    by_id = {r["id"].split(":", 1)[1]: r for r in out["items"] if r["type"] == "delegation"}
    assert by_id["d-active-out"]["active"] is True
    assert by_id["d-active-in"]["active"] is True
    assert by_id["d-future"]["active"] is False
    assert by_id["d-expired"]["active"] is False
    assert by_id["d-expired-in"]["active"] is False


def test_analytics_query_cache_isolates_by_limit():
    """AnalyticsRepository.query_events must not collide cache entries when
    the same {user_id} filter is requested with different limits. A
    sessions?limit=1 call previously poisoned platforms/protocols/devices
    cache entries, causing rollups to undercount."""
    from repositories.repos import AnalyticsRepository, reset_in_memory_stores

    class _InMemCache:
        def __init__(self):
            self._d: dict = {}
        async def get_json(self, k):
            return self._d.get(k)
        async def set_json(self, k, v, ttl=None):
            self._d[k] = v

    reset_in_memory_stores()
    cache = _InMemCache()
    repo = AnalyticsRepository(cache)
    for i in range(5):
        _run(repo.record_event(f"evt-{i}", {
            "tenant_id": "t", "user_id": "u", "event_type": "x", "id": f"evt-{i}",
        }))

    small = _run(repo.query_events("t", {"user_id": "u"}, limit=1))
    assert len(small) == 1
    # Same filter, bigger limit — bug would have returned the cached len==1.
    big = _run(repo.query_events("t", {"user_id": "u"}, limit=5))
    assert len(big) == 5


def test_repositories_share_in_memory_store_across_instances():
    """Route-level repo singletons and aggregator-owned repos must observe
    the same in-memory state, otherwise data written through /v1/flows is
    invisible to /v1/profile/{id}/wallets in AETHER_ENV=local."""
    from repositories.repos import WalletRepository, reset_in_memory_stores

    reset_in_memory_stores()
    route_instance = WalletRepository()
    _run(route_instance.link_wallet(
        wallet_id="shared-wallet",
        owner_entity_id="alice",
        tenant_id="t",
        chain="evm",
        address="0xshared",
    ))
    aggregator_instance = WalletRepository()
    rows = _run(aggregator_instance.find_many(
        filters={"owner_entity_id": "alice"}, limit=10,
    ))
    assert len(rows) == 1
    assert rows[0]["wallet_id"] == "shared-wallet"


def test_aggregator_with_default_repos_sees_writes_via_route_repos():
    """End-to-end: a wallet linked through WalletRepository (as /v1/flows
    does) must be visible to a Profile360Aggregator that constructed its
    own repos (the default path used when no override is supplied)."""
    from repositories.repos import (
        WalletRepository, TransferRepository, reset_in_memory_stores,
    )

    reset_in_memory_stores()
    _run(WalletRepository().link_wallet(
        wallet_id="w-shared",
        owner_entity_id="user-1",
        tenant_id="t-a",
        chain="evm",
        address="0xshared",
    ))
    _run(TransferRepository().record_transfer(
        transfer_id="tr-shared", tenant_id="t-a",
        from_entity_id="other", to_entity_id="user-1",
        asset_id="USD", amount="50",
    ))

    agg = Profile360Aggregator()
    wallets = _run(agg.wallets("user-1", "t-a"))
    fins = _run(agg.financials("user-1", "t-a"))
    assert any(w["id"] == "w-shared" for w in wallets["items"])
    assert fins["summary"]["inflow_total"] == 50.0


def test_wallets_does_not_truncate_when_other_tenant_has_many_rows():
    """Old code post-filtered by tenant after applying `limit` to find_many,
    so when a foreign tenant had many rows under the same owner_entity_id
    the page filled up with foreign rows that all got dropped, returning
    an empty list to the caller even though the requested tenant had
    matching rows. The fix: tenant_id is part of the find_many filter."""
    foreign = [
        {"id": f"w-foreign-{i}", "wallet_id": f"w-foreign-{i}",
         "owner_entity_id": "user-1", "tenant_id": "t-other",
         "chain": "evm", "address": f"0xforeign{i}"}
        for i in range(50)
    ]
    own = [
        {"id": f"w-own-{i}", "wallet_id": f"w-own-{i}",
         "owner_entity_id": "user-1", "tenant_id": "t-a",
         "chain": "evm", "address": f"0xown{i}"}
        for i in range(3)
    ]
    agg = _make_aggregator()
    agg._wallets = _Repo(foreign + own)  # type: ignore[attr-defined]
    out = _run(agg.wallets("user-1", "t-a", limit=10))
    ids = {i["id"] for i in out["items"]}
    assert ids == {"w-own-0", "w-own-1", "w-own-2"}
    assert out["summary"]["wallet_count"] == 3


def test_summary_does_not_lose_active_delegations_to_other_tenant_truncation():
    """Same truncation bug applied to /summary's active_delegations_*
    counts: a tenant with thousands of foreign-tenant delegations under the
    same grantee_entity_id would crowd out the page and report 0 active
    delegations for the requested tenant."""
    foreign = [
        {"id": f"d-foreign-{i}", "delegation_id": f"d-foreign-{i}",
         "tenant_id": "t-other", "grantor_entity_id": "boss",
         "grantee_entity_id": "user-1",
         "scope": {}, "starts_at": "2020-01-01T00:00:00Z",
         "ends_at": "2099-01-01T00:00:00Z", "revoked_at": None}
        for i in range(300)
    ]
    own = [
        {"id": "d-own", "delegation_id": "d-own",
         "tenant_id": "t-a", "grantor_entity_id": "boss",
         "grantee_entity_id": "user-1",
         "scope": {}, "starts_at": "2020-01-01T00:00:00Z",
         "ends_at": "2099-01-01T00:00:00Z", "revoked_at": None},
    ]
    agg = _make_aggregator()
    agg._delegations = _Repo(foreign + own)  # type: ignore[attr-defined]
    out = _run(agg.summary("user-1", "t-a"))
    counts = out["snapshot"]["counts"]
    assert counts["delegations_received"] == 1
    assert counts["active_delegations_received"] == 1


def test_financials_transfers_not_truncated_by_other_tenant_rows():
    """The transfer list_for_entity helper made one un-tenant-scoped
    find_many call per direction. With many same-id foreign-tenant
    transfers, the requested tenant's rows would be dropped after limit
    truncation. Aggregator now uses an explicit tenant-scoped query."""
    foreign = [
        {"id": f"tr-foreign-{i}", "transfer_id": f"tr-foreign-{i}",
         "tenant_id": "t-other", "from_entity_id": "x",
         "to_entity_id": "user-1", "asset_id": "USD",
         "amount": "1", "occurred_at": "2026-01-01T00:00:00Z"}
        for i in range(60)
    ]
    own = [
        {"id": "tr-own-in", "transfer_id": "tr-own-in",
         "tenant_id": "t-a", "from_entity_id": "x",
         "to_entity_id": "user-1", "asset_id": "USD",
         "amount": "100", "occurred_at": "2026-04-01T00:00:00Z"},
        {"id": "tr-own-out", "transfer_id": "tr-own-out",
         "tenant_id": "t-a", "from_entity_id": "user-1",
         "to_entity_id": "y", "asset_id": "USD",
         "amount": "40", "occurred_at": "2026-04-02T00:00:00Z"},
    ]
    agg = _make_aggregator()
    agg._transfers = _Repo(foreign + own)  # type: ignore[attr-defined]
    out = _run(agg.financials("user-1", "t-a", limit=10))
    assert out["summary"]["inflow_total"] == 100.0
    assert out["summary"]["outflow_total"] == 40.0
    ids = {i["id"] for i in out["items"]}
    assert ids == {"tr-own-in", "tr-own-out"}


def test_aggregator_preserves_legacy_unscoped_rows():
    """Pre-multi-tenant production rows (tenant_id NULL or '') were
    intentionally admitted by _tenant_filter. The earlier fix that pushed
    tenant_id into find_many would otherwise have made them disappear
    from /v1/profile/{id}/{wallets,transfers,delegations,…}. The
    aggregator now fans out a primary tenant-scoped query AND a legacy
    `tenant_id=None` query, then merges, so legacy data stays visible
    until ops backfill the column."""
    legacy_wallet = {
        "id": "w-legacy", "wallet_id": "w-legacy",
        "owner_entity_id": "user-1",  # tenant_id intentionally omitted
        "chain": "evm", "address": "0xlegacy",
        "linked_at": "2024-01-01T00:00:00Z",
    }
    own_wallet = {
        "id": "w-own", "wallet_id": "w-own",
        "owner_entity_id": "user-1", "tenant_id": "t-a",
        "chain": "evm", "address": "0xown",
        "linked_at": "2026-01-01T00:00:00Z",
    }
    foreign_wallet = {
        "id": "w-foreign", "wallet_id": "w-foreign",
        "owner_entity_id": "user-1", "tenant_id": "t-other",
        "chain": "evm", "address": "0xforeign",
    }
    agg = _make_aggregator()
    agg._wallets = _Repo([foreign_wallet, legacy_wallet, own_wallet])  # type: ignore[attr-defined]
    out = _run(agg.wallets("user-1", "t-a"))
    ids = {i["id"] for i in out["items"]}
    assert "w-own" in ids
    assert "w-legacy" in ids   # legacy row still visible
    assert "w-foreign" not in ids


def test_aggregator_legacy_rows_survive_truncation_under_load():
    """Even when the current tenant fills the page, a small number of
    legacy unscoped rows should still surface (they come from a separate
    query whose own slice is up to `limit`, then we merge and truncate
    sorted by recency). Conversely, foreign-tenant rows never appear."""
    own = [
        {"id": f"w-own-{i}", "wallet_id": f"w-own-{i}",
         "owner_entity_id": "user-1", "tenant_id": "t-a",
         "chain": "evm", "address": f"0xown{i}",
         "linked_at": f"2026-0{(i % 9) + 1}-01T00:00:00Z",
         "created_at": f"2026-0{(i % 9) + 1}-01T00:00:00Z"}
        for i in range(20)
    ]
    legacy = [
        {"id": "w-legacy", "wallet_id": "w-legacy",
         "owner_entity_id": "user-1",  # no tenant
         "chain": "solana", "address": "legacy",
         "linked_at": "2099-01-01T00:00:00Z",
         "created_at": "2099-01-01T00:00:00Z"},  # newest, must appear
    ]
    foreign = [
        {"id": f"w-foreign-{i}", "wallet_id": f"w-foreign-{i}",
         "owner_entity_id": "user-1", "tenant_id": "t-other",
         "chain": "evm", "address": f"0xforeign{i}"}
        for i in range(50)
    ]
    agg = _make_aggregator()
    agg._wallets = _Repo(foreign + own + legacy)  # type: ignore[attr-defined]
    out = _run(agg.wallets("user-1", "t-a", limit=10))
    ids = {i["id"] for i in out["items"]}
    assert "w-legacy" in ids
    assert not any(i.startswith("w-foreign") for i in ids)


def test_base_repository_supports_legacy_tenant_filter():
    """BaseRepository.find_many must treat tenant_id=None as a request to
    match legacy unscoped rows. In-memory dict path matches missing keys
    naturally; the SQL path special-cases the filter to emit
    (tenant_id IS NULL OR tenant_id = '')."""
    from repositories.repos import BaseRepository, reset_in_memory_stores

    class _T(BaseRepository):
        def __init__(self):
            super().__init__("test_legacy_filter")

    reset_in_memory_stores()
    repo = _T()
    _run(repo.insert("scoped", {"tenant_id": "t-a", "owner_entity_id": "u"}))
    _run(repo.insert("legacy", {"owner_entity_id": "u"}))  # no tenant_id
    _run(repo.insert("foreign", {"tenant_id": "t-other", "owner_entity_id": "u"}))

    scoped = _run(repo.find_many(filters={"tenant_id": "t-a", "owner_entity_id": "u"}))
    legacy = _run(repo.find_many(filters={"tenant_id": None, "owner_entity_id": "u"}))
    assert {r.get("id") for r in scoped} == {"scoped"}
    assert {r.get("id") for r in legacy} == {"legacy"}


def test_aggregator_degrades_on_repo_failure_without_raising():
    """A failing dependency must produce an empty dimension, not a 500."""

    class _Boom:
        async def find_many(self, *a, **kw):
            raise RuntimeError("simulated outage")

        async def list_for_entity(self, *a, **kw):
            raise RuntimeError("simulated outage")

        async def list_for_owner(self, *a, **kw):
            raise RuntimeError("simulated outage")

        async def find_by_id(self, *a, **kw):
            raise RuntimeError("simulated outage")

    agg = _make_aggregator()
    # Swap the wallet repo for one that always fails.
    agg._wallets = _Boom()  # type: ignore[attr-defined]
    out = _run(agg.wallets("user-1", "t-a"))
    assert out["items"] == []
    assert out["pagination"]["count"] == 0
