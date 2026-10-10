"""Aether Billing — Data Models"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class OverageLineItem:
    service_name: str
    endpoint_pattern: str
    overage_requests: int
    price_per_1k: Decimal
    pricing_option: str       # "A", "B", or "C"
    line_total: Decimal       # 2-decimal-rounded dollars

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "endpoint_pattern": self.endpoint_pattern,
            "overage_requests": self.overage_requests,
            "price_per_1k": str(self.price_per_1k),
            "pricing_option": self.pricing_option,
            "line_total": str(self.line_total),
        }


@dataclass
class OverageInvoice:
    tenant_id: str
    billing_period: str
    plan_tier: str
    plan_fee: Decimal
    included_quota: int
    total_requests: int
    overage_request_count: int
    line_items: list[OverageLineItem] = field(default_factory=list)
    total_overage: Decimal = Decimal("0")
    period_total: Decimal = Decimal("0")

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "billing_period": self.billing_period,
            "plan_tier": self.plan_tier,
            "plan_fee": str(self.plan_fee),
            "included_quota": self.included_quota,
            "total_requests": self.total_requests,
            "overage_request_count": self.overage_request_count,
            "line_items": [li.to_dict() for li in self.line_items],
            "total_overage": str(self.total_overage),
            "period_total": str(self.period_total),
        }
