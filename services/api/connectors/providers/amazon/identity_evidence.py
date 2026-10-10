"""Customer identity fields exposed by Amazon Orders records.

Amazon SP-API order identifiers identify orders, not shoppers. The Orders
shape does not expose a stable Amazon customer ID, so this extractor accepts
only an actual buyer email and rejects Amazon relay addresses, redactions, and
masked values. Buyer names, seller IDs, PO numbers, and order IDs are not
identity evidence.
"""

from __future__ import annotations

import re
from typing import Any

from shared.integration_contracts.events import RawProviderRecord


_MASK_MARKERS = ("*", "...", "redacted", "masked", "private", "hidden")


def _usable_buyer_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip()
    lowered = email.lower()
    if not email or any(marker in lowered for marker in _MASK_MARKERS):
        return None
    if "@" not in email:
        return None
    local, domain = email.rsplit("@", 1)
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None
    # SP-API may expose a relay address that is scoped to Amazon messaging,
    # not a reusable customer identifier for cross-source stitching.
    if domain.lower().startswith("marketplace.amazon."):
        return None
    if not re.fullmatch(r"[^\s<>]+", local) or not re.fullmatch(r"[^\s<>]+", domain):
        return None
    return email


def extract_amazon_customer_evidence(
    record: RawProviderRecord,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(external_customer_id, email, phone)`` for an Amazon order.

    Amazon Orders exposes no stable customer ID or phone in this projection.
    The order ID, seller order ID, marketplace ID, and purchase order number
    are deliberately never promoted to shopper identity.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    buyer = payload.get("BuyerInfo")
    buyer = buyer if isinstance(buyer, dict) else {}
    return None, _usable_buyer_email(buyer.get("BuyerEmail")), None


__all__ = ["extract_amazon_customer_evidence"]
