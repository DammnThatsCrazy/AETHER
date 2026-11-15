"""Correlation token key custody: parse configured keys, never log them."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from shared.integration_contracts.correlation_token import TokenVerifier, token_verifier

MIN_KEY_BYTES = 32


class CorrelationKeyError(ValueError):
    """Configured key material is unusable. The message never contains a secret."""


@dataclass(frozen=True)
class CorrelationKeyring:
    signing_key_id: str
    keys: Mapping[str, bytes]

    def secret(self, key_id: str) -> bytes:
        return self.keys[key_id]

    def verifier(self) -> TokenVerifier:
        return token_verifier(self.keys)


def _decode(secret_b64: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(secret_b64 + "=" * (-len(secret_b64) % 4))
    except (ValueError, TypeError) as exc:
        raise CorrelationKeyError("correlation token key is not base64url") from exc


def parse_keyring(entries: Iterable[str]) -> Optional[CorrelationKeyring]:
    """Parse ``key_id:base64url_secret`` entries; the first entry signs.

    Returns ``None`` when no keys are configured, so callers can report that
    token issuance is unavailable instead of failing the whole service.
    """
    keys: dict[str, bytes] = {}
    order: list[str] = []
    for raw in entries:
        entry = (raw or "").strip()
        if not entry:
            continue
        key_id, sep, secret_b64 = entry.partition(":")
        key_id = key_id.strip()
        if not sep or not key_id or not secret_b64.strip():
            raise CorrelationKeyError("correlation token keys must be key_id:base64url_secret")
        if key_id in keys:
            raise CorrelationKeyError(f"correlation token key {key_id!r} is listed twice")
        secret = _decode(secret_b64.strip())
        if len(secret) < MIN_KEY_BYTES:
            raise CorrelationKeyError(f"correlation token key {key_id!r} must decode to at least {MIN_KEY_BYTES} bytes")
        keys[key_id] = secret
        order.append(key_id)
    if not order:
        return None
    return CorrelationKeyring(signing_key_id=order[0], keys=keys)


def configured_keyring() -> Optional[CorrelationKeyring]:
    from config.settings import settings

    return parse_keyring(settings.agent_correlation.token_keys)
