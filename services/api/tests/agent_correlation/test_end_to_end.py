"""End to end: a Grok bot, Shopify, Stripe, Ramp, Cloudflare, and OpenAI in one graph.

The scenario the agent economy produces today: an agent registers a task
through Aether's MCP endpoint, changes Shopify inventory through Shopify's AI
connector (which acts through a staff account), charges a customer through
Stripe, spends on a Ramp card under a limit, and calls a model through a
Cloudflare AI Gateway. Each vendor's record arrives separately. Aether links
them, grades every link, and states what it could not see.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from actions.agent_correlation.mappers import MappingError
from actions.agent_correlation.mcp_server import handle_jsonrpc
from tests.agent_correlation.conftest import connect_verified_account

T0 = datetime.now(timezone.utc).replace(microsecond=0)
STORE = "acme.myshopify.com"


def iso(delta_s: int = 0) -> str:
    return (T0 + timedelta(seconds=delta_s)).isoformat()


async def _mcp(service, tenant_id, name, arguments):
    reply = await handle_jsonrpc(service, tenant_id, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments},
    })
    assert "result" in reply, reply
    assert reply["result"]["isError"] is False, reply
    return reply["result"]["structuredContent"]


@pytest.mark.asyncio
async def test_grok_bot_task_links_across_every_vendor(service, tenant_id, projector) -> None:
    # The merchant's Shopify store is a verified provider-runtime connection.
    account_ref = await connect_verified_account(tenant_id, account_key=STORE)
    await service.bindings.put(tenant_id, "ramp", "biz_1", "live")

    # 1. The Grok bot registers its task through Aether's MCP endpoint.
    task = await _mcp(service, tenant_id, "aether_register_task", {
        "agent_platform": "xai_grok", "agent_ref": "bot_ops_1", "principal_ref": "alice@acme",
        "description": "Restock and charge the wholesale order",
    })
    token, task_ref = task["correlation_token"], task["task_ref"]
    assert task["stamp_token_in"]["stripe"].startswith("metadata.")

    # 2. It reports the Shopify connector call it made, whose output names the inventory level.
    await _mcp(service, tenant_id, "aether_report_tool_call", {
        "correlation_token": token, "agent_platform": "xai_grok", "call_id": "call_1",
        "tool_name": "set-inventory", "input": {"available": 40},
        "output": {"inventoryLevel": {"id": "gid://shopify/InventoryLevel/991?inventory_item_id=55"}},
        "occurred_at": iso(5),
    })

    # 3. Shopify's webhook arrives on the verified connection: the change names a staff account.
    shop = await service.ingest_record(tenant_id, "shopify", "inventory_level", {
        "inventory_item_id": 55, "location_id": 7, "available": 40, "updated_at": iso(8),
        "admin_graphql_api_id": "gid://shopify/InventoryLevel/991?inventory_item_id=55",
        "user_id": 4242,
    }, account_bindings={"shopify": {"source_account_key": STORE}})
    assert account_ref
    shop_links = shop[0]["links"]
    tool_link = next(l for l in shop_links if l["other_observation_id"] == "aether_mcp:tool_call:xai_grok:call_1")
    assert tool_link["status"] == "linked"
    assert tool_link["key_kind"] == "shared_object_ref"
    assert tool_link["evidence_class"] == "DETERMINISTIC_BINDING"

    # 4. Stripe settles hours later with the token in the PaymentIntent metadata.
    stripe = await service.ingest_record(tenant_id, "stripe", "event", {
        "id": "evt_1", "type": "payment_intent.succeeded", "created": int((T0 + timedelta(hours=3)).timestamp()),
        "livemode": True, "account": "acct_1",
        "data": {"object": {"object": "payment_intent", "id": "pi_3AbcDefGhi", "metadata": {"aether_correlation": token}}},
    })
    pay_link = next(l for l in stripe[0]["links"] if l["other_observation_id"] == f"aether_mcp:task:{task_ref}")
    # The token is MAC-verified for this tenant, so no account verification is needed.
    assert pay_link["status"] == "linked" and pay_link["key_kind"] == "aether_correlation_token"

    # 5. Ramp: the limit the agent's card runs under, then the spend on that card.
    await service.ingest_record(tenant_id, "ramp", "limit", {
        "id": "lim_1", "card_id": "card_9", "display_name": f"ops bot budget {token}", "created_at": iso(-60),
    })
    ramp = await service.ingest_record(tenant_id, "ramp", "transaction", {
        "id": "txn_1", "user_transaction_time": iso(30), "card_id": "card_9", "memo": "freight",
    })
    limit_link = next(l for l in ramp[0]["links"] if l["other_observation_id"].startswith("ramp:limit:"))
    # Same card, no token on the transaction: the spend-to-authority link is provider-asserted, not proof.
    assert limit_link["status"] == "candidate" and limit_link["evidence_class"] == "PROVIDER_ASSERTED"

    # 6. Cloudflare AI Gateway saw the model call, with the token in its metadata.
    cf = await service.ingest_record(tenant_id, "cloudflare", "ai_gateway_log", {
        "id": "log_1", "created_at": iso(2), "provider": "xai", "model": "grok", "metadata": {"aether": token},
    })
    assert any(l["status"] == "linked" and l["key_kind"] == "aether_correlation_token" for l in cf[0]["links"])

    # 7. The chain: everything proven hangs off the task, gaps are explicit.
    chain = await service.chain_for_task(tenant_id, task_ref)
    roles = {o["source_role"] for o in chain["observations"]}
    assert {"agent_runtime", "tool_bridge", "system_of_record", "network_observer", "authority_issuer"} <= roles
    providers = {o["provider"] for o in chain["observations"]}
    assert {"aether_mcp", "shopify", "stripe", "cloudflare", "ramp"} <= providers
    assert all(l["evidence_class"] in {"DETERMINISTIC_BINDING", "CRYPTOGRAPHICALLY_ATTESTED"} for l in chain["proven_links"])
    assert chain["task"]["declared_principal_ref"] == "alice@acme"
    assert chain["gaps"] == []
    times = [o["occurred_at"] for o in chain["observations"]]
    assert times == sorted(times)

    # Only proven links reached the graph, each as one evidence-classed edge.
    assert projector.calls
    for _, _, verdict, verdict_id, mutations in projector.calls:
        assert verdict.status == "linked"
        edge = mutations[-1]
        assert edge.edge_type == "CORRELATED_ACROSS_SOURCES"
        assert edge.properties["evidence_class"] == verdict.evidence_class
        assert edge.properties["source_event_id"] == verdict_id


@pytest.mark.asyncio
async def test_staff_account_change_without_agent_evidence_is_not_attributed_to_an_agent(service, tenant_id) -> None:
    await service.bindings.put(tenant_id, "shopify", STORE, "live")
    task = await service.register_task(tenant_id, agent_platform="xai_grok")
    shop = await service.ingest_record(tenant_id, "shopify", "inventory_level", {
        "inventory_item_id": 1, "location_id": 2, "updated_at": iso(20), "user_id": 7,
    })
    # Near in time to the task, but nothing binds them: a candidate at most.
    assert all(l["status"] != "linked" for l in shop[0]["links"])
    chain = await service.chain_for_observation(tenant_id, shop[0]["observation_id"])
    assert chain["proven_links"] == []
    assert any("agent runtime" in g for g in chain["gaps"])
    assert task["task_ref"]


@pytest.mark.asyncio
async def test_openai_export_links_trace_tools_and_stripe(service, tenant_id) -> None:
    await service.bindings.put(tenant_id, "stripe", "acct_1", "live")
    task = await service.register_task(tenant_id, agent_platform="openai")
    token = task["correlation_token"]
    out = await service.ingest_record(tenant_id, "openai", "export", {"data": [
        {"object": "trace", "id": "trace_1", "workflow_name": "refunds", "metadata": {"aether": token}},
        {"object": "trace.span", "id": "span_1", "trace_id": "trace_1", "started_at": iso(1), "ended_at": iso(2),
         "span_data": {"type": "function", "name": "create_refund", "input": "{}", "output": '{"id": "re_1Abcdefghij"}'}},
        {"object": "trace.span", "id": "span_2", "trace_id": "trace_1", "started_at": iso(1),
         "span_data": {"type": "generation"}},
    ]})
    roles = {o["source_role"] for o in out}
    assert roles == {"agent_runtime", "tool_bridge"}
    refund = await service.ingest_record(tenant_id, "stripe", "event", {
        "id": "evt_9", "type": "refund.created", "created": int((T0 + timedelta(seconds=4)).timestamp()),
        "livemode": True, "data": {"object": {"object": "refund", "id": "re_1Abcdefghij", "charge": "ch_1Abcdefghij"}},
    })
    span_link = next(l for l in refund[0]["links"] if l["other_observation_id"] == "openai:span:span_1")
    # Stripe has no verified provider-runtime connection here, so the refund's
    # account rests on the tenant's declaration: an exact ID match, graded as such.
    assert span_link["status"] == "candidate"
    assert span_link["key_kind"] == "declared_object_ref"
    assert span_link["evidence_class"] == "TENANT_DECLARED"
    # The trace's token still binds the tool call to the task exactly.
    trace_links = (await service.chain_for_task(tenant_id, task["task_ref"]))["proven_links"]
    assert any(l["key_kind"] == "aether_correlation_token" for l in trace_links)


@pytest.mark.asyncio
async def test_signed_agent_request_attested_by_edge(service, tenant_id) -> None:
    task = await service.register_task(tenant_id, agent_platform="custom")
    await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", {
        "agent_platform": "custom", "call_id": "c9", "correlation_token": task["correlation_token"],
        "occurred_at": iso(0), "signature_nonce": "n-123",
    })
    edge = await service.ingest_record(tenant_id, "cloudflare", "http_request", {
        "RayID": "8f00aa", "EdgeStartTimestamp": int((T0 + timedelta(minutes=40)).timestamp() * 1e9),
        "signature_nonce": "n-123", "signature_verified": True,
    })
    link = next(l for l in edge[0]["links"] if l["other_observation_id"] == "aether_mcp:tool_call:custom:c9")
    assert link["status"] == "linked" and link["evidence_class"] == "CRYPTOGRAPHICALLY_ATTESTED"


@pytest.mark.asyncio
async def test_repeated_delivery_is_idempotent(service, tenant_id) -> None:
    rec = {"id": "evt_dup", "type": "charge.succeeded", "created": int(T0.timestamp()), "livemode": False,
           "account": "acct_x", "data": {"object": {"object": "charge", "id": "ch_dupAbcdefgh"}}}
    first = await service.ingest_record(tenant_id, "stripe", "event", rec)
    again = await service.ingest_record(tenant_id, "stripe", "event", rec)
    assert first[0]["duplicate"] is False and again[0]["duplicate"] is True and again[0]["links"] == []


@pytest.mark.asyncio
async def test_tenants_never_link(service, tenant_id) -> None:
    task = await service.register_task(tenant_id, agent_platform="xai_grok")
    other_tenant = tenant_id + "_other"
    out = await service.ingest_record(other_tenant, "stripe", "event", {
        "id": "evt_x", "type": "payment_intent.succeeded", "created": int(T0.timestamp()), "livemode": True,
        "account": "acct_1",
        "data": {"object": {"object": "payment_intent", "id": "pi_xAbcdefghij", "metadata": {"a": task["correlation_token"]}}},
    })
    assert out[0]["links"] == []
    assert await service.chain_for_task(other_tenant, task["task_ref"]) is None


@pytest.mark.asyncio
async def test_declared_shopify_account_links_only_as_tenant_declared(service, tenant_id) -> None:
    await service.declare_binding(tenant_id, "shopify", STORE, "live")
    task = await service.register_task(tenant_id, agent_platform="xai_grok")
    await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", {
        "agent_platform": "xai_grok", "call_id": "c1", "correlation_token": task["correlation_token"],
        "occurred_at": iso(0), "output": "gid://shopify/Product/77",
    })
    shop = await service.ingest_record(tenant_id, "shopify", "product", {"id": 77, "updated_at": iso(3)})
    link = next(l for l in shop[0]["links"] if l["other_observation_id"] == "aether_mcp:tool_call:xai_grok:c1")
    assert link["status"] == "candidate" and link["evidence_class"] == "TENANT_DECLARED"
    status = await service.binding_status(tenant_id)
    assert status == [{"provider_family": "shopify", "source_account_realm": "live", "verified": False,
                       "binding_source": "tenant_declared"}]


@pytest.mark.asyncio
async def test_unverified_account_cannot_be_named_when_verified_ones_exist(service, tenant_id) -> None:
    await connect_verified_account(tenant_id, account_key=STORE)
    with pytest.raises(MappingError, match="not a verified connection"):
        await service.ingest_record(tenant_id, "shopify", "product", {"id": 1, "updated_at": iso(0)},
                                    account_bindings={"shopify": {"source_account_key": "evil.myshopify.com"}})
    with pytest.raises(MappingError, match="verified accounts"):
        await service.declare_binding(tenant_id, "shopify", "evil.myshopify.com", "live")
    with pytest.raises(MappingError, match="different realm"):
        await service.ingest_record(tenant_id, "shopify", "product", {"id": 1, "updated_at": iso(0)},
                                    account_bindings={"shopify": {"source_account_key": STORE,
                                                                  "source_account_realm": "test"}})
    status = await service.binding_status(tenant_id)
    assert status[0]["verified"] is True and status[0]["binding_source"] == "verified_connection"


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "verified"), [("revoked", True), ("failed", True), ("connected", False)])
async def test_revoked_failed_or_unverified_connections_do_not_verify(service, tenant_id, state, verified) -> None:
    await connect_verified_account(tenant_id, account_key=STORE, state=state, verified=verified)
    assert await service.resolver.verified_accounts(tenant_id) == {}


@pytest.mark.asyncio
async def test_verified_accounts_are_tenant_scoped(service, tenant_id) -> None:
    await connect_verified_account(tenant_id + "_other", account_key=STORE)
    assert await service.resolver.verified_accounts(tenant_id) == {}


@pytest.mark.asyncio
async def test_live_and_test_realms_of_one_account_both_stay_verified(service, tenant_id) -> None:
    await connect_verified_account(tenant_id, family="stripe", account_key="acct_1", realm="live")
    await connect_verified_account(tenant_id, family="stripe", account_key="acct_1", realm="test")
    verified = await service.resolver.verified_accounts(tenant_id)
    assert {("stripe", "live", "acct_1"), ("stripe", "test", "acct_1")} <= set(verified)
    for livemode, event_id in ((True, "evt_live"), (False, "evt_test")):
        out = await service.ingest_record(tenant_id, "stripe", "event", {
            "id": event_id, "type": "charge.succeeded", "created": int(T0.timestamp()),
            "livemode": livemode, "account": "acct_1",
            "data": {"object": {"object": "charge", "id": f"ch_{event_id}Abcdefgh"}},
        })
        assert out and out[0]["duplicate"] is False
    # Declaring the account in either realm matches its verified connection.
    for realm in ("live", "test"):
        assert (await service.declare_binding(tenant_id, "stripe", "acct_1", realm))["verified"] is True


class _FlakyProjector:
    def __init__(self) -> None:
        self.down = True
        self.calls = 0

    async def project(self, left, right, verdict, verdict_id):
        self.calls += 1
        if self.down:
            return {"graph_projection_status": "failed", "graph_mutations_persisted": 0}
        return {"graph_projection_status": "persisted", "graph_mutations_persisted": 2}


@pytest.mark.asyncio
async def test_a_redelivery_completes_a_projection_a_graph_outage_left_failed(service, tenant_id) -> None:
    projector = _FlakyProjector()
    service.engine._projector = projector  # noqa: SLF001 - test seam
    task = await service.register_task(tenant_id, agent_platform="xai_grok")
    call = {"agent_platform": "xai_grok", "call_id": "c7", "correlation_token": task["correlation_token"],
            "occurred_at": iso(0), "output": "ok"}
    first = await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", call)
    linked = [l for l in first[0]["links"] if l["status"] == "linked"]
    assert linked and all(l["graph_projection_status"] == "failed" for l in linked)
    projector.down = False
    again = await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", call)
    assert again[0]["duplicate"] is True
    retried = [l for l in again[0]["links"] if l["status"] == "linked"]
    assert retried and all(l["graph_projection_status"] == "persisted" for l in retried)
    row = await service.engine._verdicts.get(tenant_id, retried[0]["verdict_id"])  # noqa: SLF001
    assert row["graph_projection_status"] == "persisted" and row["graph_projection_attempts"] == 2
    # Once complete, a further redelivery projects nothing.
    calls = projector.calls
    third = await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", call)
    assert third[0]["links"] == [] and projector.calls == calls


@pytest.mark.asyncio
async def test_a_redelivery_resumes_an_ingestion_that_failed_after_the_save(service, tenant_id, monkeypatch) -> None:
    task = await service.register_task(tenant_id, agent_platform="xai_grok")
    call = {"agent_platform": "xai_grok", "call_id": "c9", "correlation_token": task["correlation_token"],
            "occurred_at": iso(0), "output": "ok"}
    keys = service.engine._keys  # noqa: SLF001 - test seam
    real = keys.observations_for

    async def down(*a, **k):
        raise ConnectionError("key index down")

    monkeypatch.setattr(keys, "observations_for", down)
    with pytest.raises(ConnectionError):
        await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", call)
    monkeypatch.setattr(keys, "observations_for", real)
    again = await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", call)
    assert again[0]["duplicate"] is True
    assert any(l["status"] == "linked" for l in again[0]["links"])  # correlation resumed
    third = await service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", call)
    assert third[0]["links"] == []  # complete now: nothing replayed


@pytest.mark.asyncio
async def test_matching_observations_ingested_concurrently_still_link(service, tenant_id) -> None:
    import asyncio

    await connect_verified_account(tenant_id, account_key=STORE)
    task = await service.register_task(tenant_id, agent_platform="xai_grok")
    gid = "gid://shopify/InventoryLevel/77?inventory_item_id=66"
    call = {"correlation_token": task["correlation_token"], "agent_platform": "xai_grok", "call_id": "race_1",
            "tool_name": "set-inventory", "input": {"available": 3},
            "output": {"inventoryLevel": {"id": gid}}, "occurred_at": iso(5)}
    level = {"inventory_item_id": 66, "location_id": 7, "available": 3, "updated_at": iso(6),
             "admin_graphql_api_id": gid, "user_id": 4242}

    # Force the worst interleaving: neither observation may write its keys until
    # BOTH have reached the indexing step. With the old order (look up, then
    # index) each side has finished every lookup by then and misses the other;
    # indexing first means both lookups run after both keys are published.
    keys = service.engine._keys  # noqa: SLF001 - test seam
    real_index, real_lookup = keys.index, keys.observations_for
    arrived: set[str] = set()
    both_arrived = asyncio.Event()

    async def index(tenant, observation_id, ks):
        arrived.add(observation_id)
        if len(arrived) >= 2:
            both_arrived.set()
        try:
            await asyncio.wait_for(both_arrived.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        await real_index(tenant, observation_id, ks)

    lookup = real_lookup
    keys.index, keys.observations_for = index, lookup
    try:
        tool, shop = await asyncio.gather(
            service.ingest_record(tenant_id, "aether_mcp", "tool_call_reported", call),
            service.ingest_record(tenant_id, "shopify", "inventory_level", level,
                                  account_bindings={"shopify": {"source_account_key": STORE}}),
        )
    finally:
        keys.index, keys.observations_for = real_index, real_lookup

    tool_id = "aether_mcp:tool_call:xai_grok:race_1"
    links = [l for l in tool[0]["links"] + shop[0]["links"]
             if l["status"] == "linked" and l["key_kind"] == "shared_object_ref"
             and tool_id in (l["other_observation_id"], tool[0]["observation_id"])]
    assert links, "concurrently ingested matching observations must link"
    # Both sides may find each other; the symmetric verdict id means one verdict.
    assert len({l["verdict_id"] for l in links}) == 1
