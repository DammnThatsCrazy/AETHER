"""Cost selection for AI execution facts.

Selection hierarchy (first available wins):

    billed_cost           → cost_basis "billed"
    actual_cost           → cost_basis "provider_reported"
    price-card calculation → cost_basis "calculated"
    estimated_cost        → cost_basis "estimated"
    (nothing)             → cost_basis "unknown", selected_cost None

UNKNOWN STAYS UNKNOWN: an unknown cost is never coerced to zero.

Currency safety: a calculated cost is denominated in the price card's
currency. If the event currency differs from the card currency the two are
never mixed — selection falls back to estimated/unknown and the mismatch is
flagged so the projector can mark the fact ``suspect``.

DECIMAL PRESERVED TO THE WIRE: ``CostSelection.selected_cost`` keeps the money
value as ``Decimal`` (program sec19) — the exact provider-reported/estimated
values flow unrounded into ``AIExecutionFact`` and Decimal aggregation. The
float wire/JSON shape is produced only by the Pydantic ``@field_serializer`` on
``ai_models`` at the external serialization boundary, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from services.economic.ai_models import AIInvocationObserved, AIPriceCard, CostBasis
from services.economic.ai_pricing import AIPriceCardRegistry, get_price_card_registry

# (usage field on the invocation, rate field on the price card, unit divisor)
USAGE_RATE_MAP: tuple[tuple[str, str, float], ...] = (
    ("input_tokens", "input_tokens_per_1k", 1000.0),
    ("output_tokens", "output_tokens_per_1k", 1000.0),
    ("cached_input_tokens", "cached_input_tokens_per_1k", 1000.0),
    ("reasoning_tokens", "reasoning_tokens_per_1k", 1000.0),
    ("embedding_tokens", "embedding_tokens_per_1k", 1000.0),
    ("image_units", "image_unit", 1.0),
    ("audio_seconds", "audio_second", 1.0),
    ("video_seconds", "video_second", 1.0),
    ("tool_call_count", "tool_call", 1.0),
    ("retrieval_count", "retrieval", 1.0),
)


@dataclass(frozen=True)
class CostSelection:
    """Outcome of the cost selection hierarchy for one invocation."""

    selected_cost: Optional[Decimal]
    cost_basis: CostBasis
    pricing_version: Optional[str]
    currency: str
    currency_mismatch: bool = False


def calculate_card_cost(observed: AIInvocationObserved, card: AIPriceCard) -> Optional[float]:
    """Sum the priced usage dimensions present on the invocation.

    Returns None when no usage dimension present on the invocation has a rate
    on the card (nothing priceable — never fabricate a zero).
    """
    total = 0.0
    priced_any = False
    for usage_field, rate_field, divisor in USAGE_RATE_MAP:
        usage = getattr(observed, usage_field)
        rate = getattr(card.rates, rate_field)
        if usage is None or rate is None:
            continue
        total += (usage / divisor) * rate
        priced_any = True
    if not priced_any:
        return None
    return round(total, 10)


async def select_cost(
    observed: AIInvocationObserved,
    registry: AIPriceCardRegistry | None = None,
) -> CostSelection:
    """Apply the cost selection hierarchy to one observed invocation."""
    if observed.billed_cost is not None:
        return CostSelection(
            # Money stays Decimal here — the float wire shape is produced only by
            # the AIExecutionFact @field_serializer at the serialization boundary.
            selected_cost=observed.billed_cost,
            cost_basis="billed",
            pricing_version=observed.pricing_version,
            currency=observed.currency,
        )
    if observed.actual_cost is not None:
        return CostSelection(
            selected_cost=observed.actual_cost,
            cost_basis="provider_reported",
            pricing_version=observed.pricing_version,
            currency=observed.currency,
        )

    registry = registry or get_price_card_registry()
    currency_mismatch = False
    card = None
    try:
        card = await registry.get_active_card(
            observed.provider,
            observed.model,
            region=observed.region,
            at=observed.observed_at,
            tenant_id=observed.tenant_id,
        )
    except Exception:
        card = None

    if card is not None:
        if card.currency != observed.currency:
            # Never mix currencies: fall through to estimated/unknown, flagged.
            currency_mismatch = True
        else:
            calculated = calculate_card_cost(observed, card)
            if calculated is not None:
                return CostSelection(
                    # Card rates are float-typed; capture the computed result as
                    # Decimal at the selection boundary so every subsequent money
                    # consumer (fact build, aggregation) sees exact Decimal.
                    selected_cost=Decimal(str(calculated)),
                    cost_basis="calculated",
                    pricing_version=card.pricing_version,
                    currency=card.currency,
                )

    if observed.estimated_cost is not None:
        return CostSelection(
            selected_cost=observed.estimated_cost,
            cost_basis="estimated",
            pricing_version=observed.pricing_version,
            currency=observed.currency,
            currency_mismatch=currency_mismatch,
        )

    # Unknown stays unknown — never coerce to zero.
    return CostSelection(
        selected_cost=None,
        cost_basis="unknown",
        pricing_version=None,
        currency=observed.currency,
        currency_mismatch=currency_mismatch,
    )
