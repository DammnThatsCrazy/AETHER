"""Durable canonical IDs for provider-owned, non-identity source objects.

The key omits connection/integration IDs so reconnecting the same verified
provider account reuses its object IDs. Source account and native object IDs
are HMACed under the existing tenant-scoped identity hashing key; raw values
are never persisted in these tables or logged. Every read and write verifies
the account against UPR's selected ProviderAccountRecord and connection.

This repository only issues non-identity object IDs. People, customers,
devices, agents, and account identities belong to SourceIdentityRegistry.
The local fallback follows the existing repository convention; non-local
deployments require PostgreSQL and IDENTITY_HASH_KEY and fail closed otherwise.
The HMAC key must remain pinned until a reviewed key-rotation crosswalk exists.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
import unicodedata
from datetime import datetime, timezone
from typing import Literal

from repositories.repos import get_pool
from services.identity.hashing import hash_value
from services.provider_runtime.acquisition import ProviderAccountRepository
from services.provider_runtime.connection import ProviderConnectionRepository
from shared.integration_contracts.source_objects import SourceAccountRef, SourceObjectRef


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS provider_object_refs (
    canonical_object_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider_family TEXT NOT NULL,
    source_account_realm TEXT NOT NULL CHECK (source_account_realm IN ('live', 'test')),
    source_account_hash TEXT NOT NULL,
    source_object_type TEXT NOT NULL,
    source_object_hash TEXT NOT NULL,
    account_verification_ref_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_provider_object_source UNIQUE (
        tenant_id, provider_family, source_account_realm, source_account_hash,
        source_object_type, source_object_hash
    ),
    CONSTRAINT uq_provider_object_account_scope UNIQUE (
        canonical_object_id, tenant_id, provider_family, source_account_realm,
        source_account_hash
    )
);
CREATE TABLE IF NOT EXISTS provider_object_aliases (
    alias_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider_family TEXT NOT NULL,
    source_account_realm TEXT NOT NULL CHECK (source_account_realm IN ('live', 'test')),
    source_account_hash TEXT NOT NULL,
    alias_namespace TEXT NOT NULL,
    alias_kind TEXT NOT NULL,
    alias_hash TEXT NOT NULL,
    canonical_object_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN (
        'legacy_migration', 'verified_reconnect', 'source_id_change',
        'schema_upgrade', 'operator_correction'
    )),
    evidence_ref TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_provider_object_alias_validity CHECK (
        valid_to IS NULL OR valid_to > valid_from
    ),
    CONSTRAINT uq_provider_object_alias UNIQUE (
        tenant_id, provider_family, source_account_realm, source_account_hash,
        alias_namespace, alias_kind, alias_hash
    ),
    CONSTRAINT fk_provider_object_alias_scope FOREIGN KEY (
        canonical_object_id, tenant_id, provider_family, source_account_realm,
        source_account_hash
    ) REFERENCES provider_object_refs (
        canonical_object_id, tenant_id, provider_family, source_account_realm,
        source_account_hash
    ) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_provider_object_alias_target
    ON provider_object_aliases (tenant_id, canonical_object_id);
"""


AliasReason = Literal[
    "legacy_migration",
    "verified_reconnect",
    "source_id_change",
    "schema_upgrade",
    "operator_correction",
]
_ALIAS_TOKEN = re.compile(r"^[a-z][a-z0-9_]*$")


class AccountEvidenceInvalid(ValueError):
    """The asserted immutable account and connection evidence did not match."""


class ObjectIdCollision(RuntimeError):
    """UUIDv4 candidate collided independently of the source tuple."""


class ObjectAliasConflict(ValueError):
    """An alias already names another object, or its target is out of scope."""


_LOCAL_OBJECTS: dict[tuple[str, ...], str] = {}
_LOCAL_ALIASES: dict[tuple[str, ...], dict] = {}
_LOCAL_LOCK = asyncio.Lock()


def reset_object_ref_local_stores() -> None:
    """Clear local-only mapping state between focused tests."""
    _LOCAL_OBJECTS.clear()
    _LOCAL_ALIASES.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_object_id() -> str:
    return str(uuid.uuid4())


def _is_local() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _require_hash_key() -> None:
    if (not _is_local() or os.getenv("DATABASE_URL")) and not os.getenv("IDENTITY_HASH_KEY"):
        raise RuntimeError("IDENTITY_HASH_KEY is required for provider object mapping")


def _account_hash(source: SourceAccountRef) -> str:
    return hash_value(
        source.source_account_key,
        scope=f"provider_object_account:{source.tenant_id}:{source.provider_family}:{source.source_account_realm}",
    )


def _object_hash(source: SourceObjectRef) -> str:
    return hash_value(
        source.source_object_id,
        scope=(
            f"provider_object_id:{source.tenant_id}:{source.provider_family}:"
            f"{source.source_account_realm}:{_account_hash(source)}:{source.source_object_type}"
        ),
    )


def _verification_hash(source: SourceAccountRef) -> str:
    return hash_value(
        source.account_verification_ref,
        scope=f"provider_object_evidence:{source.tenant_id}:{source.provider_family}",
    )


def _object_scope(source: SourceObjectRef) -> tuple[str, ...]:
    return (
        source.tenant_id,
        source.provider_family,
        source.source_account_realm,
        _account_hash(source),
        source.source_object_type,
        _object_hash(source),
    )


def _alias_scope(
    source: SourceAccountRef, namespace: str, kind: str, value: str
) -> tuple[str, ...]:
    digest = hash_value(
        unicodedata.normalize("NFC", value),
        scope=(
            f"provider_object_alias:{source.tenant_id}:{source.provider_family}:"
            f"{source.source_account_realm}:{_account_hash(source)}:{namespace}:{kind}"
        ),
    )
    return (
        source.tenant_id,
        source.provider_family,
        source.source_account_realm,
        _account_hash(source),
        namespace,
        kind,
        digest,
    )


def _validate_alias_input(namespace: str, kind: str, value: str) -> None:
    if not _ALIAS_TOKEN.fullmatch(namespace) or not _ALIAS_TOKEN.fullmatch(kind):
        raise ValueError("alias namespace and kind must be stable lowercase tokens")
    if not value.strip():
        raise ValueError("alias value must be nonblank")


class ProviderObjectRefRepository:
    """Atomic source-object mapping with tenant/account-scoped alias lookup."""

    def __init__(self, *, accounts=None, connections=None) -> None:
        self._accounts = accounts if accounts is not None else ProviderAccountRepository()
        self._connections = (
            connections if connections is not None else ProviderConnectionRepository()
        )
        self._pool = None
        self._table_ensured = False

    async def _ensure(self):
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is None:
            if not _is_local():
                raise RuntimeError("PostgreSQL is required for provider object mapping")
            return None
        if not self._table_ensured:
            # Serialize concurrent first-use DDL across worker processes.
            # IF NOT EXISTS alone can still race while PostgreSQL registers a
            # newly-created relation in pg_class.
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                        "aether.provider_object_refs.ensure_schema",
                    )
                    await conn.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    async def _verify_account(self, source: SourceAccountRef) -> None:
        """Require live-discovered immutable account evidence from existing UPR."""
        _require_hash_key()
        account = await self._accounts.find(source.account_verification_ref)
        if account is None:
            raise AccountEvidenceInvalid("provider account evidence is missing")
        connection = await self._connections.find(account.connection_id)
        if connection is None:
            raise AccountEvidenceInvalid("provider connection evidence is missing")
        selected_prefix = f"{connection.connection_id}:"
        selected_id = (
            account.account_id[len(selected_prefix) :]
            if account.account_id.startswith(selected_prefix)
            else ""
        )
        if not all(
            (
                account.tenant_id == source.tenant_id,
                connection.tenant_id == source.tenant_id,
                account.provider_identity == source.provider_identity,
                connection.provider_identity == source.provider_identity,
                bool(connection.last_verified_at),
                bool(selected_id) and selected_id in connection.selected_accounts,
                bool(account.external_id) and account.external_id == source.source_account_key,
                account.metadata.get("source_account_realm") == source.source_account_realm,
            )
        ):
            raise AccountEvidenceInvalid("provider account scope is not verified")

    async def lookup(self, source: SourceObjectRef) -> str | None:
        """Read an existing mapping after account verification; never create."""
        await self._verify_account(source)
        key = _object_scope(source)
        pool = await self._ensure()
        if pool is None:
            return _LOCAL_OBJECTS.get(key)
        row = await pool.fetchrow(
            "SELECT canonical_object_id FROM provider_object_refs WHERE "
            "tenant_id=$1 AND provider_family=$2 AND source_account_realm=$3 "
            "AND source_account_hash=$4 AND source_object_type=$5 AND source_object_hash=$6",
            *key,
        )
        return str(row["canonical_object_id"]) if row is not None else None

    async def resolve(self, source: SourceObjectRef) -> str:
        """Create a UUIDv4 mapping once, or reuse the atomically persisted ID."""
        await self._verify_account(source)
        key = _object_scope(source)
        pool = await self._ensure()
        if pool is None:
            async with _LOCAL_LOCK:
                existing = _LOCAL_OBJECTS.get(key)
                if existing is not None:
                    return existing
                for _ in range(3):
                    candidate = _new_object_id()
                    if candidate not in _LOCAL_OBJECTS.values():
                        _LOCAL_OBJECTS[key] = candidate
                        return candidate
                raise ObjectIdCollision("canonical object ID collision after three retries")

        for _ in range(3):
            candidate = _new_object_id()
            row = await pool.fetchrow(
                "INSERT INTO provider_object_refs ("
                "canonical_object_id, tenant_id, provider_family, source_account_realm, "
                "source_account_hash, source_object_type, source_object_hash, "
                "account_verification_ref_hash, created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
                "ON CONFLICT DO NOTHING RETURNING canonical_object_id",
                candidate,
                *key,
                _verification_hash(source),
                _now(),
            )
            if row is not None:
                return str(row["canonical_object_id"])
            existing = await pool.fetchrow(
                "SELECT canonical_object_id FROM provider_object_refs WHERE "
                "tenant_id=$1 AND provider_family=$2 AND source_account_realm=$3 "
                "AND source_account_hash=$4 AND source_object_type=$5 AND source_object_hash=$6",
                *key,
            )
            if existing is not None:
                return str(existing["canonical_object_id"])
        raise ObjectIdCollision("canonical object ID collision after three retries")

    async def add_alias(
        self,
        source: SourceAccountRef,
        *,
        canonical_object_id: str,
        namespace: str,
        kind: str,
        value: str,
        reason: AliasReason,
        evidence_ref: str,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> str:
        """Bind a scoped legacy/source alias to an existing object, immutably."""
        await self._verify_account(source)
        _validate_alias_input(namespace, kind, value)
        if reason not in AliasReason.__args__:
            raise ValueError("unreviewed alias reason")
        if not evidence_ref.strip():
            raise ValueError("alias evidence_ref must be nonblank")
        try:
            parsed_id = uuid.UUID(canonical_object_id)
        except ValueError as exc:
            raise ValueError("canonical_object_id must be UUIDv4") from exc
        if parsed_id.version != 4:
            raise ValueError("canonical_object_id must be UUIDv4")
        start = valid_from if valid_from is not None else _now()
        if start.tzinfo is None or (valid_to is not None and valid_to.tzinfo is None):
            raise ValueError("alias validity timestamps must be timezone-aware")
        if valid_to is not None and valid_to <= start:
            raise ValueError("alias valid_to must follow valid_from")
        alias_key = _alias_scope(source, namespace, kind, value)
        account_scope = alias_key[:4]
        pool = await self._ensure()
        if pool is None:
            async with _LOCAL_LOCK:
                if not any(
                    object_id == canonical_object_id and key[:4] == account_scope
                    for key, object_id in _LOCAL_OBJECTS.items()
                ):
                    raise ObjectAliasConflict("alias target is outside verified account scope")
                existing = _LOCAL_ALIASES.get(alias_key)
                if existing is not None:
                    if existing["canonical_object_id"] != canonical_object_id:
                        raise ObjectAliasConflict("alias already names another object")
                    return existing["alias_id"]
                alias_id = f"poalias_{uuid.uuid4().hex}"
                _LOCAL_ALIASES[alias_key] = {
                    "alias_id": alias_id,
                    "canonical_object_id": canonical_object_id,
                    "valid_from": start,
                    "valid_to": valid_to,
                }
                return alias_id

        target = await pool.fetchrow(
            "SELECT canonical_object_id FROM provider_object_refs WHERE "
            "canonical_object_id=$1 AND tenant_id=$2 AND provider_family=$3 "
            "AND source_account_realm=$4 AND source_account_hash=$5",
            canonical_object_id,
            *account_scope,
        )
        if target is None:
            raise ObjectAliasConflict("alias target is outside verified account scope")
        alias_id = f"poalias_{uuid.uuid4().hex}"
        row = await pool.fetchrow(
            "INSERT INTO provider_object_aliases ("
            "alias_id, tenant_id, provider_family, source_account_realm, "
            "source_account_hash, alias_namespace, alias_kind, alias_hash, "
            "canonical_object_id, reason, evidence_ref, valid_from, valid_to, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) "
            "ON CONFLICT DO NOTHING RETURNING alias_id, canonical_object_id",
            alias_id,
            *alias_key,
            canonical_object_id,
            reason,
            evidence_ref,
            start,
            valid_to,
            _now(),
        )
        if row is not None:
            return str(row["alias_id"])
        existing = await pool.fetchrow(
            "SELECT alias_id, canonical_object_id FROM provider_object_aliases WHERE "
            "tenant_id=$1 AND provider_family=$2 AND source_account_realm=$3 "
            "AND source_account_hash=$4 AND alias_namespace=$5 AND alias_kind=$6 "
            "AND alias_hash=$7",
            *alias_key,
        )
        if existing is None or str(existing["canonical_object_id"]) != canonical_object_id:
            raise ObjectAliasConflict("alias already names another object")
        return str(existing["alias_id"])

    async def resolve_alias(
        self,
        source: SourceAccountRef,
        *,
        namespace: str,
        kind: str,
        value: str,
        at: datetime | None = None,
    ) -> str | None:
        """Resolve only a verified tenant/account-scoped alias valid at ``at``."""
        await self._verify_account(source)
        _validate_alias_input(namespace, kind, value)
        instant = at if at is not None else _now()
        if instant.tzinfo is None:
            raise ValueError("alias lookup time must be timezone-aware")
        key = _alias_scope(source, namespace, kind, value)
        pool = await self._ensure()
        if pool is None:
            row = _LOCAL_ALIASES.get(key)
        else:
            fetched = await pool.fetchrow(
                "SELECT canonical_object_id, valid_from, valid_to FROM provider_object_aliases WHERE "
                "tenant_id=$1 AND provider_family=$2 AND source_account_realm=$3 "
                "AND source_account_hash=$4 AND alias_namespace=$5 AND alias_kind=$6 "
                "AND alias_hash=$7",
                *key,
            )
            row = dict(fetched) if fetched is not None else None
        if row is None:
            return None
        if instant < row["valid_from"] or (
            row["valid_to"] is not None and instant >= row["valid_to"]
        ):
            return None
        return str(row["canonical_object_id"])


__all__ = [
    "AccountEvidenceInvalid",
    "ObjectAliasConflict",
    "ObjectIdCollision",
    "ProviderObjectRefRepository",
    "SCHEMA_SQL",
    "reset_object_ref_local_stores",
]
