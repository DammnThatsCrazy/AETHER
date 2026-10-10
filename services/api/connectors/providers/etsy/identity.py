"""Customer identity extraction for durable Etsy receipt records."""

from __future__ import annotations

from typing import Any


def _usable(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"0", "unknown", "anonymous", "masked", "redacted"}:
        return None
    if any(marker in text for marker in ("*", "…", "...")):
        return None
    return text


def extract_customer_identity(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return buyer user id/email only; receipt and shop ids are never identities."""
    buyer = payload.get("buyer")
    buyer = buyer if isinstance(buyer, dict) else {}
    return _usable(buyer.get("user_id")), _usable(buyer.get("email")), None


__all__ = ["extract_customer_identity"]
