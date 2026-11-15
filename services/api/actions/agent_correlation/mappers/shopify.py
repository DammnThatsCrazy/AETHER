"""Shopify: system of record (orders, inventory, products) and authority issuer.

Inputs are Shopify Admin webhook payloads (``orders/*``, ``inventory_levels/update``,
``products/*``) as delivered to the tenant's connection, plus the access-grant
record the connection captures when a merchant approves an app or AI connector.

Shopify's AI connectors act through a staff account's permissions, so the
actor these records name is a staff account or app, never an agent. The
mapper reports that actor as a provider-asserted reference; whether an agent
acted is decided only by a join with agent-side observations.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from actions.agent_correlation.mappers._common import (
    MapperContext,
    MappingError,
    find_tokens,
    opt_str,
    parse_time,
    require,
    shopify_ref,
)
from shared.integration_contracts.correlation import CorrelationObservation

FAMILY = "shopify"
_GID_NUMBER = re.compile(r"gid://shopify/[A-Za-z]+/(\d+)")


def _binding(ctx: MapperContext):
    binding = ctx.account_bindings.get(FAMILY)
    if binding is None:
        raise MappingError("a shopify account binding (shop domain) is required")
    return binding


def _actors(record: Mapping[str, Any]) -> tuple[str, ...]:
    refs = []
    if opt_str(record.get("app_id")):
        refs.append(f"shopify_app:{record['app_id']}")
    if opt_str(record.get("user_id")):
        refs.append(f"shopify_staff:{record['user_id']}")
    return tuple(refs)


def map_order(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    binding = _binding(ctx)
    order_id = str(require(record, "id"))
    occurred = parse_time(record.get("updated_at") or record.get("created_at"), field_name="updated_at")
    note_attributes = [
        a.get("value") for a in record.get("note_attributes") or [] if isinstance(a, Mapping)
    ]
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"shopify:order:{binding.source_account_key}:{order_id}:{occurred.isoformat()}",
        source_role="system_of_record",
        provider_family=FAMILY,
        occurred_at=occurred,
        object_refs=(shopify_ref(binding, "order", order_id),),
        correlation_tokens=find_tokens(record.get("note"), note_attributes, record.get("tags")),
        actor_refs=_actors(record),
    )]


def map_inventory_level(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    binding = _binding(ctx)
    item_id = str(require(record, "inventory_item_id"))
    location_id = str(require(record, "location_id"))
    occurred = parse_time(record.get("updated_at"), field_name="updated_at")
    refs = [shopify_ref(binding, "inventory_item", item_id)]
    gid = opt_str(record.get("admin_graphql_api_id"))
    level = _GID_NUMBER.match(gid) if gid else None
    if level:
        refs.insert(0, shopify_ref(binding, "inventory_level", level.group(1)))
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=(
            f"shopify:inventory_level:{binding.source_account_key}:{item_id}:{location_id}:{occurred.isoformat()}"
        ),
        source_role="system_of_record",
        provider_family=FAMILY,
        occurred_at=occurred,
        object_refs=tuple(refs),
        actor_refs=_actors(record),
    )]


def map_product(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    binding = _binding(ctx)
    product_id = str(require(record, "id"))
    occurred = parse_time(record.get("updated_at") or record.get("created_at"), field_name="updated_at")
    refs = [shopify_ref(binding, "product", product_id)]
    for variant in record.get("variants") or []:
        if isinstance(variant, Mapping) and opt_str(variant.get("id")):
            refs.append(shopify_ref(binding, "product_variant", str(variant["id"])))
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"shopify:product:{binding.source_account_key}:{product_id}:{occurred.isoformat()}",
        source_role="system_of_record",
        provider_family=FAMILY,
        occurred_at=occurred,
        object_refs=tuple(refs[:32]),
        correlation_tokens=find_tokens(record.get("tags")),
        actor_refs=_actors(record),
    )]


def map_access_grant(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    """An app or AI-connector access approval captured by the connection."""
    binding = _binding(ctx)
    grant_id = str(require(record, "grant_id"))
    occurred = parse_time(record.get("granted_at"), field_name="granted_at")
    actors = []
    if opt_str(record.get("app_id")):
        actors.append(f"shopify_app:{record['app_id']}")
    if opt_str(record.get("staff_user_id")):
        actors.append(f"shopify_staff:{record['staff_user_id']}")
    if not actors:
        raise MappingError("an access grant must name the app or the staff account it binds")
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"shopify:access_grant:{binding.source_account_key}:{grant_id}",
        source_role="authority_issuer",
        provider_family=FAMILY,
        occurred_at=occurred,
        actor_refs=tuple(actors),
        correlation_tokens=find_tokens(record.get("note")),
    )]


# ── Admin GraphQL records ────────────────────────────────────────────────
#
# The provider runtime's GraphQL readers and the Shopify connector return
# Admin GraphQL nodes rather than webhook payloads. Each GraphQL kind
# translates its node into the webhook field names and reuses the mapper
# above, so one object revision yields the same observation ID whichever path
# delivered it, and the two paths deduplicate instead of double counting.


def _gid_number(value: Any, field: str) -> str:
    match = _GID_NUMBER.match(str(value or ""))
    if not match:
        raise MappingError(f"{field} must be a Shopify GID")
    return match.group(1)


def _node_id(node: Any) -> Any:
    return node.get("id") if isinstance(node, Mapping) else None


def _nodes(connection: Any) -> list[Mapping[str, Any]]:
    if isinstance(connection, Mapping):
        items = connection.get("nodes")
        if items is None and isinstance(connection.get("edges"), list):
            items = [e.get("node") for e in connection["edges"] if isinstance(e, Mapping)]
        return [n for n in items or [] if isinstance(n, Mapping)]
    return []


def map_product_graphql(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    variants = [
        {"id": _gid_number(v.get("id"), "variant id")} for v in _nodes(record.get("variants")) if v.get("id")
    ]
    return map_product(ctx, {
        "id": _gid_number(require(record, "id"), "id"),
        "admin_graphql_api_id": record.get("id"),
        "updated_at": record.get("updatedAt") or record.get("createdAt"),
        "created_at": record.get("createdAt"),
        "tags": record.get("tags"),
        "variants": variants,
    })


def map_inventory_level_graphql(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    return map_inventory_level(ctx, {
        "inventory_item_id": _gid_number(_node_id(record.get("item")), "item.id"),
        "location_id": _gid_number(_node_id(record.get("location")), "location.id"),
        "updated_at": record.get("updatedAt"),
        "admin_graphql_api_id": require(record, "id"),
    })


def map_order_graphql(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    """An Admin GraphQL order.

    ``staffMember`` needs the ``read_users`` scope, which Shopify grants only to
    finance embedded apps and Plus or Advanced stores (found by sandbox
    certification). Elsewhere it is null or denied, so the staff actor is
    absent and only the app actor remains: absence never means "no staff".
    """
    app_gid = _node_id(record.get("app"))
    staff_gid = _node_id(record.get("staffMember"))
    return map_order(ctx, {
        "id": _gid_number(require(record, "id"), "id"),
        "updated_at": record.get("updatedAt") or record.get("createdAt"),
        "created_at": record.get("createdAt"),
        "note": record.get("note"),
        "note_attributes": [
            {"name": a.get("key"), "value": a.get("value")}
            for a in record.get("customAttributes") or []
            if isinstance(a, Mapping)
        ],
        "tags": record.get("tags"),
        "app_id": _gid_number(app_gid, "app.id") if app_gid else None,
        "user_id": _gid_number(staff_gid, "staffMember.id") if staff_gid else None,
    })


KINDS = {
    "order": ("system_of_record", map_order),
    "inventory_level": ("system_of_record", map_inventory_level),
    "product": ("system_of_record", map_product),
    "access_grant": ("authority_issuer", map_access_grant),
    "order_graphql": ("system_of_record", map_order_graphql),
    "inventory_level_graphql": ("system_of_record", map_inventory_level_graphql),
    "product_graphql": ("system_of_record", map_product_graphql),
}
