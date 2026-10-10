"""Privacy boundary for persisted SDK acquisition evidence.

Verified referral tokens are bearer credentials. They may exist in memory
long enough to be verified, but Bronze and the transactional outbox persist
only their SHA-256 digest. Legacy/raw referrers are reduced to an origin plus a
one-way path fingerprint before durable ingestion.
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TOKEN_KEYS = frozenset({"aetherref", "referraltoken"})
_TOKEN_HASH_KEYS = frozenset({"referraltokenhash", "aetherrefhash"})
_REFERRER_KEYS = frozenset({"referrer", "referrerurl"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def sanitize_acquisition_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a persistence-safe deep copy of an SDK event payload."""

    sanitized = copy.deepcopy(payload)
    digests: list[str] = []
    _sanitize_mapping(sanitized, digests)

    if digests:
        context = sanitized.get("context")
        if not isinstance(context, dict):
            context = {}
            sanitized["context"] = context
        # The digest remains a bearer lookup value and is therefore kept only
        # on the internal event context, never copied into analytics facts.
        context["referralTokenHash"] = digests[0]
    return sanitized


def _sanitize_mapping(mapping: dict[str, Any], digests: list[str]) -> None:
    for key in list(mapping):
        value = mapping.get(key)
        normalized = _normalized_key(key)

        if normalized in _TOKEN_KEYS:
            mapping.pop(key, None)
            if value:
                digests.append(_token_hash(str(value)))
            continue

        if normalized in _TOKEN_HASH_KEYS:
            mapping.pop(key, None)
            digest = str(value or "").lower()
            if _DIGEST_RE.fullmatch(digest):
                digests.append(digest)
            continue

        if isinstance(value, (dict, list, tuple)):
            mapping[key] = _sanitize_nested(value, digests)
            continue
        if not isinstance(value, str) or not value:
            continue

        token = _token_from_url(value)
        if token:
            digests.append(_token_hash(token))
            value = _strip_referral_token(value)

        if normalized in _REFERRER_KEYS:
            origin, path_hash = _privacy_safe_referrer(value)
            mapping[key] = origin or None
            if path_hash:
                path_key = (
                    "referrer_path_hash"
                    if "_" in str(key)
                    else "referrerPathHash"
                )
                mapping.setdefault(path_key, path_hash)
        else:
            mapping[key] = value


def _sanitize_nested(value: Any, digests: list[str]) -> Any:
    """Recursively sanitize arbitrary JSON-like containers.

    SDK properties are intentionally open-ended and may contain nested arrays.
    Walking only dictionaries directly contained in the first list level would
    allow a bearer token to cross the persistence boundary inside a deeper
    list/tuple.  Preserve container shape while sanitizing every descendant.
    """

    if isinstance(value, dict):
        _sanitize_mapping(value, digests)
        return value
    if isinstance(value, list):
        return [_sanitize_nested(item, digests) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_nested(item, digests) for item in value)
    if isinstance(value, str) and value:
        token = _token_from_url(value)
        if token:
            digests.append(_token_hash(token))
            return _strip_referral_token(value)
    return value


def _normalized_key(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_from_url(value: str) -> str | None:
    try:
        query = value[1:] if value.startswith("?") else urlsplit(value).query
        for key, token in parse_qsl(query, keep_blank_values=True):
            if _normalized_key(key) == "aetherref" and token:
                return token
    except (TypeError, ValueError):
        return None
    return None


def _strip_referral_token(value: str) -> str:
    try:
        if value.startswith("?"):
            filtered = [
                (key, item)
                for key, item in parse_qsl(value[1:], keep_blank_values=True)
                if _normalized_key(key) != "aetherref"
            ]
            encoded = urlencode(filtered, doseq=True)
            return f"?{encoded}" if encoded else ""
        parsed = urlsplit(value)
        filtered = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if _normalized_key(key) != "aetherref"
        ]
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(filtered, doseq=True),
                parsed.fragment,
            )
        )
    except (TypeError, ValueError):
        return ""


def _privacy_safe_referrer(value: str) -> tuple[str, str | None]:
    try:
        candidate = value if "://" in value else f"https://{value}"
        parsed = urlsplit(candidate)
        domain = (parsed.hostname or "").strip(". ").lower()
        if domain.startswith("www."):
            domain = domain[4:]
        domain = domain.encode("idna").decode("ascii")[:253]
        if not domain:
            return "", None
        scheme = parsed.scheme.lower() if parsed.scheme.lower() in {"http", "https"} else "https"
        path_hash = None
        if parsed.path and parsed.path != "/":
            path_hash = hashlib.sha256(
                parsed.path.encode("utf-8", errors="ignore")
            ).hexdigest()[:24]
        return f"{scheme}://{domain}/", path_hash
    except (TypeError, ValueError, UnicodeError):
        return "", None
