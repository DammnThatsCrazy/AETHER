"""Sandbox recorders: create test activity, then read back the provider's own records.

Each recorder talks to one provider's sandbox and returns the raw records the
provider returned. Credentials come from the environment, or from the
session's credential proxy, which replaces the placeholder values sent here.

Guardrails:

* Stripe: the account must report ``livemode: false`` before anything is
  created; a live key is refused.
* Shopify: only draft products are created, and they are deleted afterwards.
* Ramp and Cloudflare: read-only.
* OpenAI Agents: runs one traced agent turn when the ``openai-agents`` package
  is installed; otherwise the kind is skipped, not certified.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import httpx

SHOPIFY_API_VERSION = "2026-07"
POLL_ATTEMPTS = 10
POLL_DELAY_S = 2.0


class RecorderError(RuntimeError):
    """A recorder could not complete. The message names the step, never a secret."""


class RecorderSkipped(RuntimeError):
    """The recorder's prerequisites are absent (credentials, SDK)."""


@dataclass
class Recording:
    provider: str
    kind: str
    recorder: str
    raw: dict[str, Any]
    provider_api: dict[str, str]
    account_bindings: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class RecordingContext:
    token: str
    task_ref: str


def _env(name: str, placeholder: Optional[str] = None, *, required: bool = False) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if required:
        raise RecorderSkipped(f"{name} is not set")
    return placeholder or ""


def _check(resp: httpx.Response, step: str) -> Any:
    if resp.status_code >= 400:
        # Provider error bodies can echo request fields; keep only the status and step.
        raise RecorderError(f"{step} failed with HTTP {resp.status_code}")
    return resp.json()


async def _poll(fetch: Callable[[], Awaitable[Optional[dict[str, Any]]]], step: str) -> dict[str, Any]:
    for _ in range(POLL_ATTEMPTS):
        found = await fetch()
        if found is not None:
            return found
        await asyncio.sleep(POLL_DELAY_S)
    raise RecorderError(f"{step}: provider did not return the record in time")


# ── Stripe ────────────────────────────────────────────────────────────────

async def record_stripe(client: httpx.AsyncClient, ctx: RecordingContext) -> list[Recording]:
    key = _env("STRIPE_SANDBOX_SECRET_KEY", "sk_test_supplied_by_credential_proxy")
    headers = {"Authorization": f"Bearer {key}"}
    base = "https://api.stripe.com/v1"

    balance = _check(await client.get(f"{base}/balance", headers=headers), "stripe balance")
    if balance.get("livemode") is not False:
        raise RecorderError("stripe key is not a test-mode key; refusing to create objects")
    account = _check(await client.get(f"{base}/account", headers=headers), "stripe account")
    account_id = str(account.get("id") or "")
    if not account_id:
        raise RecorderError("stripe account id missing")

    intent = _check(await client.post(f"{base}/payment_intents", headers=headers, data={
        "amount": "100", "currency": "usd", "confirm": "true", "payment_method": "pm_card_visa",
        "automatic_payment_methods[enabled]": "true", "automatic_payment_methods[allow_redirects]": "never",
        "metadata[aether_correlation]": ctx.token, "description": "Aether correlation certification",
    }), "stripe create payment intent")
    if intent.get("livemode") is not False:
        raise RecorderError("stripe returned a live object; aborting")
    refund = _check(await client.post(f"{base}/refunds", headers=headers, data={
        "payment_intent": intent["id"], "metadata[aether_correlation]": ctx.token,
    }), "stripe create refund")

    async def find_event(types: list[str], object_id: str) -> Optional[dict[str, Any]]:
        params = [("limit", "25")] + [("types[]", t) for t in types]
        events = _check(await client.get(f"{base}/events", headers=headers, params=params), "stripe list events")
        for event in events.get("data", []):
            if (event.get("data") or {}).get("object", {}).get("id") == object_id:
                return event
        return None

    pi_event = await _poll(lambda: find_event(["payment_intent.succeeded"], intent["id"]), "stripe payment_intent.succeeded")
    refund_event = await _poll(lambda: find_event(["refund.created", "refund.updated"], refund["id"]), "stripe refund event")
    bindings = {"stripe": {"source_account_key": account_id, "source_account_realm": "test"}}
    out = []
    for name, event in (("stripe.payment_intent_succeeded", pi_event), ("stripe.refund_created", refund_event)):
        api = {"host": "api.stripe.com", "api_version": str(event.get("api_version") or "")}
        out.append(Recording("stripe", "event", name, event, api, bindings))
    return out


# ── Shopify ───────────────────────────────────────────────────────────────

async def record_shopify(client: httpx.AsyncClient, ctx: RecordingContext) -> list[Recording]:
    shop = _env("SHOPIFY_SANDBOX_SHOP", required=True)
    token = _env("SHOPIFY_SANDBOX_ACCESS_TOKEN", "shpat_supplied_by_credential_proxy")
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    admin = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}"
    api = {"host": shop.split(".", 1)[-1] if "." in shop else shop, "api_version": SHOPIFY_API_VERSION}
    bindings = {"shopify": {"source_account_key": shop, "source_account_realm": "test"}}

    async def gql(query: str, variables: dict[str, Any], step: str) -> dict[str, Any]:
        body = _check(await client.post(f"{admin}/graphql.json", headers=headers,
                                        json={"query": query, "variables": variables}), step)
        if body.get("errors"):
            raise RecorderError(f"{step} returned GraphQL errors")
        return body["data"]

    created = await gql(
        """mutation($product: ProductCreateInput!) {
             productCreate(product: $product) {
               product { id variants(first: 1) { nodes { inventoryItem { id } } } }
               userErrors { message }
             } }""",
        {"product": {"title": "Aether correlation certification", "status": "DRAFT", "tags": [ctx.token]}},
        "shopify productCreate",
    )
    result = created["productCreate"]
    if result["userErrors"] or not result["product"]:
        raise RecorderError("shopify productCreate returned user errors")
    product_gid = result["product"]["id"]
    product_id = product_gid.rsplit("/", 1)[-1]
    out: list[Recording] = []
    try:
        product = _check(await client.get(f"{admin}/products/{product_id}.json", headers=headers), "shopify read product")
        out.append(Recording("shopify", "product", "shopify.product_draft", product["product"], api, bindings))

        item_gid = result["product"]["variants"]["nodes"][0]["inventoryItem"]["id"]
        locations = await gql("{ locations(first: 1) { nodes { id } } }", {}, "shopify locations")
        location_gid = locations["locations"]["nodes"][0]["id"]
        await gql(
            """mutation($id: ID!) { inventoryItemUpdate(id: $id, input: {tracked: true}) { userErrors { message } } }""",
            {"id": item_gid}, "shopify track inventory")
        await gql(
            """mutation($item: ID!, $loc: ID!) { inventoryActivate(inventoryItemId: $item, locationId: $loc) { userErrors { message } } }""",
            {"item": item_gid, "loc": location_gid}, "shopify activate inventory")
        await gql(
            """mutation($input: InventorySetQuantitiesInput!) {
                 inventorySetQuantities(input: $input) { userErrors { message } } }""",
            {"input": {"name": "available", "reason": "correction", "ignoreCompareQuantity": True,
                       "quantities": [{"inventoryItemId": item_gid, "locationId": location_gid, "quantity": 5}]}},
            "shopify set inventory")
        item_id = item_gid.rsplit("/", 1)[-1]
        levels = _check(await client.get(f"{admin}/inventory_levels.json", headers=headers,
                                         params={"inventory_item_ids": item_id}), "shopify read inventory level")
        if levels.get("inventory_levels"):
            out.append(Recording("shopify", "inventory_level", "shopify.inventory_set",
                                 levels["inventory_levels"][0], api, bindings))

        node = await gql(
            """query($id: ID!, $item: ID!) {
                 product(id: $id) { id createdAt updatedAt tags variants(first: 5) { nodes { id inventoryItem { id } } } }
                 inventoryItem(id: $item) { inventoryLevels(first: 1) { nodes { id updatedAt item { id } location { id } } } }
               }""",
            {"id": product_gid, "item": item_gid}, "shopify read graphql nodes")
        if node.get("product"):
            out.append(Recording("shopify", "product_graphql", "shopify.product_draft_graphql",
                                 node["product"], api, bindings))
        levels_gql = ((node.get("inventoryItem") or {}).get("inventoryLevels") or {}).get("nodes") or []
        if levels_gql:
            out.append(Recording("shopify", "inventory_level_graphql", "shopify.inventory_set_graphql",
                                 levels_gql[0], api, bindings))

        orders = _check(await client.get(f"{admin}/orders.json", headers=headers,
                                         params={"status": "any", "limit": "1"}), "shopify read orders")
        if orders.get("orders"):
            out.append(Recording("shopify", "order", "shopify.existing_order", orders["orders"][0], api, bindings))
    finally:
        await gql("""mutation($id: ID!) { productDelete(input: {id: $id}) { deletedProductId } }""",
                  {"id": product_gid}, "shopify productDelete")
    return out


# ── Ramp ──────────────────────────────────────────────────────────────────

async def record_ramp(client: httpx.AsyncClient, ctx: RecordingContext) -> list[Recording]:
    base = os.environ.get("RAMP_SANDBOX_BASE_URL", "https://demo-api.ramp.com").rstrip("/")
    client_id = _env("RAMP_SANDBOX_CLIENT_ID", "proxy")
    client_secret = _env("RAMP_SANDBOX_CLIENT_SECRET", "proxy")
    token = _check(await client.post(
        f"{base}/developer/v1/token", auth=(client_id, client_secret),
        data={"grant_type": "client_credentials", "scope": "business:read transactions:read limits:read"},
    ), "ramp token")
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    business = _check(await client.get(f"{base}/developer/v1/business", headers=headers), "ramp business")
    bindings = {"ramp": {"source_account_key": str(business.get("id") or "ramp_sandbox"), "source_account_realm": "test"}}
    api = {"host": base.split("//", 1)[-1], "api_version": "developer/v1"}
    out = []
    txns = _check(await client.get(f"{base}/developer/v1/transactions", headers=headers, params={"page_size": "3"}), "ramp transactions")
    out += [Recording("ramp", "transaction", "ramp.transactions_list", t, api, bindings) for t in txns.get("data", [])[:3]]
    limits = _check(await client.get(f"{base}/developer/v1/limits", headers=headers, params={"page_size": "3"}), "ramp limits")
    out += [Recording("ramp", "limit", "ramp.limits_list", l, api, bindings) for l in limits.get("data", [])[:3]]
    return out


# ── Cloudflare ────────────────────────────────────────────────────────────

async def record_cloudflare(client: httpx.AsyncClient, ctx: RecordingContext) -> list[Recording]:
    account = _env("CLOUDFLARE_ACCOUNT_ID", required=True)
    gateway = _env("CLOUDFLARE_AI_GATEWAY_ID", required=True)
    token = _env("CLOUDFLARE_API_TOKEN", "cf_supplied_by_credential_proxy")
    resp = await client.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai-gateway/gateways/{gateway}/logs",
        headers={"Authorization": f"Bearer {token}"}, params={"per_page": "5"},
    )
    body = _check(resp, "cloudflare ai gateway logs")
    api = {"host": "api.cloudflare.com", "api_version": "client/v4"}
    return [Recording("cloudflare", "ai_gateway_log", "cloudflare.ai_gateway_logs", log, api)
            for log in (body.get("result") or [])[:5]]


# ── OpenAI Agents ─────────────────────────────────────────────────────────

async def record_openai(client: httpx.AsyncClient, ctx: RecordingContext) -> list[Recording]:
    try:
        import agents  # type: ignore[import-not-found]
        from agents.tracing import TracingProcessor  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RecorderSkipped("the openai-agents package is not installed") from exc
    _env("OPENAI_API_KEY", required=True)

    exported: list[dict[str, Any]] = []

    class Capture(TracingProcessor):  # type: ignore[misc, valid-type]
        def on_trace_start(self, trace: Any) -> None: ...
        def on_trace_end(self, trace: Any) -> None:
            item = trace.export()
            if item:
                exported.append(item)
        def on_span_start(self, span: Any) -> None: ...
        def on_span_end(self, span: Any) -> None:
            item = span.export()
            if item:
                exported.append(item)
        def shutdown(self) -> None: ...
        def force_flush(self) -> None: ...

    @agents.function_tool
    def lookup_order(order_ref: str) -> str:
        """Return the reference the caller asked about."""
        return f"order {order_ref}"

    agents.add_trace_processor(Capture())
    agent = agents.Agent(name="aether-certification", instructions="Call lookup_order once with ORDER-1.",
                         tools=[lookup_order])
    with agents.trace("aether-certification", metadata={"aether_correlation": ctx.token}):
        await agents.Runner.run(agent, "Look up ORDER-1.")
    if not exported:
        raise RecorderError("openai agents produced no trace export")
    api = {"host": "api.openai.com", "api_version": f"openai-agents {getattr(agents, '__version__', 'unknown')}"}
    return [Recording("openai", "export", "openai.agents_trace", {"data": exported}, api)]


RECORDERS: dict[str, Callable[[httpx.AsyncClient, RecordingContext], Awaitable[list[Recording]]]] = {
    "stripe": record_stripe,
    "shopify": record_shopify,
    "ramp": record_ramp,
    "cloudflare": record_cloudflare,
    "openai": record_openai,
}
