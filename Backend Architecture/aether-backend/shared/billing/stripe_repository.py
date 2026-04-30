"""Aether Billing — Stripe persistence layer.

Backed by asyncpg in non-local environments (tables created by
shared.billing.migrations.ensure_billing_tables) and by in-memory dicts in
AETHER_ENV=local when no DATABASE_URL is configured. Mirrors the fallback
pattern in repositories.repos.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.auth.auth import PlanTier
from shared.logger.logger import get_logger

logger = get_logger("aether.billing.stripe_repo")


# ---------------------------------------------------------------------------
# In-memory fallback (LOCAL only — when no DB pool is available)
# ---------------------------------------------------------------------------

_mem_accounts: dict[str, dict[str, Any]] = {}
_mem_webhook_events: dict[str, dict[str, Any]] = {}
_mem_invoices: dict[str, dict[str, Any]] = {}
_mem_overage_attempts: dict[tuple[str, str], dict[str, Any]] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _from_iso(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(int(val), tz=timezone.utc)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# tenant_billing_accounts
# ---------------------------------------------------------------------------

async def get_billing_account(tenant_id: str) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        return _mem_accounts.get(tenant_id)
    row = await pool.fetchrow(
        "SELECT * FROM tenant_billing_accounts WHERE tenant_id=$1", tenant_id,
    )
    return dict(row) if row else None


async def get_by_stripe_customer_id(customer_id: str) -> Optional[dict[str, Any]]:
    if not customer_id:
        return None
    pool = await get_pool()
    if pool is None:
        for acct in _mem_accounts.values():
            if acct.get("stripe_customer_id") == customer_id:
                return acct
        return None
    row = await pool.fetchrow(
        "SELECT * FROM tenant_billing_accounts WHERE stripe_customer_id=$1",
        customer_id,
    )
    return dict(row) if row else None


async def get_by_stripe_subscription_id(
    subscription_id: str,
) -> Optional[dict[str, Any]]:
    if not subscription_id:
        return None
    pool = await get_pool()
    if pool is None:
        for acct in _mem_accounts.values():
            if acct.get("stripe_subscription_id") == subscription_id:
                return acct
        return None
    row = await pool.fetchrow(
        "SELECT * FROM tenant_billing_accounts WHERE stripe_subscription_id=$1",
        subscription_id,
    )
    return dict(row) if row else None


async def upsert_billing_account(
    tenant_id: str,
    contact_email: Optional[str] = None,
    plan_tier: Optional[str] = None,
) -> dict[str, Any]:
    pool = await get_pool()
    plan_tier = plan_tier or PlanTier.P1_HOBBYIST.value
    now = _utcnow()
    if pool is None:
        existing = _mem_accounts.get(tenant_id)
        if existing:
            if contact_email:
                existing["contact_email"] = contact_email
            existing["updated_at"] = now
            return existing
        record = {
            "tenant_id": tenant_id,
            "contact_email": contact_email,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "stripe_price_id": None,
            "plan_tier": plan_tier,
            "subscription_status": None,
            "current_period_end": None,
            "created_at": now,
            "updated_at": now,
        }
        _mem_accounts[tenant_id] = record
        return record
    await pool.execute(
        """
        INSERT INTO tenant_billing_accounts
            (tenant_id, contact_email, plan_tier)
        VALUES ($1, $2, $3)
        ON CONFLICT (tenant_id) DO UPDATE SET
            contact_email = COALESCE(EXCLUDED.contact_email,
                                     tenant_billing_accounts.contact_email),
            updated_at = NOW()
        """,
        tenant_id, contact_email, plan_tier,
    )
    return await get_billing_account(tenant_id) or {}


async def update_customer_mapping(
    tenant_id: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    contact_email: Optional[str] = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        acct = _mem_accounts.setdefault(tenant_id, {
            "tenant_id": tenant_id,
            "plan_tier": PlanTier.P1_HOBBYIST.value,
            "created_at": _utcnow(),
        })
        if stripe_customer_id is not None:
            acct["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id is not None:
            acct["stripe_subscription_id"] = stripe_subscription_id
        if contact_email is not None:
            acct["contact_email"] = contact_email
        acct["updated_at"] = _utcnow()
        return
    await pool.execute(
        """
        INSERT INTO tenant_billing_accounts
            (tenant_id, contact_email, stripe_customer_id, stripe_subscription_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (tenant_id) DO UPDATE SET
            stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id,
                                          tenant_billing_accounts.stripe_customer_id),
            stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id,
                                              tenant_billing_accounts.stripe_subscription_id),
            contact_email = COALESCE(EXCLUDED.contact_email,
                                     tenant_billing_accounts.contact_email),
            updated_at = NOW()
        """,
        tenant_id, contact_email, stripe_customer_id, stripe_subscription_id,
    )


async def update_subscription_state(
    tenant_id: str,
    stripe_subscription_id: Optional[str] = None,
    stripe_price_id: Optional[str] = None,
    subscription_status: Optional[str] = None,
    current_period_end: Optional[datetime] = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        acct = _mem_accounts.setdefault(tenant_id, {
            "tenant_id": tenant_id,
            "plan_tier": PlanTier.P1_HOBBYIST.value,
            "created_at": _utcnow(),
        })
        if stripe_subscription_id is not None:
            acct["stripe_subscription_id"] = stripe_subscription_id
        if stripe_price_id is not None:
            acct["stripe_price_id"] = stripe_price_id
        if subscription_status is not None:
            acct["subscription_status"] = subscription_status
        if current_period_end is not None:
            acct["current_period_end"] = current_period_end
        acct["updated_at"] = _utcnow()
        return
    await pool.execute(
        """
        UPDATE tenant_billing_accounts SET
            stripe_subscription_id = COALESCE($2, stripe_subscription_id),
            stripe_price_id = COALESCE($3, stripe_price_id),
            subscription_status = COALESCE($4, subscription_status),
            current_period_end = COALESCE($5, current_period_end),
            updated_at = NOW()
        WHERE tenant_id = $1
        """,
        tenant_id,
        stripe_subscription_id,
        stripe_price_id,
        subscription_status,
        current_period_end,
    )


async def update_plan_tier(tenant_id: str, plan_tier: str) -> None:
    """Update the authoritative plan_tier for a tenant.

    Called only after customer.subscription.updated/deleted confirms the new
    state. Existing API-key/auth code reads from this row to drive PLAN_CATALOG
    quotas/RPM through middleware.
    """
    pool = await get_pool()
    if pool is None:
        acct = _mem_accounts.setdefault(tenant_id, {
            "tenant_id": tenant_id,
            "created_at": _utcnow(),
        })
        acct["plan_tier"] = plan_tier
        acct["updated_at"] = _utcnow()
        return
    await pool.execute(
        """
        INSERT INTO tenant_billing_accounts (tenant_id, plan_tier)
        VALUES ($1, $2)
        ON CONFLICT (tenant_id) DO UPDATE SET
            plan_tier = EXCLUDED.plan_tier,
            updated_at = NOW()
        """,
        tenant_id, plan_tier,
    )


# ---------------------------------------------------------------------------
# stripe_webhook_events (idempotency)
# ---------------------------------------------------------------------------

async def record_webhook_event_once(event_id: str, event_type: str) -> bool:
    """Record a webhook event ID. Return True if newly recorded, False if dup."""
    if not event_id:
        return False
    pool = await get_pool()
    now = _utcnow()
    if pool is None:
        if event_id in _mem_webhook_events:
            return False
        _mem_webhook_events[event_id] = {
            "event_id": event_id,
            "event_type": event_type,
            "processed_at": now,
        }
        return True
    try:
        result = await pool.execute(
            """
            INSERT INTO stripe_webhook_events (event_id, event_type)
            VALUES ($1, $2)
            ON CONFLICT (event_id) DO NOTHING
            """,
            event_id, event_type,
        )
        # asyncpg returns "INSERT 0 1" when a row was inserted, "INSERT 0 0"
        # when ON CONFLICT skipped it.
        return result.endswith(" 1")
    except Exception as e:
        logger.warning(f"record_webhook_event_once failed: {e}")
        return False


# ---------------------------------------------------------------------------
# stripe_invoices
# ---------------------------------------------------------------------------

INVOICE_FIELDS = (
    "stripe_invoice_id", "tenant_id", "stripe_customer_id",
    "stripe_subscription_id", "status", "currency", "amount_due",
    "amount_paid", "amount_remaining", "hosted_invoice_url", "invoice_pdf",
    "period_start", "period_end", "created_at",
)


async def upsert_invoice(invoice: dict[str, Any]) -> None:
    """Upsert a Stripe invoice payload into stripe_invoices."""
    if not invoice.get("stripe_invoice_id") or not invoice.get("tenant_id"):
        logger.debug("upsert_invoice missing keys")
        return
    pool = await get_pool()
    if pool is None:
        prev = _mem_invoices.get(invoice["stripe_invoice_id"], {})
        merged = {**prev, **invoice, "updated_at": _utcnow()}
        _mem_invoices[invoice["stripe_invoice_id"]] = merged
        return
    await pool.execute(
        """
        INSERT INTO stripe_invoices (
            stripe_invoice_id, tenant_id, stripe_customer_id,
            stripe_subscription_id, status, currency,
            amount_due, amount_paid, amount_remaining,
            hosted_invoice_url, invoice_pdf,
            period_start, period_end, created_at, updated_at
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,NOW()
        )
        ON CONFLICT (stripe_invoice_id) DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id,
                                          stripe_invoices.stripe_customer_id),
            stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id,
                                              stripe_invoices.stripe_subscription_id),
            status = COALESCE(EXCLUDED.status, stripe_invoices.status),
            currency = COALESCE(EXCLUDED.currency, stripe_invoices.currency),
            amount_due = COALESCE(EXCLUDED.amount_due, stripe_invoices.amount_due),
            amount_paid = COALESCE(EXCLUDED.amount_paid, stripe_invoices.amount_paid),
            amount_remaining = COALESCE(EXCLUDED.amount_remaining,
                                        stripe_invoices.amount_remaining),
            hosted_invoice_url = COALESCE(EXCLUDED.hosted_invoice_url,
                                          stripe_invoices.hosted_invoice_url),
            invoice_pdf = COALESCE(EXCLUDED.invoice_pdf, stripe_invoices.invoice_pdf),
            period_start = COALESCE(EXCLUDED.period_start, stripe_invoices.period_start),
            period_end = COALESCE(EXCLUDED.period_end, stripe_invoices.period_end),
            created_at = COALESCE(EXCLUDED.created_at, stripe_invoices.created_at),
            updated_at = NOW()
        """,
        invoice.get("stripe_invoice_id"),
        invoice.get("tenant_id"),
        invoice.get("stripe_customer_id"),
        invoice.get("stripe_subscription_id"),
        invoice.get("status"),
        invoice.get("currency"),
        invoice.get("amount_due"),
        invoice.get("amount_paid"),
        invoice.get("amount_remaining"),
        invoice.get("hosted_invoice_url"),
        invoice.get("invoice_pdf"),
        _from_iso(invoice.get("period_start")),
        _from_iso(invoice.get("period_end")),
        _from_iso(invoice.get("created_at")),
    )


async def list_invoices(
    tenant_id: str, limit: int = 50,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        items = [
            inv for inv in _mem_invoices.values()
            if inv.get("tenant_id") == tenant_id
        ]
        items.sort(
            key=lambda r: r.get("created_at") or r.get("updated_at") or _utcnow(),
            reverse=True,
        )
        return items[: max(1, limit)]
    rows = await pool.fetch(
        """
        SELECT * FROM stripe_invoices
        WHERE tenant_id=$1
        ORDER BY COALESCE(created_at, updated_at) DESC
        LIMIT $2
        """,
        tenant_id, max(1, limit),
    )
    return [dict(row) for row in rows]


async def get_invoice(
    tenant_id: str, stripe_invoice_id: str,
) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        inv = _mem_invoices.get(stripe_invoice_id)
        if inv and inv.get("tenant_id") == tenant_id:
            return inv
        return None
    row = await pool.fetchrow(
        "SELECT * FROM stripe_invoices "
        "WHERE tenant_id=$1 AND stripe_invoice_id=$2",
        tenant_id, stripe_invoice_id,
    )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# stripe_overage_invoice_attempts
# ---------------------------------------------------------------------------

async def record_overage_invoice_attempt(
    tenant_id: str,
    billing_period: str,
    overage_requests: int,
    amount_cents: Optional[int] = None,
    stripe_invoice_id: Optional[str] = None,
    stripe_invoice_item_id: Optional[str] = None,
    status: str = "pending",
    error: Optional[str] = None,
) -> dict[str, Any]:
    """Insert or update the overage-invoice attempt for (tenant, period).

    Idempotent: a single attempt row exists per (tenant_id, billing_period).
    """
    pool = await get_pool()
    now = _utcnow()
    if pool is None:
        key = (tenant_id, billing_period)
        existing = _mem_overage_attempts.get(key)
        if existing:
            existing.update({
                "overage_requests": overage_requests,
                "amount_cents": amount_cents,
                "stripe_invoice_id": stripe_invoice_id or existing.get("stripe_invoice_id"),
                "stripe_invoice_item_id": stripe_invoice_item_id or existing.get("stripe_invoice_item_id"),
                "status": status,
                "error": error,
                "updated_at": now,
            })
            return existing
        record = {
            "tenant_id": tenant_id,
            "billing_period": billing_period,
            "overage_requests": overage_requests,
            "amount_cents": amount_cents,
            "stripe_invoice_id": stripe_invoice_id,
            "stripe_invoice_item_id": stripe_invoice_item_id,
            "status": status,
            "error": error,
            "created_at": now,
            "updated_at": now,
        }
        _mem_overage_attempts[key] = record
        return record
    await pool.execute(
        """
        INSERT INTO stripe_overage_invoice_attempts (
            tenant_id, billing_period, overage_requests, amount_cents,
            stripe_invoice_id, stripe_invoice_item_id, status, error
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (tenant_id, billing_period) DO UPDATE SET
            overage_requests = EXCLUDED.overage_requests,
            amount_cents = EXCLUDED.amount_cents,
            stripe_invoice_id = COALESCE(EXCLUDED.stripe_invoice_id,
                                         stripe_overage_invoice_attempts.stripe_invoice_id),
            stripe_invoice_item_id = COALESCE(EXCLUDED.stripe_invoice_item_id,
                                              stripe_overage_invoice_attempts.stripe_invoice_item_id),
            status = EXCLUDED.status,
            error = EXCLUDED.error,
            updated_at = NOW()
        """,
        tenant_id, billing_period, overage_requests, amount_cents,
        stripe_invoice_id, stripe_invoice_item_id, status, error,
    )
    row = await pool.fetchrow(
        "SELECT * FROM stripe_overage_invoice_attempts "
        "WHERE tenant_id=$1 AND billing_period=$2",
        tenant_id, billing_period,
    )
    return dict(row) if row else {}


async def get_overage_invoice_attempt(
    tenant_id: str, billing_period: str,
) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        return _mem_overage_attempts.get((tenant_id, billing_period))
    row = await pool.fetchrow(
        "SELECT * FROM stripe_overage_invoice_attempts "
        "WHERE tenant_id=$1 AND billing_period=$2",
        tenant_id, billing_period,
    )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _reset_in_memory_for_tests() -> None:
    """Clear all in-memory state. Test-only helper."""
    _mem_accounts.clear()
    _mem_webhook_events.clear()
    _mem_invoices.clear()
    _mem_overage_attempts.clear()


__all__ = [
    "get_billing_account",
    "get_by_stripe_customer_id",
    "get_by_stripe_subscription_id",
    "upsert_billing_account",
    "update_customer_mapping",
    "update_subscription_state",
    "update_plan_tier",
    "record_webhook_event_once",
    "upsert_invoice",
    "list_invoices",
    "get_invoice",
    "record_overage_invoice_attempt",
    "get_overage_invoice_attempt",
    "_reset_in_memory_for_tests",
]


# Suppress unused-import warning for json (kept available for future JSONB use)
_ = json
