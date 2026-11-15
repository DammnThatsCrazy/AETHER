"""Stripe: system of record for payments, refunds, and disputes.

Input is a Stripe event (``payment_intent.*``, ``charge.*``, ``refund.*``,
``charge.dispute.*``). An agent can carry an Aether correlation token in the
object's ``metadata`` or ``description``, which joins the payment to the
agent's task exactly, however long after the task it settles.
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
    stripe_ref,
)
from shared.integration_contracts.correlation import CorrelationObservation

FAMILY = "stripe"
_OBJECT_TYPES = {
    "payment_intent": "payment_intent",
    "charge": "charge",
    "refund": "refund",
    "dispute": "dispute",
}


def map_event(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    event_id = str(require(record, "id"))
    data = record.get("data")
    obj = data.get("object") if isinstance(data, Mapping) else None
    if not isinstance(obj, Mapping):
        raise MappingError("data.object is required")
    object_type = _OBJECT_TYPES.get(str(obj.get("object") or ""))
    if object_type is None:
        raise MappingError("only payment_intent, charge, refund, and dispute objects are mapped")
    object_id = str(require(obj, "id"))
    occurred = parse_time(record.get("created"), field_name="created")

    realm = "live" if record.get("livemode") is True else "test"
    bound = ctx.account_bindings.get(FAMILY)
    # Connect events name the connected account in ``account``; newer API
    # versions also name the owning account in ``context``.
    account_key = (
        opt_str(record.get("account"))
        or opt_str(record.get("context"))
        or (bound.source_account_key if bound else None)
    )
    if account_key is None:
        raise MappingError("a stripe account binding or event.account is required")
    binding = ctx.binding_for(FAMILY, account_key, realm)
    if binding is None:  # pragma: no cover - account_key is set above
        raise MappingError("a stripe account binding or event.account is required")

    refs = [stripe_ref(binding, object_type, object_id)]
    for linked_field, linked_type in (("payment_intent", "payment_intent"), ("charge", "charge")):
        linked = obj.get(linked_field)
        if isinstance(linked, str) and linked and linked != object_id:
            refs.append(stripe_ref(binding, linked_type, linked))

    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"stripe:{event_id}",
        source_role="system_of_record",
        provider_family=FAMILY,
        occurred_at=occurred,
        object_refs=tuple(refs),
        correlation_tokens=find_tokens(obj.get("metadata"), obj.get("description")),
    )]


KINDS = {"event": ("system_of_record", map_event)}
