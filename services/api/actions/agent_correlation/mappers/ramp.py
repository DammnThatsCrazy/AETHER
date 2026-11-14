"""Ramp: system of record for card spend, and authority issuer for card limits.

Inputs are Ramp API objects: a transaction, and a limit (spend program or
card limit) record. A transaction and its limit share the card and the card
holder, so the join between spend and the authority behind it is a
provider-asserted actor match. An agent that stamps its correlation token in a
transaction memo or a limit's display name joins exactly.
"""

from __future__ import annotations

from typing import Any, Mapping

from actions.agent_correlation.mappers._common import (
    MapperContext,
    MappingError,
    find_tokens,
    opt_str,
    parse_time,
    require,
)
from shared.integration_contracts.correlation import CorrelationObservation, ObservedObjectRef

FAMILY = "ramp"


def _binding(ctx: MapperContext):
    binding = ctx.account_bindings.get(FAMILY)
    if binding is None:
        raise MappingError("a ramp account binding (business) is required")
    return binding


def _card_actors(record: Mapping[str, Any]) -> tuple[str, ...]:
    refs = []
    card_id = opt_str(record.get("card_id"))
    if card_id:
        refs.append(f"ramp_card:{card_id}")
    holder = record.get("card_holder")
    user_id = opt_str(holder.get("user_id")) if isinstance(holder, Mapping) else opt_str(record.get("user_id"))
    if user_id:
        refs.append(f"ramp_user:{user_id}")
    return tuple(refs)


def map_transaction(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    binding = _binding(ctx)
    txn_id = str(require(record, "id"))
    occurred = parse_time(record.get("user_transaction_time"), field_name="user_transaction_time")
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"ramp:transaction:{binding.source_account_key}:{txn_id}",
        source_role="system_of_record",
        provider_family=FAMILY,
        occurred_at=occurred,
        object_refs=(ObservedObjectRef(
            provider_family=FAMILY,
            source_account_realm=binding.source_account_realm,  # type: ignore[arg-type]
            source_account_key=binding.source_account_key,
            object_type="card_transaction",
            object_id=txn_id,
            account_verification_ref=binding.verification_ref,
        ),),
        correlation_tokens=find_tokens(record.get("memo")),
        actor_refs=_card_actors(record),
    )]


def map_limit(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    binding = _binding(ctx)
    limit_id = str(require(record, "id"))
    occurred = parse_time(record.get("updated_at") or record.get("created_at"), field_name="created_at")
    actors = _card_actors(record)
    if not actors:
        raise MappingError("a limit must name the card or the card holder it governs")
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"ramp:limit:{binding.source_account_key}:{limit_id}:{occurred.isoformat()}",
        source_role="authority_issuer",
        provider_family=FAMILY,
        occurred_at=occurred,
        actor_refs=actors,
        correlation_tokens=find_tokens(record.get("display_name"), record.get("memo")),
    )]


KINDS = {
    "transaction": ("system_of_record", map_transaction),
    "limit": ("authority_issuer", map_limit),
}
