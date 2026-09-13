"""WS6 — config/secret migration projections from a legacy connector to a native
provider identity.

A :class:`~shared.integration_contracts.migration.MigrationProjection` declares
one fully-mapped legacy connector: which native identity it maps to, how legacy
config and secret keys map onto native fields, and the target credential ref
(``provider:{tenant}:{identity}``). This module owns the engine plus the Shopify
mapping (the only legacy connector with a native plugin built on this runtime).

**Honest scope** — the engine + Shopify ship; every other provider family is a
declared table row, explicitly marked unbuilt:

* ``project_connection`` raises :class:`ProjectionUnavailable` for any family
  with no built mapping (never fabricates a projection for an unbuilt family).
* ``list_projectable`` returns :class:`ProjectionCandidate` rows for every known
  family, with ``native_identity=None`` / ``requires_manual_mapping=True`` for
  the unbuilt ones.

**Refs-only, fail-closed invariants**:

* No plaintext anywhere. Callers pass a credential *ref* (never a secret);
  ``apply_projection`` reveals the legacy structured credential only through the
  auditable ``to_plaintext_dict`` seam, extracts ONLY the mapped fields, and
  re-wraps them as ``SecretStr`` before storing.
* Any tenant-supplied host in migrated config passes
  :func:`validated_https_host <shared.security.ssrf.validated_https_host>` with a
  fixed provider allowlist (S1) or the projection fails closed.
* A missing / unresolvable legacy credential or a missing mapped secret field
  fails closed with a typed error — a partial credential is never stored
  silently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import SecretStr

from shared.common.common import utc_now
from shared.credentials.types import (
    ApiKeyWebhookSecretCredential,
    StructuredCredential,
    to_plaintext_dict,
)
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.migration import MigrationProjection, ProjectionCandidate
from shared.security.ssrf import validated_https_host

from services.provider_runtime.errors import (
    CredentialMissing,
    ProviderRuntimeError,
)


def _now_iso() -> str:
    """Current UTC time in ISO-8601 form (caller-supplied timestamps)."""
    return utc_now().isoformat()


class ProjectionUnavailable(ProviderRuntimeError):
    """No built native mapping exists for the connector type (or it is unknown).

    ``safe_message`` names only the connector type — never legacy values.
    """


class ProjectionInvalid(ProviderRuntimeError):
    """Legacy config/secret input fails the projection's fail-closed validation.

    ``safe_message`` is generic; no raw legacy input or secret text is echoed.
    """


@dataclass(frozen=True)
class _FamilyMapping:
    """One connector family's native projection declaration (engine table row)."""

    native_identity: str
    credential_type: Literal["api_key_webhook_secret", "api_key"]
    config_field_map: tuple[tuple[str, str], ...] = ()
    secret_field_map: tuple[tuple[str, str], ...] = ()
    confidence: Literal["high", "medium", "low"] = "low"
    built: bool = False
    notes: str = ""
    #: legacy config key -> fixed host allow-suffixes (S1). Only host-type keys
    #: that require the SSRF gate appear here.
    host_config_suffixes: dict[str, tuple[str, ...]] = field(default_factory=dict)


# ── Engine table ────────────────────────────────────────────────────────────

# Shopify is the ONLY built mapping — it is the only legacy connector with a
# native plugin registered on this runtime (services.providers.shopify). The six
# provider families under Team G's build are declared as unbuilt table rows so
# operators see them as projectable-with-manual-mapping, never as migrated.
_FIELD_MAP: dict[str, _FamilyMapping] = {
    "shopify": _FamilyMapping(
        native_identity="shopify.admin.orders_read",
        credential_type="api_key_webhook_secret",
        config_field_map=(("shop_domain", "shop_domain"),),
        secret_field_map=(
            ("api_key", "api_key"),
            ("webhook_signing_secret", "webhook_secret"),
        ),
        confidence="medium",
        built=True,
        host_config_suffixes={"shop_domain": ("myshopify.com",)},
        notes=(
            "legacy shopify credentials carry no 'password'/'shop_access_token' "
            "field; the migrated connection may require manual credential "
            "completion for the native Basic-auth surface"
        ),
    ),
    "woocommerce": _FamilyMapping(
        native_identity="woocommerce.admin.orders_read",
        credential_type="api_key",
        notes="unbuilt — native plugin pending (Team G)",
    ),
    "etsy": _FamilyMapping(
        native_identity="etsy.admin.orders_read",
        credential_type="api_key",
        notes="unbuilt — native plugin pending (Team G)",
    ),
    "amazon": _FamilyMapping(
        native_identity="amazon.admin.orders_read",
        credential_type="api_key",
        notes="unbuilt — native plugin pending (Team G)",
    ),
    "ebay": _FamilyMapping(
        native_identity="ebay.admin.orders_read",
        credential_type="api_key",
        notes="unbuilt — native plugin pending (Team G)",
    ),
    "walmart": _FamilyMapping(
        native_identity="walmart.admin.orders_read",
        credential_type="api_key",
        notes="unbuilt — native plugin pending (Team G)",
    ),
    "tiktok": _FamilyMapping(
        native_identity="tiktok.admin.orders_read",
        credential_type="api_key",
        notes="unbuilt — native plugin pending (Team G)",
    ),
}

#: Connector families the engine knows about (ordered, stable for list_projectable).
_KNOWN_FAMILIES: tuple[str, ...] = tuple(_FIELD_MAP.keys())

#: Fixed Shopify host allowlist (S1) — real admin hosts are always *.myshopify.com.
_SHOPIFY_HOST_SUFFIXES = ("myshopify.com",)


def _mapping(connector_type: str) -> Optional[_FamilyMapping]:
    return _FIELD_MAP.get(connector_type)


def project_connection(
    tenant_id: str,
    connector_type: str,
    legacy_config: dict[str, Any],
    legacy_secret_ref: str,
) -> MigrationProjection:
    """Project one legacy connector onto a :class:`MigrationProjection`.

    Fail-closed: an unknown/unbuilt family raises :class:`ProjectionUnavailable`;
    a missing mapped config key or an invalid tenant-supplied host raises
    :class:`ProjectionInvalid`. ``legacy_secret_ref`` must be a non-empty,
    tenant-namespaced credential *ref* — plaintext secrets are never accepted
    here (refs-only contract).
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ProjectionInvalid("a non-empty tenant_id is required")
    mapping = _mapping(connector_type)
    if mapping is None:
        raise ProjectionUnavailable(
            f"no migration mapping exists for connector type {connector_type!r}"
        )
    if not mapping.built:
        raise ProjectionUnavailable(
            f"connector type {connector_type!r} has no built native migration "
            "mapping (manual mapping required)"
        )
    if not isinstance(legacy_config, dict):
        raise ProjectionInvalid("legacy_config must be a mapping")
    _validate_ref(legacy_secret_ref)
    _validate_legacy_config(mapping, legacy_config)

    return MigrationProjection(
        connector_type=connector_type,
        native_identity=mapping.native_identity,
        config_field_map={legacy: native for legacy, native in mapping.config_field_map},
        secret_field_map={legacy: native for legacy, native in mapping.secret_field_map},
        credential_ref_target=_credential_ref_target(tenant_id, mapping.native_identity),
        confidence=mapping.confidence,
        notes=mapping.notes,
    )


async def apply_projection(
    tenant_id: str,
    connector_type: str,
    legacy_config: dict[str, Any],
    legacy_secret_ref: str,
    *,
    broker: Any = None,
    connections: Any = None,
) -> Any:
    """Store the migrated structured credential and create the native connection.

    Returns the persisted :class:`~services.provider_runtime.connection.ProviderConnection`
    carrying ONLY a ``credential_ref`` (never secret material). Refs-only: the
    legacy secret is revealed via the auditable ``to_plaintext_dict`` seam, only
    the mapped fields are extracted, and they are re-wrapped as ``SecretStr``.
    A missing/unresolvable legacy credential or a missing mapped secret field
    fails closed with :class:`CredentialMissing`.
    """
    projection = project_connection(tenant_id, connector_type, legacy_config, legacy_secret_ref)
    mapping = _mapping(connector_type)
    assert mapping is not None  # project_connection already guaranteed built

    from services.provider_runtime.credential_broker import CredentialBroker
    from services.provider_runtime.connection import (
        ProviderConnection,
        ProviderConnectionRepository,
    )

    broker = broker if broker is not None else CredentialBroker()
    connections = (
        connections
        if connections is not None
        else ProviderConnectionRepository()
    )

    legacy_credential = await broker.resolve(tenant_id, legacy_secret_ref)
    if legacy_credential is None:
        raise CredentialMissing(
            f"legacy credential ref for {connector_type!r} did not resolve"
        )

    secret_values = _extract_secret_values(legacy_credential, mapping.secret_field_map)
    missing = [
        native for (legacy, native) in mapping.secret_field_map
        if native not in secret_values
    ]
    if missing:
        # Never name secret fields in a tenant-facing message with their values;
        # a generic classification is honest and leak-free.
        raise CredentialMissing(
            f"legacy credential for {connector_type!r} is missing mapped secret fields"
        )

    native_credential = _build_native_credential(mapping.credential_type, secret_values)
    ref = broker.provider_ref(tenant_id, projection.native_identity)
    await broker.store(tenant_id, ref, native_credential)

    config: dict[str, Any] = {}
    for legacy_key, native_field in mapping.config_field_map:
        config[native_field] = _normalized_config_value(mapping, legacy_key, legacy_config)

    now = _now_iso()
    connection = ProviderConnection(
        connection_id=f"conn_{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        provider_identity=projection.native_identity,
        display_name=f"{connector_type} (migrated)",
        state=ConnectionState.CREDENTIALS_RECEIVED,
        credential_ref=ref,
        config=config,
        created_at=now,
        updated_at=now,
    )
    await connections.upsert(connection)
    return connection


async def list_projectable(
    tenant_id: str,
    *,
    connections: Any = None,
) -> list[ProjectionCandidate]:
    """List every known connector family as a projectable candidate.

    Built families carry their native identity and confidence;
    ``requires_manual_mapping=True`` families carry ``native_identity=None``.
    Families the tenant has already migrated (an existing ``ProviderConnection``
    for the native identity) are excluded — a tenant never sees a duplicate
    migration target.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ProjectionInvalid("a non-empty tenant_id is required")

    if connections is None:
        from services.provider_runtime.connection import ProviderConnectionRepository

        connections = ProviderConnectionRepository()
    migrated_identities: set[str] = set()
    try:
        for existing in await connections.list_for_tenant(tenant_id, limit=1000):
            migrated_identities.add(getattr(existing, "provider_identity", ""))
    except Exception:  # pragma: no cover - best-effort tenant read
        pass

    candidates: list[ProjectionCandidate] = []
    for connector_type in _KNOWN_FAMILIES:
        mapping = _mapping(connector_type)
        assert mapping is not None
        if mapping.built and mapping.native_identity in migrated_identities:
            continue
        candidates.append(
            ProjectionCandidate(
                connector_type=connector_type,
                native_identity=mapping.native_identity if mapping.built else None,
                confidence=mapping.confidence if mapping.built else "",
                requires_manual_mapping=not mapping.built,
            )
        )
    return candidates


# ── Internals ───────────────────────────────────────────────────────────────


def _credential_ref_target(tenant_id: str, native_identity: str) -> str:
    """``provider:{tenant}:{identity}`` — the target ref, never a secret."""
    from services.provider_runtime.credential_broker import CredentialBroker

    return CredentialBroker().provider_ref(tenant_id, native_identity)


def _validate_ref(legacy_secret_ref: str) -> None:
    """Fail closed unless the caller passed a non-empty, tenant-namespaced ref.

    Refs are opaque, colon-separated, tenant-scoped strings (e.g.
    ``legacy:{tenant}:{identity}`` / ``provider:{tenant}:{identity}``). A
    plaintext secret is never a valid ref here.
    """
    if not isinstance(legacy_secret_ref, str) or not legacy_secret_ref.strip():
        raise ProjectionInvalid("a non-empty legacy secret ref is required")
    if ":" not in legacy_secret_ref:
        raise ProjectionInvalid(
            "legacy_secret_ref must be a tenant-namespaced credential ref"
        )


def _validate_legacy_config(mapping: _FamilyMapping, legacy_config: dict[str, Any]) -> None:
    """Fail closed on missing mapped keys or invalid tenant-supplied hosts."""
    for legacy_key, _native in mapping.config_field_map:
        value = legacy_config.get(legacy_key)
        if value is None or str(value).strip() == "":
            raise ProjectionInvalid(
                f"legacy config is missing required key {legacy_key!r}"
            )
        suffixes = mapping.host_config_suffixes.get(legacy_key)
        if suffixes and validated_https_host(str(value), allow_suffixes=suffixes) is None:
            raise ProjectionInvalid("legacy config carries an invalid provider host")


def _normalized_config_value(
    mapping: _FamilyMapping, legacy_key: str, legacy_config: dict[str, Any]
) -> Any:
    """Normalize a mapped config value through the S1 SSRF gate when host-type."""
    raw = legacy_config.get(legacy_key)
    suffixes = mapping.host_config_suffixes.get(legacy_key)
    if suffixes:
        normalized = validated_https_host(str(raw), allow_suffixes=suffixes)
        if normalized is None:
            raise ProjectionInvalid("legacy config carries an invalid provider host")
        return normalized
    return raw


def _find_legacy_secret(
    plain: dict[str, Any], legacy_key: str, native_field: str
) -> Optional[str]:
    """Resolve one mapped legacy secret field from a revealed credential dict.

    Handles both the flat reveal (a single shaped credential whose own field
    names match the legacy keys at the top level) and the legacy
    ``MultiCredential`` shape, where named sub-credentials nest under
    ``credentials[...]`` and their secret values live inside each sub-dict.

    Fail-closed: a value is only accepted when a scalar field is uniquely named
    after the legacy key, the native field, or (inside a ``MultiCredential``) a
    sub-credential field named after the legacy key or native field. When a
    sub-credential exposes multiple scalar secrets and none is unambiguously the
    mapped field, ``None`` is returned — the caller fails the migration rather
    than guess a secret.
    """
    value = plain.get(legacy_key)
    if isinstance(value, str) and value:
        return value
    # A flat shaped credential (e.g. api_key_webhook_secret) may reveal the
    # secret under its own native field name rather than the legacy key; accept
    # a uniquely-named scalar without guessing among multiple values.
    value = plain.get(native_field)
    if isinstance(value, str) and value:
        return value

    nested = plain.get("credentials")
    if not isinstance(nested, dict):
        return None
    sub = nested.get(legacy_key)
    if isinstance(sub, str) and sub:
        return sub
    if not isinstance(sub, dict):
        return None
    # A sub-credential: accept the scalar uniquely named after the legacy key or
    # the native field. Never fall back to "the first secret" — ambiguous sub-
    # credentials fail closed.
    for candidate_name in (legacy_key, native_field):
        candidate = sub.get(candidate_name)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _extract_secret_values(
    legacy_credential: StructuredCredential,
    secret_field_map: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    """Reveal ONLY the mapped legacy secret fields; re-wrap happens downstream.

    The revealed dict is never logged, returned, or stored — it is a local
    intermediate that lives only for the migration re-wrap.
    """
    plain = to_plaintext_dict(legacy_credential)
    values: dict[str, str] = {}
    for legacy_key, native_field in secret_field_map:
        value = _find_legacy_secret(plain, legacy_key, native_field)
        if value is not None:
            values[native_field] = value
    return values


def _build_native_credential(
    credential_type: str, secret_values: dict[str, str]
) -> StructuredCredential:
    """Build the native StructuredCredential from mapped secret values (SecretStr)."""
    if credential_type == "api_key_webhook_secret":
        return ApiKeyWebhookSecretCredential(
            api_key=SecretStr(secret_values.get("api_key", "")),
            webhook_secret=SecretStr(secret_values.get("webhook_secret", "")),
        )
    if credential_type == "api_key":
        from shared.credentials.types import ApiKeyCredential

        return ApiKeyCredential(api_key=SecretStr(secret_values.get("api_key", "")))
    raise ProjectionUnavailable(
        f"unknown native credential type {credential_type!r}"
    )


__all__ = [
    "ProjectionInvalid",
    "ProjectionUnavailable",
    "apply_projection",
    "list_projectable",
    "project_connection",
]
