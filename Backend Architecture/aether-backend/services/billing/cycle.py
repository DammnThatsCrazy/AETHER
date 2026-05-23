"""Aether Billing — Overage Invoice Cycle

Iterates all tenants with a Stripe billing account and billing_period
overage, creates Stripe invoice items, and records the attempt.

Called at end-of-month by the async cron task in services/billing/cron.py,
or manually via POST /v1/admin/billing/overage-cycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config.settings import settings
from shared.auth.auth import PlanTier
from shared.billing import stripe_client, stripe_repository
from shared.billing.overage import OverageCalculator
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.billing.cycle")


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _list_active_tenant_ids() -> list[str]:
    """Return tenant IDs with an active or past_due billing account."""
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool is not None:
            rows = await pool.fetch(
                """
                SELECT tenant_id FROM tenant_billing_accounts
                WHERE subscription_status IN ('active', 'past_due')
                """
            )
            return [row["tenant_id"] for row in rows]
    except Exception as e:
        logger.warning(f"Overage cycle: failed to list tenants from DB: {e}")
    # In-memory fallback: iterate in-memory accounts
    from shared.billing.stripe_repository import _mem_accounts
    return [
        tid for tid, acct in _mem_accounts.items()
        if acct.get("subscription_status") in ("active", "past_due")
    ]


async def run_overage_cycle(billing_period: Optional[str] = None) -> dict:
    """Run the overage invoice cycle for all active tenants.

    Args:
        billing_period: YYYY-MM string; defaults to current month.

    Returns:
        Summary dict with counts for processed, skipped, and failed tenants.
    """
    period = billing_period or _current_period()
    logger.info(f"Overage cycle started: billing_period={period}")

    if not settings.stripe_billing.overage_invoicing_enabled:
        logger.info("Overage invoicing disabled (STRIPE_OVERAGE_PRICE_ID not set); skipping")
        return {"period": period, "skipped": 0, "processed": 0, "failed": 0, "reason": "overage_disabled"}

    redis_client = None
    db_pool = None
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        quota_engine = getattr(registry, "quota_engine", None)
        if quota_engine is not None:
            redis_client = getattr(quota_engine, "_redis", None)
        from repositories.repos import get_pool
        db_pool = await get_pool()
    except Exception as e:
        logger.debug(f"Overage cycle: resource init partial: {e}")

    calculator = OverageCalculator(
        redis_client=redis_client,
        db_pool=db_pool,
        pricing_option=settings.rate_limit.pricing_option,
    )

    tenant_ids = await _list_active_tenant_ids()
    logger.info(f"Overage cycle: {len(tenant_ids)} active tenants for period={period}")

    processed = skipped = failed = 0

    for tenant_id in tenant_ids:
        try:
            # Skip if already invoiced this period
            existing = await stripe_repository.get_overage_invoice_attempt(tenant_id, period)
            if existing and existing.get("status") in ("success", "pending"):
                skipped += 1
                continue

            account = await stripe_repository.get_billing_account(tenant_id)
            if not account:
                skipped += 1
                continue

            plan_tier_value = account.get("plan_tier", "P1")
            try:
                plan_tier = PlanTier(plan_tier_value)
            except ValueError:
                plan_tier = PlanTier.P1_HOBBYIST

            invoice = await calculator.calculate(tenant_id, plan_tier, period)
            if invoice.overage_request_count == 0:
                skipped += 1
                continue

            amount_cents = int(invoice.total_overage * 100)
            customer_id = account.get("stripe_customer_id") or ""

            # Record as pending before calling Stripe (idempotency)
            await stripe_repository.record_overage_invoice_attempt(
                tenant_id=tenant_id,
                billing_period=period,
                overage_requests=invoice.overage_request_count,
                amount_cents=amount_cents,
                status="pending",
            )

            result = await stripe_client.create_overage_invoice_item(
                tenant_id=tenant_id,
                customer_id=customer_id,
                billing_period=period,
                overage_requests=invoice.overage_request_count,
                amount_cents=amount_cents,
            )

            await stripe_repository.record_overage_invoice_attempt(
                tenant_id=tenant_id,
                billing_period=period,
                overage_requests=invoice.overage_request_count,
                amount_cents=amount_cents,
                stripe_invoice_id=result.get("stripe_invoice_id"),
                stripe_invoice_item_id=result.get("stripe_invoice_item_id"),
                status="success",
            )

            metrics.increment(
                "billing_overage_invoiced",
                labels={"plan_tier": plan_tier.value},
            )
            logger.info(
                f"Overage invoice created: tenant={tenant_id} period={period} "
                f"requests={invoice.overage_request_count} cents={amount_cents}"
            )
            processed += 1

        except Exception as e:
            failed += 1
            logger.error(f"Overage cycle failed for tenant={tenant_id}: {e}")
            try:
                await stripe_repository.record_overage_invoice_attempt(
                    tenant_id=tenant_id,
                    billing_period=period,
                    overage_requests=0,
                    status="failed",
                    error=str(e),
                )
            except Exception:
                pass

    summary = {"period": period, "processed": processed, "skipped": skipped, "failed": failed}
    logger.info(f"Overage cycle complete: {summary}")
    metrics.increment("billing_overage_cycle_runs")
    return summary
