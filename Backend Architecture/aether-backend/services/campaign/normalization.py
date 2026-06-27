"""Campaign evidence normalization utilities.

All normalization is deterministic and idempotent. Raw values are never
mutated in the database — normalization is applied only for lookup/matching.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from typing import Any


# Canonical platform identifiers accepted by Aether.
_PLATFORM_ALIASES: dict[str, str] = {
    "google": "google_ads",
    "google_ads": "google_ads",
    "google ads": "google_ads",
    "googleads": "google_ads",
    "adwords": "google_ads",
    "meta": "meta_ads",
    "meta_ads": "meta_ads",
    "facebook": "meta_ads",
    "facebook_ads": "meta_ads",
    "fb": "meta_ads",
    "instagram": "meta_ads",
    "tiktok": "tiktok_ads",
    "tiktok_ads": "tiktok_ads",
    "tiktok ads": "tiktok_ads",
    "linkedin": "linkedin_ads",
    "linkedin_ads": "linkedin_ads",
    "linkedin ads": "linkedin_ads",
    "x": "x_ads",
    "x_ads": "x_ads",
    "twitter": "x_ads",
    "twitter_ads": "x_ads",
    "reddit": "reddit_ads",
    "reddit_ads": "reddit_ads",
    "microsoft": "microsoft_ads",
    "microsoft_ads": "microsoft_ads",
    "bing": "microsoft_ads",
    "bing_ads": "microsoft_ads",
    "snapchat": "snapchat_ads",
    "snapchat_ads": "snapchat_ads",
    "pinterest": "pinterest_ads",
    "pinterest_ads": "pinterest_ads",
}


def normalize_platform(raw: str | None) -> str | None:
    """Return the canonical Aether platform identifier for a raw input."""
    if not raw:
        return None
    key = raw.strip().lower()
    return _PLATFORM_ALIASES.get(key, key)


def normalize_utm_value(raw: str | None) -> str | None:
    """Return a canonical UTM value for alias matching.

    Applies URL decoding, strips whitespace, lowercases. Does not alter
    special characters beyond those steps — the caller must not rely on
    this function to validate or sanitize user input for storage.
    """
    if raw is None:
        return None
    decoded = urllib.parse.unquote_plus(raw)
    return decoded.strip().lower() or None


def normalize_external_id(raw: str | None) -> str | None:
    """Normalize an external provider campaign ID for exact matching.

    External IDs are stored and matched verbatim after stripping leading/
    trailing whitespace. They are NOT lowercased because provider IDs can
    be case-sensitive (e.g. TikTok numeric strings, Meta UUID-like strings).
    """
    if raw is None:
        return None
    return raw.strip() or None


_EVIDENCE_HASH_FIELDS = (
    "platform",
    "external_account_id",
    "external_campaign_id",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_id",
    "landing_url",
)


def build_evidence_hash(tenant_id: str, evidence: dict[str, Any]) -> str:
    """Build a stable SHA-256 hex digest for deduplicating Mapping Review items.

    Only the fields that define evidence identity are included. Fields that
    vary per-event (timestamps, session IDs, user IDs) are excluded so that
    repeated identical unresolved evidence increments the same review item.
    """
    parts: dict[str, str | None] = {"tenant_id": tenant_id}
    for field in _EVIDENCE_HASH_FIELDS:
        val = evidence.get(field)
        parts[field] = normalize_utm_value(str(val)) if val is not None else None

    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def safe_text(value: Any, max_length: int = 2048) -> str | None:
    """Coerce a value to a bounded string for evidence storage."""
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_length] if text else None
