"""
Aether Service — Pricing Engine
Resolves price for a protected resource given tenant, subject, and plan context.
Uses base price + tenant multiplier + plan discounts.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional

from shared.logger.logger import get_logger

from services.value.models import to_decimal

from .commerce_models import ProtectedResource
from .resources import get_resource_registry

logger = get_logger("aether.service.x402.pricing")

# Plan discount factors. Computed in Decimal so a fractional unit price times a
# discount never produces a binary-float artifact (e.g. 0.10 * 0.60 * n).
_PLAN_DISCOUNTS: dict[str, Decimal] = {
    "pro": Decimal("0.80"),
    "enterprise": Decimal("0.60"),
}
_PRICE_ROUND = Decimal("0.000001")  # 6 dp, mirrors the legacy round(..., 6)


def _round_usd(value: Decimal) -> Decimal:
    return value.quantize(_PRICE_ROUND, rounding=ROUND_HALF_EVEN)


class PricingEngine:
    """Resolves the USD price for access to a protected resource."""

    def __init__(self) -> None:
        self._registry = get_resource_registry()

    async def resolve_price(
        self,
        tenant_id: str,
        resource_id: str,
        plan_code: Optional[str] = None,
        quantity: int = 1,
    ) -> dict:
        """Return {'resource_id', 'unit_price_usd', 'total_usd', 'currency'}."""
        resource = await self._registry.get(tenant_id, resource_id)
        if not resource:
            raise ValueError(f"Unknown resource: {resource_id}")

        # Convert to Decimal at the boundary: every price arithmetic below
        # (plan discount, quantity scaling) is exact decimal money math.
        unit = to_decimal(resource.price_usd)
        if unit is None:  # unparseable price is an error, never coerced to 0
            raise ValueError(f"Resource has an unparseable price: {resource_id}")

        # Plan discounts (simple): "pro" -> 20%, "enterprise" -> 40%
        discount = _PLAN_DISCOUNTS.get(plan_code or "")
        if discount is not None:
            unit = unit * discount

        total = unit * Decimal(int(quantity))
        unit_price = _round_usd(unit)
        # total is derived from the UNROUNDED discounted unit (matching the
        # legacy float path), then rounded to 6 dp with half-even.
        total = _round_usd(total)
        return {
            "resource_id": resource_id,
            "unit_price_usd": float(unit_price),
            "total_usd": float(total),
            "currency": "USD",
            "asset_symbol": "USDC",
        }

    async def quote_for(
        self, tenant_id: str, resource: ProtectedResource
    ) -> float:
        return resource.price_usd
