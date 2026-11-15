"""Vendor mapper contracts and the HTTP routes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from actions.agent_correlation import routes as correlation_routes
from actions.agent_correlation.keys import CorrelationKeyError, parse_keyring
from actions.agent_correlation.mappers import PROVIDERS, AccountBinding, MapperContext, MappingError, catalog, map_record
from actions.agent_correlation.mappers._common import find_object_refs, parse_time
from shared.integration_contracts.source_roles import SOURCE_ROLES

CTX = MapperContext(tenant_id="t1", account_bindings={
    "shopify": AccountBinding("acme.myshopify.com"), "ramp": AccountBinding("biz"), "stripe": AccountBinding("acct_1"),
})


def test_every_registered_kind_declares_known_roles() -> None:
    for kinds in PROVIDERS.values():
        for entry in kinds.values():
            assert entry.roles and entry.roles <= set(SOURCE_ROLES)
    providers = {row["provider"] for row in catalog()}
    assert providers == {"shopify", "stripe", "ramp", "cloudflare", "openai", "aether_mcp"}


def test_roles_per_vendor_follow_what_each_stream_proves() -> None:
    roles = {(r["provider"], r["kind"]): set(r["roles"]) for r in catalog()}
    assert roles[("shopify", "order")] == {"system_of_record"}
    assert roles[("shopify", "access_grant")] == {"authority_issuer"}
    assert roles[("ramp", "limit")] == {"authority_issuer"}
    assert roles[("cloudflare", "ai_gateway_log")] == {"network_observer"}
    assert roles[("openai", "export")] == {"agent_runtime", "tool_bridge"}


def test_shopify_order_reads_staff_app_and_token_from_note() -> None:
    (obs,) = map_record("shopify", "order", CTX, {
        "id": 1001, "updated_at": "2026-11-14T12:00:00Z", "app_id": 55, "user_id": 9,
        "note": "no token here", "note_attributes": [{"name": "x", "value": "y"}],
    })
    assert obs.source_role == "system_of_record"
    assert obs.actor_refs == ("shopify_app:55", "shopify_staff:9")
    assert obs.object_refs[0].object_type == "order" and obs.object_refs[0].source_account_key == "acme.myshopify.com"


def test_shopify_requires_an_account_binding() -> None:
    with pytest.raises(MappingError, match="account binding"):
        map_record("shopify", "order", MapperContext(tenant_id="t1"), {"id": 1, "updated_at": "2026-11-14T12:00:00Z"})


def test_stripe_maps_realm_and_rejects_other_objects() -> None:
    (obs,) = map_record("stripe", "event", MapperContext(tenant_id="t1"), {
        "id": "evt_1", "created": 1763121600, "livemode": False, "account": "acct_9",
        "data": {"object": {"object": "charge", "id": "ch_1Abcdefghij", "payment_intent": "pi_1Abcdefghij"}},
    })
    assert {r.object_type for r in obs.object_refs} == {"charge", "payment_intent"}
    assert {r.source_account_realm for r in obs.object_refs} == {"test"}
    with pytest.raises(MappingError):
        map_record("stripe", "event", CTX, {"id": "e", "created": 1, "data": {"object": {"object": "customer", "id": "cus_1"}}})


def test_ramp_limit_needs_a_card_or_holder() -> None:
    with pytest.raises(MappingError, match="card"):
        map_record("ramp", "limit", CTX, {"id": "l1", "created_at": "2026-11-14T12:00:00Z"})


def test_cloudflare_nanosecond_edge_time_and_signature_flag() -> None:
    (obs,) = map_record("cloudflare", "http_request", CTX, {
        "RayID": "r1", "EdgeStartTimestamp": 1763121600123456789, "signature_nonce": "n", "signature_verified": True,
    })
    assert obs.occurred_at.year == 2025 or obs.occurred_at.year == 2026
    assert obs.signed_request.signature_verified is True
    with pytest.raises(MappingError):
        map_record("cloudflare", "http_request", CTX, {"RayID": "r", "EdgeStartTimestamp": 1, "signature_verified": "yes"})


def test_object_refs_need_a_binding_for_their_family() -> None:
    text = "gid://shopify/Product/12 and pi_1Abcdefghij"
    assert {r.provider_family for r in find_object_refs(CTX, text)} == {"shopify", "stripe"}
    assert find_object_refs(MapperContext(tenant_id="t1"), text) == ()


def test_unknown_mapper_and_bad_time() -> None:
    with pytest.raises(MappingError):
        map_record("nobody", "x", CTX, {})
    with pytest.raises(MappingError):
        parse_time("2026-11-14T12:00:00", field_name="t")  # no timezone
    assert parse_time("1763121600", field_name="t") == datetime.fromtimestamp(1763121600, tz=timezone.utc)


def test_aether_mcp_rejects_bad_platform_and_missing_token() -> None:
    with pytest.raises(MappingError):
        map_record("aether_mcp", "outcome_reported", CTX, {
            "agent_platform": "Bad Platform", "outcome_id": "o", "correlation_token": "x", "occurred_at": "2026-11-14T12:00:00Z"})
    with pytest.raises(MappingError, match="correlation token"):
        map_record("aether_mcp", "outcome_reported", CTX, {
            "agent_platform": "xai_grok", "outcome_id": "o", "correlation_token": "x", "occurred_at": "2026-11-14T12:00:00Z"})


def test_keyring_parsing() -> None:
    assert parse_keyring([]) is None
    ring = parse_keyring(["new:" + "Y" * 43, "old:" + "Z" * 43])
    assert ring.signing_key_id == "new" and set(ring.keys) == {"new", "old"}
    for bad in (["nokey"], ["k:short"], ["k:" + "Y" * 43, "k:" + "Z" * 43]):
        with pytest.raises(CorrelationKeyError):
            parse_keyring(bad)


# --- routes -------------------------------------------------------------------


class _Tenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def has_permission(self, _perm: str) -> bool:
        return True


@pytest.fixture
def client(service, tenant_id, monkeypatch):
    monkeypatch.setattr(correlation_routes, "get_service", lambda: service)
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request: Request, call_next):
        request.state.tenant = _Tenant(tenant_id)
        return await call_next(request)

    app.include_router(correlation_routes.router)
    return TestClient(app)


def test_routes_register_ingest_and_explain(client) -> None:
    base = correlation_routes.PREFIX
    assert client.put(f"{base}/account-bindings/stripe", json={"source_account_key": "acct_1"}).status_code == 200
    task = client.post(f"{base}/tasks", json={"agent_platform": "xai_grok", "agent_ref": "bot"}).json()
    resp = client.post(f"{base}/observations/stripe/event", json={"record": {
        "id": "evt_r", "created": int(datetime.now(timezone.utc).timestamp()), "livemode": True,
        "data": {"object": {"object": "payment_intent", "id": "pi_rAbcdefghij",
                            "metadata": {"aether_correlation": task["correlation_token"]}}},
    }})
    assert resp.status_code == 201
    assert resp.json()["observations"][0]["links"][0]["status"] == "linked"
    chain = client.get(f"{base}/tasks/{task['task_ref']}/chain").json()
    assert {o["provider"] for o in chain["observations"]} == {"aether_mcp", "stripe"}
    obs_chain = client.get(f"{base}/observations/stripe:evt_r/chain")
    assert obs_chain.status_code == 200
    assert client.get(f"{base}/tasks/ctk_unknownunknownunk/chain").status_code == 404
    assert client.get(f"{base}/catalog").json()["token_issuance_available"] is True


def test_routes_reject_bad_records_and_execution(client) -> None:
    base = correlation_routes.PREFIX
    assert client.post(f"{base}/observations/stripe/event", json={"record": {"id": "e"}}).status_code == 422
    assert client.post(f"{base}/observations/stripe/event",
                       json={"record": {"execution_by_aether": True}}).status_code == 422
    assert client.post(f"{base}/tasks", json={"agent_platform": "Not Valid"}).status_code == 422


def test_mcp_route_handles_batches_and_notifications(client) -> None:
    url = f"{correlation_routes.PREFIX}/mcp"
    assert client.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    batch = client.post(url, json=[
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]).json()
    assert [r["id"] for r in batch] == [1, 2]
    assert client.post(url, content=b"{not json", headers={"content-type": "application/json"}).status_code == 400


def test_stripe_reads_the_owning_account_from_context() -> None:
    """Found by sandbox certification: newer events name the account in ``context``."""
    (obs,) = map_record("stripe", "event", MapperContext(tenant_id="t1"), {
        "id": "evt_c", "created": 1793832998, "livemode": False, "context": "acct_ctx",
        "data": {"object": {"object": "payment_intent", "id": "pi_cAbcdefghij"}},
    })
    assert obs.object_refs[0].source_account_key == "acct_ctx"


def test_shopify_graphql_and_webhook_records_converge_on_one_observation() -> None:
    """The same product revision from a webhook and from Admin GraphQL is one observation."""
    (rest,) = map_record("shopify", "product", CTX, {
        "id": 8801, "updated_at": "2026-11-14T07:00:00-05:00", "tags": "a, b", "variants": [{"id": 42}],
    })
    (gql,) = map_record("shopify", "product_graphql", CTX, {
        "id": "gid://shopify/Product/8801", "updatedAt": "2026-11-14T12:00:00Z", "tags": ["a", "b"],
        "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/42", "inventoryItem": {"id": "gid://shopify/InventoryItem/7"}}]},
    })
    assert rest.observation_id == gql.observation_id
    assert {r.scope_key for r in rest.object_refs} == {r.scope_key for r in gql.object_refs}


def test_shopify_graphql_inventory_and_order() -> None:
    (level,) = map_record("shopify", "inventory_level_graphql", CTX, {
        "id": "gid://shopify/InventoryLevel/991?inventory_item_id=55", "updatedAt": "2026-11-14T12:00:00Z",
        "item": {"id": "gid://shopify/InventoryItem/55"}, "location": {"id": "gid://shopify/Location/7"},
    })
    (rest_level,) = map_record("shopify", "inventory_level", CTX, {
        "inventory_item_id": 55, "location_id": 7, "updated_at": "2026-11-14T12:00:00Z",
        "admin_graphql_api_id": "gid://shopify/InventoryLevel/991?inventory_item_id=55",
    })
    assert level.observation_id == rest_level.observation_id
    assert {r.object_type for r in level.object_refs} == {"inventory_level", "inventory_item"}
    (order,) = map_record("shopify", "order_graphql", CTX, {
        "id": "gid://shopify/Order/1001", "updatedAt": "2026-11-14T12:00:00Z", "note": "x",
        "customAttributes": [{"key": "k", "value": "v"}], "app": {"id": "gid://shopify/App/55"},
    })
    assert order.actor_refs == ("shopify_app:55",)
    with pytest.raises(MappingError, match="GID"):
        map_record("shopify", "product_graphql", CTX, {"id": "8801", "updatedAt": "2026-11-14T12:00:00Z"})
