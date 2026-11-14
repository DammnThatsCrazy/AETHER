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


KINDS = {
    "order": ("system_of_record", map_order),
    "inventory_level": ("system_of_record", map_inventory_level),
    "product": ("system_of_record", map_product),
    "access_grant": ("authority_issuer", map_access_grant),
}
