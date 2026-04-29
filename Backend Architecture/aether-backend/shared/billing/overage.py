"""Aether Billing — Overage Calculator

Converts per-service overage counts into dollar line items using the active
pricing option (A/B/C). Reads counts from Redis hot-path first, falls back
to the durable PostgreSQL snapshot.
"""

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from shared.auth.auth import PlanTier
from shared.billing.models import OverageInvoice, OverageLineItem
from shared.logger.logger import get_logger
from shared.plans.catalog import PLAN_CATALOG
from shared.plans.service_catalog import find_service_by_name
from shared.plans.models import ServiceDefinition
from shared.rate_limit.metrics import OVERAGE_COST

logger = get_logger("aether.billing.overage")


def _quantize_dollars(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _price_per_1k(service: ServiceDefinition, option: str) -> Decimal:
    if option == "A":
        return service.pricing.option_a_per_1k
    if option == "B":
        return service.pricing.option_b_per_1k
    if option == "C":
        return service.pricing.option_c_per_1k
    raise ValueError(f"Unknown pricing option: {option!r}")


class OverageCalculator:
    """Build OverageInvoice records from per-service overage counts."""

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        db_pool: Optional[Any] = None,
        pricing_option: str = "B",
    ) -> None:
        if pricing_option not in ("A", "B", "C"):
            raise ValueError(f"pricing_option must be A/B/C: {pricing_option!r}")
        self._redis = redis_client
        self._db = db_pool
        self._pricing_option = pricing_option

    @property
    def pricing_option(self) -> str:
        return self._pricing_option

    async def _read_overage_counts(
        self, tenant_id: str, billing_period: str,
    ) -> dict[str, int]:
        # Hot path: Redis hash
        if self._redis is not None:
            try:
                key = f"rl:overage:{tenant_id}:{billing_period}"
                raw = await self._redis.hgetall(key)
                if raw:
                    return {k: int(v) for k, v in raw.items()}
            except Exception as e:
                logger.warning(f"Redis overage read failed: {e}")
        # Cold path: PostgreSQL snapshot
        if self._db is not None:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT overage_by_service FROM tenant_usage "
                        "WHERE tenant_id=$1 AND billing_period=$2",
                        tenant_id, billing_period,
                    )
                if row and row["overage_by_service"]:
                    raw = row["overage_by_service"]
                    if isinstance(raw, str):
                        raw = json.loads(raw)
                    return {k: int(v) for k, v in raw.items()}
            except Exception as e:
                logger.warning(f"Postgres overage read failed: {e}")
        return {}

    async def _read_total_requests(
        self, tenant_id: str, billing_period: str,
    ) -> int:
        if self._redis is not None:
            try:
                raw = await self._redis.get(
                    f"rl:quota:{tenant_id}:{billing_period}"
                )
                if raw is not None:
                    return int(raw)
            except Exception as e:
                logger.warning(f"Redis quota read failed: {e}")
        if self._db is not None:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT total_requests FROM tenant_usage "
                        "WHERE tenant_id=$1 AND billing_period=$2",
                        tenant_id, billing_period,
                    )
                if row:
                    return int(row["total_requests"])
            except Exception as e:
                logger.warning(f"Postgres quota read failed: {e}")
        return 0

    def _build_line_items(
        self, overage_by_service: dict[str, int],
    ) -> list[OverageLineItem]:
        items: list[OverageLineItem] = []
        for service_name, count in overage_by_service.items():
            if count <= 0:
                continue
            service = find_service_by_name(service_name)
            if service is None:
                logger.warning(
                    f"Overage for unknown service {service_name!r} — skipping"
                )
                continue
            price = _price_per_1k(service, self._pricing_option)
            line_total = _quantize_dollars(
                (Decimal(count) / Decimal(1000)) * price
            )
            items.append(OverageLineItem(
                service_name=service_name,
                endpoint_pattern=service.endpoint_pattern,
                overage_requests=count,
                price_per_1k=price,
                pricing_option=self._pricing_option,
                line_total=line_total,
            ))
        # Sort by largest line item first for nicer invoices.
        items.sort(key=lambda it: it.line_total, reverse=True)
        return items

    async def calculate(
        self, tenant_id: str, plan_tier: PlanTier, billing_period: str,
    ) -> OverageInvoice:
        plan = PLAN_CATALOG[plan_tier]
        plan_fee = self._plan_fee(plan_tier)

        overage_by_service = await self._read_overage_counts(
            tenant_id, billing_period,
        )
        total_requests = await self._read_total_requests(
            tenant_id, billing_period,
        )

        line_items = self._build_line_items(overage_by_service)
        for li in line_items:
            try:
                OVERAGE_COST.labels(
                    tenant_id=tenant_id,
                    plan_tier=plan.plan_id,
                    service=li.service_name,
                    pricing_option=li.pricing_option,
                ).inc(float(li.line_total))
            except Exception:
                pass
        total_overage = _quantize_dollars(
            sum((li.line_total for li in line_items), start=Decimal("0"))
        )
        overage_request_count = sum(overage_by_service.values())
        period_total = _quantize_dollars(plan_fee + total_overage)

        return OverageInvoice(
            tenant_id=tenant_id,
            billing_period=billing_period,
            plan_tier=plan.plan_id,
            plan_fee=plan_fee,
            included_quota=plan.monthly_quota,
            total_requests=total_requests,
            overage_request_count=overage_request_count,
            line_items=line_items,
            total_overage=total_overage,
            period_total=period_total,
        )

    def _plan_fee(self, plan_tier: PlanTier) -> Decimal:
        plan = PLAN_CATALOG[plan_tier]
        if self._pricing_option == "A":
            return plan.pricing.option_a
        if self._pricing_option == "B":
            return plan.pricing.option_b
        return plan.pricing.option_c
