"""Structured credential shapes for the provider-neutral credential platform.

Every secret-bearing field is a :class:`pydantic.SecretStr` so the value never
leaks through ``repr()``, ``model_dump()``, or ``model_dump_json()``. Plaintext
extraction is always explicit: a trusted resolver must call
``cred.<field>.get_secret_value()`` (or the reveal helpers here), which makes
every secret read auditable at the call site.

The public surface is a Pydantic v2 discriminated union
(:data:`StructuredCredential`) keyed on the ``type`` field. ``as_structured``
coerces a bare string into an :class:`ApiKeyCredential` and passes structured
values through unchanged.

Serialization for encryption at rest is deliberately NOT the default Pydantic
dump (which masks secrets). Use :func:`to_plaintext_dict` /
:func:`from_plaintext_dict`, which reveal secrets only for the encrypt/decrypt
seam and never for display.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter

from shared.temporal.instant import ensure_aware_utc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # Delegates naive-rejection + UTC normalization to the temporal kernel.
    return ensure_aware_utc(value)


class _CredBase(BaseModel):
    """Frozen base for every structured credential.

    Carries the optional ``expires_at`` window and a tz-safe ``is_expired``.
    """

    model_config = ConfigDict(frozen=True)

    expires_at: Optional[datetime] = None

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if self.expires_at is None:
            return False
        ref = _aware(now) if now is not None else _utc_now()
        return ref >= _aware(self.expires_at)


class ApiKeyCredential(_CredBase):
    type: Literal["api_key"] = "api_key"
    api_key: SecretStr


class ClientSecretCredential(_CredBase):
    type: Literal["client_secret"] = "client_secret"
    client_id: str
    client_secret: SecretStr


class OAuthTokenCredential(_CredBase):
    type: Literal["oauth_token"] = "oauth_token"
    access_token: SecretStr
    refresh_token: Optional[SecretStr] = None
    scope: list[str] = Field(default_factory=list)


class KeyIdSecretCredential(_CredBase):
    type: Literal["key_id_secret"] = "key_id_secret"
    key_id: str
    secret: SecretStr


class KeypairCredential(_CredBase):
    type: Literal["keypair"] = "keypair"
    public_key: str
    private_key: SecretStr


class ServiceAccountCredential(_CredBase):
    type: Literal["service_account"] = "service_account"
    service_account_json: SecretStr
    client_email: Optional[str] = None


class UsernameTokenCredential(_CredBase):
    type: Literal["username_token"] = "username_token"
    username: str
    token: SecretStr


class ApiKeyWebhookSecretCredential(_CredBase):
    type: Literal["api_key_webhook_secret"] = "api_key_webhook_secret"
    api_key: SecretStr
    webhook_secret: SecretStr


class MultiCredential(_CredBase):
    type: Literal["multi"] = "multi"
    credentials: dict[str, "StructuredCredential"]


# Discriminated union over every concrete shape. ``type`` is the discriminator.
StructuredCredential = Annotated[
    Union[
        ApiKeyCredential,
        ClientSecretCredential,
        OAuthTokenCredential,
        KeyIdSecretCredential,
        KeypairCredential,
        ServiceAccountCredential,
        UsernameTokenCredential,
        ApiKeyWebhookSecretCredential,
        MultiCredential,
    ],
    Field(discriminator="type"),
]

# Resolve the recursive forward reference inside MultiCredential now that the
# ``StructuredCredential`` alias exists in the module namespace.
MultiCredential.model_rebuild()

_ADAPTER: TypeAdapter[Any] = TypeAdapter(StructuredCredential)

# Non-secret display fields surfaced by ``masked_metadata`` when present. These
# are identifiers/scopes, never secret material.
_NON_SECRET_DISPLAY_FIELDS = (
    "client_id",
    "key_id",
    "scope",
    "client_email",
    "public_key",
    "username",
)


def as_structured(value: "StructuredCredential | str | dict[str, Any]") -> "StructuredCredential":
    """Coerce ``value`` into a :data:`StructuredCredential`.

    - a bare ``str`` becomes an :class:`ApiKeyCredential`
    - an existing structured credential is returned unchanged
    - a ``dict`` is validated through the discriminated union
    """
    if isinstance(value, _CredBase):
        return value  # type: ignore[return-value]
    if isinstance(value, str):
        return ApiKeyCredential(api_key=SecretStr(value))
    if isinstance(value, dict):
        return _ADAPTER.validate_python(value)
    raise TypeError(f"cannot coerce {type(value)!r} into a StructuredCredential")


def _reveal_value(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, _CredBase):
        return to_plaintext_dict(value)
    if isinstance(value, dict):
        return {k: _reveal_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_reveal_value(v) for v in value]
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    return value


def to_plaintext_dict(cred: "StructuredCredential") -> dict[str, Any]:
    """Reveal every secret into a plain JSON-serializable dict.

    This is the ONLY place secrets are unwrapped for persistence; the output is
    fed straight into the encryptor. Never log or display it.
    """
    return {name: _reveal_value(value) for name, value in dict(cred).items()}


def to_plaintext_json(cred: "StructuredCredential") -> str:
    return json.dumps(to_plaintext_dict(cred), separators=(",", ":"), sort_keys=True)


def from_plaintext_dict(data: dict[str, Any]) -> "StructuredCredential":
    """Rebuild a structured credential from a revealed dict (post-decrypt)."""
    return _ADAPTER.validate_python(data)


def from_plaintext_json(raw: str) -> "StructuredCredential":
    return from_plaintext_dict(json.loads(raw))


def _primary_secret_material(cred: "StructuredCredential") -> str:
    """Stable one-way input for the masked identifier hash.

    Uses the revealed plaintext JSON, hashed one-way — the digest is not
    reversible, and only four hex characters of it ever surface.
    """
    return to_plaintext_json(cred)


def masked_identifier(cred: "StructuredCredential") -> str:
    """Return ``"****" + last4(sha256(...))`` — never any secret bytes."""
    digest = hashlib.sha256(_primary_secret_material(cred).encode("utf-8")).hexdigest()
    return f"****{digest[-4:]}"


def masked_metadata(cred: "StructuredCredential") -> dict[str, Any]:
    """Non-secret display metadata for a credential (safe for API/logs)."""
    md: dict[str, Any] = {
        "credential_type": cred.type,
        "masked_identifier": masked_identifier(cred),
    }
    if cred.expires_at is not None:
        md["expires_at"] = _aware(cred.expires_at).isoformat()
    for attr in _NON_SECRET_DISPLAY_FIELDS:
        if hasattr(cred, attr):
            value = getattr(cred, attr)
            if value:
                md[attr] = value
    if isinstance(cred, MultiCredential):
        md["members"] = {k: v.type for k, v in cred.credentials.items()}
    return md


__all__ = [
    "ApiKeyCredential",
    "ApiKeyWebhookSecretCredential",
    "ClientSecretCredential",
    "KeyIdSecretCredential",
    "KeypairCredential",
    "MultiCredential",
    "OAuthTokenCredential",
    "ServiceAccountCredential",
    "StructuredCredential",
    "UsernameTokenCredential",
    "as_structured",
    "from_plaintext_dict",
    "from_plaintext_json",
    "masked_identifier",
    "masked_metadata",
    "to_plaintext_dict",
    "to_plaintext_json",
]
