"""Customer identity fields exposed by eBay Fulfillment order records.

Only eBay's buyer username is a stable provider-scoped customer identifier in
the order shape. Registration names and postal address components are not
identity claims. A phone is accepted only when eBay exposes an unmasked phone
number in the buyer registration address.
"""

from __future__ import annotations

import re
from typing import Any

from shared.integration_contracts.events import RawProviderRecord


_MASK_MARKERS = ("*", "...", "redacted", "masked", "private", "hidden")


def _usable_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    lowered = clean.lower()
    if not clean or any(marker in lowered for marker in _MASK_MARKERS):
        return None
    return clean


def _usable_phone(value: Any) -> str | None:
    clean = _usable_value(value)
    if clean is None:
        return None
    # Reject alphabetic redaction forms (for example ``xxx-555-1212``) instead
    # of stripping their mask characters and accidentally accepting the tail.
    if not re.fullmatch(r"\+?[0-9().\-\s]+", clean):
        return None
    digits = re.sub(r"\D", "", clean)
    if not 7 <= len(digits) <= 15:
        return None
    return clean


def extract_ebay_customer_evidence(
    record: RawProviderRecord,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(external_customer_id, email, phone)`` for an eBay order.

    eBay's Fulfillment projection provides the buyer's provider username and
    may include ``buyerRegistrationAddress.primaryPhone.phoneNumber``. It does
    not supply buyer email in the supported shape. Order IDs and seller/account
    identifiers are never treated as shopper identities.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    buyer = payload.get("buyer")
    buyer = buyer if isinstance(buyer, dict) else {}
    username = _usable_value(buyer.get("username"))
    address = buyer.get("buyerRegistrationAddress")
    address = address if isinstance(address, dict) else {}
    phone_block = address.get("primaryPhone")
    phone_block = phone_block if isinstance(phone_block, dict) else {}
    phone = _usable_phone(phone_block.get("phoneNumber"))
    return username, None, phone


__all__ = ["extract_ebay_customer_evidence"]
