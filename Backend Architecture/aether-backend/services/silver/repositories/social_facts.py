"""Social Silver fact repositories — durable access to the six
``silver_social_*_facts`` tables written by the M3 Social Silver projectors
(``services/silver/projectors/social_*.py``).

Production: asyncpg against PostgreSQL. Local/test: in-memory module store
(same interface). This mirrors the established repository pattern of
``services/comms/repository.py::CommsFactsRepository`` and
``services/measurement/repositories/touchpoint_repo.py::TouchpointRepository``:
the ``SilverFactWriter`` special-cases these six tables exactly like it does
``silver_comms_facts`` / ``silver_campaign_touchpoint_facts``.

Idempotency is enforced by a first-write-wins ``(tenant_id, idempotency_key)``
write (PostgreSQL ``ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`` over
the partial unique index the migration declares ``WHERE idempotency_key IS NOT
NULL``; the in-memory fallback mirrors it with a setdefault-style dict). Rows
are filtered to the columns actually present, so the repositories accept a
superset of every projector's output: ephemeral ``_base_row`` keys that are not
persisted (``surface``, ``sequence_key``) never reach the INSERT.

Typed binding mirrors touchpoint_repo: JSONB columns are ``json.dumps``-encoded,
timestamp columns parsed to ``datetime``, and the NUMERIC columns (``value``,
``resolution_confidence``) are coerced to ``Decimal`` via ``str()`` — never
through ``float()`` — so no binary floating-point artifact reaches a NUMERIC
column and no Python ``str`` is sent where PostgreSQL expects ``timestamptz``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.silver.social_facts_repo")

# In-memory fallback (local/test only): table -> {local_key: row}. The
# local_key is tenant-scoped so one tenant's replay can never return another
# tenant's row (mirrors PostgreSQL's (tenant_id, idempotency_key) uniqueness).
_local_rows: dict[str, dict[str, dict[str, Any]]] = {}


def reset_local_stores() -> None:
    """Test helper — clears every in-memory social-fact fallback store."""
    _local_rows.clear()


def local_rows(table: str) -> list[dict[str, Any]]:
    """Test helper — the rows persisted in memory for one silver_social_*_facts table."""
    return [dict(row) for row in (_local_rows.get(table, {})).values()]


# ── Column contract (mirrors alembic/versions/20260904_social_silver_facts.py) ──

# BaseProjector._base_row ownership columns (minus ephemeral surface/
# sequence_key) + SocialSilver provenance columns. present on every row.
_COMMON_COLUMNS: tuple[str, ...] = (
    "fact_id", "tenant_id", "source_event_id", "source_event_type",
    "actor_id", "user_id", "anonymous_id", "org_id", "occurred_at",
    "received_at", "consent_snapshot_id", "privacy_class", "idempotency_key",
    "payload", "source_scope", "evidence_basis", "rights_ref",
    "provider_identity", "provider_record_ref",
)

_IDENTITY_DOMAIN_COLUMNS: tuple[str, ...] = (
    "social_identity_id", "canonical_entity_ref", "provider_account_id",
    "handle", "display_name", "canonical_url", "account_type",
    "verification_state", "platform_role", "provider_profile_created_at",
    "first_observed_at", "last_observed_at", "valid_from", "valid_to",
    "resolution_state", "resolution_confidence", "identity_evidence_refs",
)

_CONNECTION_DOMAIN_COLUMNS: tuple[str, ...] = (
    "source_social_identity_ref", "target_social_identity_ref",
    "connection_type", "directionality", "observed_at", "valid_from",
    "valid_to", "proof_level", "claim_type", "evidence_refs",
    "contradictory_evidence_refs",
)

_INTERACTION_DOMAIN_COLUMNS: tuple[str, ...] = (
    "interaction_id", "actor_social_identity_ref", "target_social_identity_ref",
    "content_ref", "parent_content_ref", "community_ref", "interaction_type",
    "observed_at", "machine_classification", "human_qualification",
    "semantic_ref", "campaign_ref", "incentive_context_ref", "evidence_refs",
)

_CONTENT_DOMAIN_COLUMNS: tuple[str, ...] = (
    "content_id", "author_social_identity_ref", "provider_content_id",
    "content_type", "provider_content_subtype", "parent_content_ref",
    "root_content_ref", "published_at", "edited_at", "deleted_at",
    "content_hash", "semantic_ref", "narrative_refs", "campaign_ref",
    "incentive_context_ref", "evidence_refs",
)

_COMMUNITY_DOMAIN_COLUMNS: tuple[str, ...] = (
    "membership_id", "social_identity_ref", "community_ref", "membership_role",
    "provider_membership_role", "valid_from", "valid_to", "observed_at",
    "evidence_refs",
)

_METRIC_DOMAIN_COLUMNS: tuple[str, ...] = (
    "metric_observation_id", "social_identity_ref", "metric_name", "value",
    "unit", "status", "metric_window", "population", "observed_at",
    "computation_ref", "quality", "evidence_refs",
)


def _merge(*parts: tuple[str, ...]) -> tuple[str, ...]:
    """Order-preserving concatenation without duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for column in part:
            if column not in seen:
                seen.add(column)
                out.append(column)
    return tuple(out)


# table -> ordered union of the shared columns + that table's domain columns.
_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "silver_social_identity_facts": _merge(
        _COMMON_COLUMNS, _IDENTITY_DOMAIN_COLUMNS),
    "silver_social_connection_facts": _merge(
        _COMMON_COLUMNS, _CONNECTION_DOMAIN_COLUMNS),
    "silver_social_interaction_facts": _merge(
        _COMMON_COLUMNS, _INTERACTION_DOMAIN_COLUMNS),
    "silver_social_content_facts": _merge(
        _COMMON_COLUMNS, _CONTENT_DOMAIN_COLUMNS),
    "silver_social_community_facts": _merge(
        _COMMON_COLUMNS, _COMMUNITY_DOMAIN_COLUMNS),
    "silver_social_metric_facts": _merge(
        _COMMON_COLUMNS, _METRIC_DOMAIN_COLUMNS),
}

_JSON_COLUMNS = frozenset({
    "payload", "identity_evidence_refs", "evidence_refs",
    "contradictory_evidence_refs", "narrative_refs", "metric_window",
})
_TIMESTAMP_COLUMNS = frozenset({
    "occurred_at", "received_at", "provider_profile_created_at",
    "first_observed_at", "last_observed_at", "valid_from", "valid_to",
    "observed_at", "published_at", "edited_at", "deleted_at",
})
# NUMERIC columns — never bound as a raw Python float/str. Mirrors touchpoint
# revenue_usd handling (see touchpoint_repo._MONEY_COLUMNS / _to_decimal).
_NUMERIC_COLUMNS = frozenset({"value", "resolution_confidence"})


def _parse_ts(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Coerce to Decimal via str() — never via float() — so no binary
    floating-point artifact reaches a NUMERIC column (Decimal(0.1) !=
    Decimal('0.1')). Mirrors touchpoint_repo._to_decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _db_value(column: str, value: Any) -> Any:
    if column in _JSON_COLUMNS:
        return json.dumps(value, default=str) if value is not None else None
    if column in _TIMESTAMP_COLUMNS:
        return _parse_ts(value)
    if column in _NUMERIC_COLUMNS:
        return _to_decimal(value)
    return value


class _BaseSocialFactsRepository:
    """Shared idempotent upsert over one ``silver_social_*_facts`` table.

    ``table`` is set by each concrete repository. All six share the durable
    first-write-wins semantics of the CommsFactsRepository, extended with the
    typed binding of TouchpointRepository so ISO timestamp strings and float
    numerics bind cleanly against the DDL's ``timestamptz`` / ``numeric``
    columns.
    """

    table: str = ""

    async def _pool(self):
        return await get_pool()

    async def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert or ignore on (tenant_id, idempotency_key) conflict — replay safe."""
        row.setdefault("fact_id", str(uuid4()))
        row.setdefault("received_at", datetime.now(timezone.utc).isoformat())
        row.setdefault("privacy_class", "behavioral")
        local_key = f"{row.get('tenant_id')}:{row.get('idempotency_key')}"

        pool = await self._pool()
        if pool is None:
            store = _local_rows.setdefault(self.table, {})
            existing = store.get(local_key)
            if existing is not None:
                # Idempotent local write — first write wins, mirroring DO NOTHING.
                return existing
            store[local_key] = dict(row)
            return row

        columns = _TABLE_COLUMNS[self.table]
        cols = [c for c in columns if c in row]
        if not cols:
            return row
        values = [_db_value(c, row[c]) for c in cols]
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.table} ({', '.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                *values,
            )
        return row


class SocialIdentityFactsRepository(_BaseSocialFactsRepository):
    """Durable storage over silver_social_identity_facts (social_identity_observed)."""
    table = "silver_social_identity_facts"


class SocialConnectionFactsRepository(_BaseSocialFactsRepository):
    """Durable storage over silver_social_connection_facts (social_connection_observed)."""
    table = "silver_social_connection_facts"


class SocialInteractionFactsRepository(_BaseSocialFactsRepository):
    """Durable storage over silver_social_interaction_facts (social_interaction_observed)."""
    table = "silver_social_interaction_facts"


class SocialContentFactsRepository(_BaseSocialFactsRepository):
    """Durable storage over silver_social_content_facts (social_content_observed)."""
    table = "silver_social_content_facts"


class SocialCommunityFactsRepository(_BaseSocialFactsRepository):
    """Durable storage over silver_social_community_facts (social_community_membership_observed)."""
    table = "silver_social_community_facts"


class SocialMetricFactsRepository(_BaseSocialFactsRepository):
    """Durable storage over silver_social_metric_facts (social_metric_observed)."""
    table = "silver_social_metric_facts"


# table name -> repository class. The SilverFactWriter uses this registry to
# route the six social tables onto the durable repository path.
SOCIAL_FACT_REPOSITORY_BY_TABLE: dict[str, type[_BaseSocialFactsRepository]] = {
    cls.table: cls
    for cls in (
        SocialIdentityFactsRepository,
        SocialConnectionFactsRepository,
        SocialInteractionFactsRepository,
        SocialContentFactsRepository,
        SocialCommunityFactsRepository,
        SocialMetricFactsRepository,
    )
}

__all__ = [
    "SOCIAL_FACT_REPOSITORY_BY_TABLE",
    "SocialIdentityFactsRepository",
    "SocialConnectionFactsRepository",
    "SocialInteractionFactsRepository",
    "SocialContentFactsRepository",
    "SocialCommunityFactsRepository",
    "SocialMetricFactsRepository",
    "local_rows",
    "reset_local_stores",
]
