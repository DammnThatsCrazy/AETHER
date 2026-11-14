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

from actions.agent_correlation.mcp_server import handle_jsonrpc

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
    await service.bindings.put(tenant_id, "shopify", STORE, "live")
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

    # 3. Shopify's webhook arrives: the change is attributed to a staff account.
    shop = await service.ingest_record(tenant_id, "shopify", "inventory_level", {
        "inventory_item_id": 55, "location_id": 7, "available": 40, "updated_at": iso(8),
        "admin_graphql_api_id": "gid://shopify/InventoryLevel/991?inventory_item_id=55",
        "user_id": 4242,
    })
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
    assert span_link["status"] == "linked" and span_link["key_kind"] == "shared_object_ref"


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
