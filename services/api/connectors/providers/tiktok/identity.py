"""Customer identity extraction for durable TikTok Shop order records."""

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
    """Return buyer UID only; order, seller, and shop ids are not buyer identity."""
    return _usable(payload.get("buyer_uid")), None, None


__all__ = ["extract_customer_identity"]
