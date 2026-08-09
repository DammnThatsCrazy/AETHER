"""Asyncpg-backed durability seam for the receipt/reconciliation ledger.

The payment-rail receipt and reconciliation ledgers live in the shared
``DurableStore`` KV abstraction (:mod:`shared.store`), which is Redis-backed in
deployment and in-memory in local mode. Redis is durable and multi-instance
safe, but it is not a queryable relational ledger: an operator cannot run a SQL
analytics query, and the KV TTL is the only lifecycle. This module is the
OPTIONAL Postgres seam that mirrors the ledgers into Alembic-owned tables so a
deployment that wants a true relational durability floor gets one.

Design rules (honest seams, never a silent partial state):
- OPT-IN: everything is gated behind ``settings.payment_rails.durability_seam_
  enabled`` (default False). Wiring the seam never changes a store's behavior.
- Source of truth stays the KV store. The seam is a best-effort MIRROR: a
  mirror failure is logged and returns ``False`` — it must never break the live
  webhook/repair path or raise out of a repository write.
- LOCAL mode (``AETHER_ENV=local``, no pool) is a no-op: the KV store IS the
  durability layer there. Staging/production use the shared asyncpg pool via
  :func:`repositories.repos.get_pool`.
- Missing tables degrade to a logged hint, not a crash: the seam is
  forward-deployable BEFORE the Alembic migration lands, and
  :func:`LedgerDurabilitySeam.migration_ddl` is the exact DDL the integration
  pass must carry in the migration.
- Every write is ``INSERT ... ON CONFLICT ... DO UPDATE`` keyed on the ledger's
  natural key (``receipt_id`` / ``(tenant_id, funding_session_id)`` /
  ``(tenant_id, provider)``) so replication is idempotent and re-runnable.

No secret or raw payload is ever written: the seam mirrors metadata columns
plus ``record_json``, and the receipt/reconciliation records are metadata-only
by construction (body hashes, never bodies; sanitized discrepancy triples).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from shared.logger.logger import get_logger
from shared.temporal.instant import coerce_utc_lenient, ensure_aware_utc

logger = get_logger("aether.payment_rails.durability")

#: Settings attribute on ``settings.payment_rails`` enabling the seam.
DURABILITY_SEAM_ENABLED_ATTR = "durability_seam_enabled"

#: Table names the seam mirrors into (migrationNeeds — DDL in ``migration_ddl``).
RECEIPT_TABLE = "payment_rail_receipts"
RECONCILIATION_TABLE = "payment_rail_reconciliation_records"
ACCOUNT_TABLE = "payment_rail_provider_accounts"


def durability_seam_enabled() -> bool:
    from config.settings import settings

    return bool(getattr(settings.payment_rails, DURABILITY_SEAM_ENABLED_ATTR, False))


def migration_ddl() -> dict[str, str]:
    """The exact DDL (per table) the Alembic migration must carry.

    Returned rather than executed so this module never creates or mutates schema
    — the integration pass authors the migration from this intent. Plain SQL, no
    secrets, no grants.
    """
    return {
        RECEIPT_TABLE: """
CREATE TABLE IF NOT EXISTS payment_rail_receipts (
    tenant_id           TEXT    NOT NULL,
    receipt_id          TEXT    NOT NULL PRIMARY KEY,
    provider            TEXT    NOT NULL,
    current_stage       TEXT    NOT NULL DEFAULT 'received',
    verification_state  TEXT,
    rejection_reason    TEXT,
    funding_session_id  TEXT,
    endpoint_id         TEXT,
    environment         TEXT,
    source              TEXT,
    processing_attempts INTEGER NOT NULL DEFAULT 0,
    repair_attempts     INTEGER NOT NULL DEFAULT 0,
    received_at         TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,
    record_json         JSONB   NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_payment_rail_receipts_tenant_updated
    ON payment_rail_receipts (tenant_id, updated_at DESC);
""",
        RECONCILIATION_TABLE: """
CREATE TABLE IF NOT EXISTS payment_rail_reconciliation_records (
    tenant_id          TEXT   NOT NULL,
    funding_session_id TEXT   NOT NULL,
    provider           TEXT   NOT NULL,
    state              TEXT   NOT NULL,
    last_source        TEXT,
    first_observed_at  TIMESTAMPTZ,
    last_checked_at    TIMESTAMPTZ,
    resolved_at        TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ,
    record_json        JSONB  NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, funding_session_id)
);
CREATE INDEX IF NOT EXISTS idx_payment_rail_recon_tenant_state
    ON payment_rail_reconciliation_records (tenant_id, state);
""",
        ACCOUNT_TABLE: """
CREATE TABLE IF NOT EXISTS payment_rail_provider_accounts (
    tenant_id            TEXT    NOT NULL,
    provider             TEXT    NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'not_configured',
    provider_poll_health TEXT,
    webhook_configured   BOOLEAN NOT NULL DEFAULT FALSE,
    polling_configured   BOOLEAN NOT NULL DEFAULT FALSE,
    environment          TEXT,
    last_poll_at         TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ,
    record_json          JSONB   NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, provider)
);
""",
    }


def _ts(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp to an aware datetime (TIMESTAMPTZ parameter)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    try:
        return ensure_aware_utc(parsed)
    except (TypeError, ValueError):
        return parsed if parsed.tzinfo else coerce_utc_lenient(parsed)


def _jsonb(value: Any) -> str:
    """Serialize a record to a JSONB parameter (never fails on non-JSON types)."""
    import json

    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return "{}"


class LedgerDurabilitySeam:
    """Best-effort Postgres mirror of the payment-rail KV ledgers.

    Methods are named for the ledger they mirror. Every method:
    - no-ops (returns ``False``) when the seam is disabled or no pool exists;
    - catches all exceptions and returns ``False`` (the KV store is the source
      of truth; the mirror must never break the live path);
    - logs a one-line migration hint when the target table is missing.
    """

    async def _acquire(self) -> Optional[Any]:
        if not durability_seam_enabled():
            return None
        try:
            from repositories.repos import get_pool

            return await get_pool()
        except Exception as exc:  # noqa: BLE001 — seam is best-effort
            logger.warning("payment_rail durability seam pool unavailable: %s", exc)
            return None

    @staticmethod
    def _missing_table(record: dict[str, Any], table: str, exc: Exception) -> bool:
        hint = " (migrationNeeds: create the table via LedgerDurabilitySeam.migration_ddl)"
        logger.warning(
            "payment_rail durability seam mirror to %s failed%s: %s",
            table, hint, exc,
        )
        return False

    async def mirror_receipt(self, record: dict[str, Any]) -> bool:
        """Mirror one provider receipt into ``payment_rail_receipts``."""
        pool = await self._acquire()
        if pool is None:
            return False
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {RECEIPT_TABLE}
                        (tenant_id, receipt_id, provider, current_stage,
                         verification_state, rejection_reason, funding_session_id,
                         endpoint_id, environment, source, processing_attempts,
                         repair_attempts, received_at, completed_at, updated_at,
                         record_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                    ON CONFLICT (receipt_id) DO UPDATE SET
                        current_stage = EXCLUDED.current_stage,
                        verification_state = EXCLUDED.verification_state,
                        rejection_reason = EXCLUDED.rejection_reason,
                        funding_session_id = EXCLUDED.funding_session_id,
                        processing_attempts = EXCLUDED.processing_attempts,
                        repair_attempts = EXCLUDED.repair_attempts,
                        completed_at = EXCLUDED.completed_at,
                        updated_at = EXCLUDED.updated_at,
                        record_json = EXCLUDED.record_json
                    """,
                    record.get("tenant_id"), record.get("receipt_id") or record.get("id"),
                    record.get("provider"), record.get("current_stage"),
                    record.get("verification_state"), record.get("rejection_reason"),
                    record.get("funding_session_id"), record.get("endpoint_id"),
                    record.get("environment"), record.get("source"),
                    int(record.get("processing_attempts") or 0),
                    int(record.get("repair_attempts") or 0),
                    _ts(record.get("received_at")), _ts(record.get("completed_at")),
                    _ts(record.get("updated_at") or record.get("last_attempted_at")),
                    _jsonb(record),
                )
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort mirror
            return self._missing_table(record, RECEIPT_TABLE, exc)

    async def mirror_reconciliation(self, record: dict[str, Any]) -> bool:
        """Mirror one reconciliation record into its durable table."""
        pool = await self._acquire()
        if pool is None:
            return False
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {RECONCILIATION_TABLE}
                        (tenant_id, funding_session_id, provider, state, last_source,
                         first_observed_at, last_checked_at, resolved_at, updated_at,
                         record_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (tenant_id, funding_session_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        last_source = EXCLUDED.last_source,
                        last_checked_at = EXCLUDED.last_checked_at,
                        resolved_at = EXCLUDED.resolved_at,
                        updated_at = EXCLUDED.updated_at,
                        record_json = EXCLUDED.record_json
                    """,
                    record.get("tenant_id"), record.get("funding_session_id"),
                    record.get("provider"), record.get("state"),
                    record.get("last_source"), _ts(record.get("first_observed_at")),
                    _ts(record.get("last_checked_at")), _ts(record.get("resolved_at")),
                    _ts(record.get("updated_at")), _jsonb(record),
                )
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort mirror
            return self._missing_table(record, RECONCILIATION_TABLE, exc)

    async def mirror_account(self, record: dict[str, Any]) -> bool:
        """Mirror one provider-account record into its durable table."""
        pool = await self._acquire()
        if pool is None:
            return False
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {ACCOUNT_TABLE}
                        (tenant_id, provider, status, provider_poll_health,
                         webhook_configured, polling_configured, environment,
                         last_poll_at, updated_at, record_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (tenant_id, provider) DO UPDATE SET
                        status = EXCLUDED.status,
                        provider_poll_health = EXCLUDED.provider_poll_health,
                        webhook_configured = EXCLUDED.webhook_configured,
                        polling_configured = EXCLUDED.polling_configured,
                        environment = EXCLUDED.environment,
                        last_poll_at = EXCLUDED.last_poll_at,
                        updated_at = EXCLUDED.updated_at,
                        record_json = EXCLUDED.record_json
                    """,
                    record.get("tenant_id"), record.get("provider"),
                    record.get("status"), record.get("provider_poll_health"),
                    bool(record.get("webhook_configured")),
                    bool(record.get("polling_configured")),
                    record.get("environment"), _ts(record.get("last_poll_at")),
                    _ts(record.get("updated_at")), _jsonb(record),
                )
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort mirror
            return self._missing_table(record, ACCOUNT_TABLE, exc)

    async def replicate(
        self,
        service: Any = None,
        *,
        limit: int = 2000,
        receipts: bool = True,
        reconciliations: bool = True,
        accounts: bool = True,
    ) -> dict[str, int]:
        """Bulk, idempotent replication of the KV ledgers into Postgres.

        One-shot catch-up (e.g. after the migration lands or after an operator
        enables the seam): reads each ledger from the shared stores and mirrors
        every row. Returns per-ledger success counters. Best-effort per row — a
        single bad record never aborts the sweep.
        """
        from services.integrations.providers.payment_rails.repository import (
            get_payment_rails_repositories,
        )

        service = service or _default_service()
        repos = getattr(service, "repos", None) or get_payment_rails_repositories()
        stats = {"receipts": 0, "reconciliations": 0, "accounts": 0}

        if receipts:
            rows = (await repos.receipts.list_all())[: max(1, min(limit, 5000))]
            for row in rows:
                if await self.mirror_receipt(row):
                    stats["receipts"] += 1
        if reconciliations:
            rows = (await repos.reconciliation.list_all())[: max(1, min(limit, 5000))]
            for row in rows:
                if await self.mirror_reconciliation(row):
                    stats["reconciliations"] += 1
        if accounts:
            rows = (await repos.accounts.list_all())[: max(1, min(limit, 5000))]
            for row in rows:
                if await self.mirror_account(row):
                    stats["accounts"] += 1
        return stats


def _default_service() -> Any:
    from services.integrations.providers.payment_rails.service import (
        get_payment_rails_service,
    )

    return get_payment_rails_service()


#: Module-level singleton (same convention as the repos bundle).
_seam: Optional[LedgerDurabilitySeam] = None


def get_ledger_seam() -> LedgerDurabilitySeam:
    global _seam
    if _seam is None:
        _seam = LedgerDurabilitySeam()
    return _seam


__all__ = [
    "DURABILITY_SEAM_ENABLED_ATTR",
    "RECEIPT_TABLE",
    "RECONCILIATION_TABLE",
    "ACCOUNT_TABLE",
    "durability_seam_enabled",
    "migration_ddl",
    "LedgerDurabilitySeam",
    "get_ledger_seam",
]
