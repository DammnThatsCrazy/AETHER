"""Customer identity extraction for durable Walmart Marketplace orders."""

from __future__ import annotations

import re
from typing import Any


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _usable_email(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or any(marker in text for marker in ("*", "…", "...")):
        return None
    if text.lower() in {"unknown", "anonymous", "masked", "redacted"}:
        return None
    return text if _EMAIL.fullmatch(text) else None


def extract_customer_identity(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return only an unmasked customer email; Walmart order ids are not customers."""
    return None, _usable_email(payload.get("customerEmailId") or payload.get("customer_email_id")), None


__all__ = ["extract_customer_identity"]
