"""Per-tenant LLM credential resolution models for the model-runtime.

ADR-008 D5 — credential/secret integration.

These models describe the outcome of resolving a provider credential at call
time through the ``shared.credentials.CredentialBackend`` abstraction. They are
deliberately secret-free: no API keys, bearer tokens, authorization headers, or
raw secret material ever appear in any field. ``masked_identifier`` carries only
a one-way ``"****" + last4(sha256(...))`` tag mirroring
``shared.credentials.types.masked_identifier``.

Security invariants (MUST NOT violate):
- No raw keys/secrets/authorization headers anywhere in these models.
- ``masked_identifier`` only ever carries the masked form (never the raw value);
  :func:`mask_identifier` is the sanctioned way to build it.
- :func:`assert_no_raw_secrets` is the guard used by resolvers (and by the
  ``masked_identifier`` field validator) to reject raw secret material before it
  can leak into a field that crosses trust boundaries.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

#: Substring patterns that flag raw secret material. Any string matching one of
#: these must never be assigned to a model field that crosses trust boundaries.
REDACT_PATTERNS: tuple[str, ...] = (
    "sk-",
    "AKIA",
    "Bearer ",
    "-----BEGIN",
    "key=",
    "secret=",
)

_REDACT_RE: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in REDACT_PATTERNS)


class CredentialResolverError(Exception):
    """Base error for credential resolution failures."""


class CredentialNotResolved(CredentialResolverError):
    """A provider credential could not be resolved at call time."""


class CredentialBackendUnavailable(CredentialResolverError):
    """The configured secret backend was unreachable or misconfigured."""


class CredentialUnsafe(CredentialResolverError):
    """Raised when raw secret-like material would leak into a masked field."""


def assert_no_raw_secrets(*values: str) -> None:
    """Reject raw secret material before it leaks into a model field.

    Raises :class:`CredentialUnsafe` if any value matches a
    :data:`REDACT_PATTERNS` substring. Resolvers call this before assigning
    provider-derived strings into ``masked_identifier`` or any other field that
    crosses trust boundaries.
    """
    for value in values:
        if not value:
            continue
        for pattern in _REDACT_RE:
            if pattern.search(value):
                raise CredentialUnsafe(
                    f"refusing value matching redact pattern {pattern.pattern!r}"
                )


def mask_identifier(secret: str) -> str:
    """Return ``"****" + last4(sha256(...))`` — never any secret bytes.

    Mirrors ``shared.credentials.types.masked_identifier``: the SHA-256 digest
    is one-way, and only its final four hex characters ever surface, so the
    output cannot reveal the raw value and never matches :data:`REDACT_PATTERNS`.
    """
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return f"****{digest[-4:]}"


class CredentialResolution(BaseModel):
    """Outcome of resolving a provider credential at call time (secret-free)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    tenant_id: str
    ref: str
    resolved: bool
    configured: bool  # provider can serve with the resolved credential
    masked_identifier: str | None = None
    source: Literal["env", "secret_backend", "none"] = "none"
    rotated_at: datetime | None = None
    expires_at: datetime | None = None
    reason: str = ""

    @field_validator("masked_identifier")
    @classmethod
    def _masked_must_not_leak(cls, value: str | None) -> str | None:
        if value is None:
            return value
        assert_no_raw_secrets(value)
        return value


class ResolverConfig(BaseModel):
    """Fail-closed configuration for the per-tenant credential resolver."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    backend: str = "in_memory"
    aws_region: str | None = None
    aws_secrets_prefix: str = "aether/credentials"
    rotation_grace_seconds: int = 300
    cache_ttl_seconds: int = 60

    @field_validator("cache_ttl_seconds")
    @classmethod
    def _cache_ttl_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("cache_ttl_seconds must be > 0")
        return value


class RotationDecision(BaseModel):
    """Whether a stored credential should be rotated, and why."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    should_rotate: bool
    reason: str = ""
    expires_at: datetime | None = None


__all__ = [
    "REDACT_PATTERNS",
    "CredentialBackendUnavailable",
    "CredentialNotResolved",
    "CredentialResolution",
    "CredentialResolverError",
    "CredentialUnsafe",
    "ResolverConfig",
    "RotationDecision",
    "assert_no_raw_secrets",
    "mask_identifier",
]
