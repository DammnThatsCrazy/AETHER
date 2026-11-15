"""Helpers shared by vendor mappers: time parsing, token and object-ref discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from shared.integration_contracts.correlation import ObservedObjectRef
from shared.integration_contracts.correlation_token import extract_correlation_tokens

MAX_WALK_NODES = 2000
MAX_TOKENS = 8
MAX_OBJECT_REFS = 32


class MappingError(ValueError):
    """A vendor record the mapper cannot interpret. Callers reject, never guess."""


@dataclass(frozen=True)
class AccountBinding:
    """The tenant's account for one provider family.

    ``verification_ref`` is the verified provider account record the binding
    came from (see ``actions.agent_correlation.bindings``). ``None`` means the
    account rests on the tenant's declaration.
    """

    source_account_key: str
    source_account_realm: str = "live"
    verification_ref: Optional[str] = None

    @property
    def verified(self) -> bool:
        return bool(self.verification_ref)


@dataclass(frozen=True)
class MapperContext:
    tenant_id: str
    # provider_family -> the default account for that family. Agent-side
    # records name provider objects without account scope; a binding supplies
    # it so a tool result can match the system-of-record object exactly.
    account_bindings: Mapping[str, AccountBinding] = field(default_factory=dict)
    # (provider_family, realm, account_key) -> verified binding, for records that
    # name their own account (a payment event's connected account). The realm is
    # part of the key: one account ID can be verified in both live and test.
    verified_accounts: Mapping[tuple[str, str, str], AccountBinding] = field(default_factory=dict)

    def binding_for(self, family: str, account_key: Optional[str], realm: str) -> Optional[AccountBinding]:
        """The binding for an account a record names itself.

        A verified account wins. When the family has verified accounts and the
        record names a different one, the record is rejected rather than
        scoped to an account the tenant never verified.
        """
        if not account_key:
            return self.account_bindings.get(family)
        verified = self.verified_accounts.get((family, realm, account_key))
        if verified is not None:
            return verified
        if any(f == family and k == account_key for f, _r, k in self.verified_accounts):
            raise MappingError(f"{family} account {account_key!r} is verified for a different realm")
        if any(f == family for f, _r, _k in self.verified_accounts):
            raise MappingError(f"{family} account {account_key!r} is not a verified connection for this tenant")
        return AccountBinding(source_account_key=account_key, source_account_realm=realm)


def parse_time(value: Any, *, field_name: str) -> datetime:
    """ISO-8601 text or unix seconds (int, or float/str for sub-second traces)."""
    if isinstance(value, bool) or value is None or value == "":
        raise MappingError(f"{field_name} is required")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d+(\.\d+)?", text):
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MappingError(f"{field_name} is not a timestamp") from exc
        if parsed.tzinfo is None:
            raise MappingError(f"{field_name} must carry a timezone")
        return parsed.astimezone(timezone.utc)
    raise MappingError(f"{field_name} is not a timestamp")


def require(record: Mapping[str, Any], key: str) -> Any:
    value = record.get(key)
    if value is None or value == "":
        raise MappingError(f"{key} is required")
    return value


def iter_strings(value: Any) -> Iterable[str]:
    """Strings anywhere in a nested record, bounded against hostile payloads."""
    stack = [value]
    seen = 0
    while stack and seen < MAX_WALK_NODES:
        node = stack.pop()
        seen += 1
        if isinstance(node, str):
            yield node
        elif isinstance(node, Mapping):
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


def find_tokens(*values: Any) -> tuple[str, ...]:
    found: list[str] = []
    for value in values:
        for text in iter_strings(value):
            if "aet1." not in text:
                continue
            for token in extract_correlation_tokens(text):
                if token not in found:
                    found.append(token)
                if len(found) >= MAX_TOKENS:
                    return tuple(found)
    return tuple(found)


# Object IDs that are recognisable in free text (tool inputs and outputs).
# Each pattern yields (provider_family, object_type, object_id).
_SHOPIFY_GID = re.compile(r"gid://shopify/([A-Za-z]+)/(\d+)")
_SHOPIFY_TYPES = {
    "Product": "product",
    "ProductVariant": "product_variant",
    "InventoryLevel": "inventory_level",
    "InventoryItem": "inventory_item",
    "Order": "order",
    "Collection": "collection",
    "DiscountCodeNode": "discount",
    "DiscountNode": "discount",
}
_STRIPE_ID = re.compile(r"\b(pi|ch|re|in|sub|cus|dp|po)_[A-Za-z0-9]{8,}\b")
_STRIPE_TYPES = {
    "pi": "payment_intent",
    "ch": "charge",
    "re": "refund",
    "in": "invoice",
    "sub": "subscription",
    "cus": "customer",
    "dp": "dispute",
    "po": "payout",
}


def shopify_ref(binding: AccountBinding, object_type: str, object_id: str) -> ObservedObjectRef:
    return ObservedObjectRef(
        provider_family="shopify",
        source_account_realm=binding.source_account_realm,  # type: ignore[arg-type]
        source_account_key=binding.source_account_key,
        object_type=object_type,
        object_id=str(object_id),
        account_verification_ref=binding.verification_ref,
    )


def stripe_ref(binding: AccountBinding, object_type: str, object_id: str) -> ObservedObjectRef:
    return ObservedObjectRef(
        provider_family="stripe",
        source_account_realm=binding.source_account_realm,  # type: ignore[arg-type]
        source_account_key=binding.source_account_key,
        object_type=object_type,
        object_id=str(object_id),
        account_verification_ref=binding.verification_ref,
    )


def find_object_refs(ctx: MapperContext, *values: Any) -> tuple[ObservedObjectRef, ...]:
    """Provider object refs named in free text, scoped by the tenant's bindings.

    A reference to a family the tenant has no binding for is dropped: without
    the account, it cannot match a system-of-record object exactly.
    """
    refs: list[ObservedObjectRef] = []
    shopify = ctx.account_bindings.get("shopify")
    stripe = ctx.account_bindings.get("stripe")
    for value in values:
        for text in iter_strings(value):
            if shopify is not None:
                for kind, number in _SHOPIFY_GID.findall(text):
                    if kind in _SHOPIFY_TYPES:
                        refs.append(shopify_ref(shopify, _SHOPIFY_TYPES[kind], number))
            if stripe is not None:
                for match in _STRIPE_ID.finditer(text):
                    refs.append(stripe_ref(stripe, _STRIPE_TYPES[match.group(1)], match.group(0)))
            if len(refs) >= MAX_OBJECT_REFS:
                break
    return tuple(dict.fromkeys(refs))[:MAX_OBJECT_REFS]


def opt_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
