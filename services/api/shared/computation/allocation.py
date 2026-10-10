"""The allocation engine.

Distributes a source amount (e.g. campaign spend) across targets (channels,
entities, journeys) under a declared policy, and GUARANTEES conservation:

    sum(allocated_amounts) + residual == source_amount

Every allocated slice records its weight, its share, the residual, the rounding
policy, and whether it is ``observed`` or ``estimated``. Entity/journey-level
campaign cost is ``estimated`` (allocated), never ``observed`` — which is the
fix for gold materialization attributing full campaign spend to every journey.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from shared.computation.errors import AllocationError
from shared.computation.types import to_decimal, to_decimal_string


class AllocationPolicy(str, Enum):
    EQUAL = "equal"
    PROPORTIONAL = "proportional"
    TIME_WEIGHTED = "time_weighted"
    USAGE_WEIGHTED = "usage_weighted"
    ATTRIBUTION_CREDIT = "attribution_credit"
    CONTRACTUAL = "contractual"
    CUSTOM = "custom"


ALLOCATION_POLICIES: tuple[str, ...] = tuple(p.value for p in AllocationPolicy)


class AllocationTarget(BaseModel):
    """One target receiving a share of the source amount."""

    target_id: str
    weight: str = "0"  # decimal string
    allocated_amount: Optional[str] = None  # decimal string, filled by the engine


class AllocationResult(BaseModel):
    """A conserved allocation of a source amount across targets."""

    policy: AllocationPolicy
    policy_version: str = "1"
    source_amount: str
    currency: str
    targets: list[AllocationTarget] = Field(default_factory=list)
    residual: str = "0"
    rounding: str = "half_up_2dp"
    basis: str = "estimated"  # allocated slices are estimated, not observed

    def total_allocated(self) -> Decimal:
        total = Decimal("0")
        for t in self.targets:
            d = to_decimal(t.allocated_amount)
            if d is not None:
                total += d
        return total

    def assert_conserved(self) -> None:
        src = to_decimal(self.source_amount) or Decimal("0")
        residual = to_decimal(self.residual) or Decimal("0")
        if self.total_allocated() + residual != src:
            raise AllocationError(
                f"allocation not conserved: "
                f"sum({self.total_allocated()}) + residual({residual}) != source({src})"
            )


def _quantize(d: Decimal, places: int = 2) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def allocate(
    *,
    source_amount: object,
    currency: str,
    weights: dict[str, object],
    policy: AllocationPolicy = AllocationPolicy.PROPORTIONAL,
    policy_version: str = "1",
    places: int = 2,
) -> AllocationResult:
    """Allocate ``source_amount`` across targets by ``weights``, conserving total.

    ``weights`` maps target_id -> weight. For ``EQUAL`` the weights are ignored
    and every target gets an equal share. The residual (from rounding or a zero
    total weight) is disclosed, never dropped.
    """
    if not currency:
        raise AllocationError("allocation requires a currency")
    src = to_decimal(source_amount)
    if src is None:
        raise AllocationError("allocation source amount is not a finite number")

    target_ids = list(weights.keys())
    if not target_ids:
        # Nothing to allocate to: the entire source is residual.
        return AllocationResult(
            policy=policy,
            policy_version=policy_version,
            source_amount=to_decimal_string(src) or "0",
            currency=currency,
            targets=[],
            residual=to_decimal_string(src) or "0",
        )

    if policy == AllocationPolicy.EQUAL:
        eff_weights = {t: Decimal("1") for t in target_ids}
    else:
        eff_weights = {}
        for t in target_ids:
            w = to_decimal(weights[t])
            eff_weights[t] = w if (w is not None and w > 0) else Decimal("0")

    total_w = sum(eff_weights.values(), Decimal("0"))
    targets: list[AllocationTarget] = []
    allocated_total = Decimal("0")

    if total_w == 0:
        # No positive weights: allocate nothing; full source is residual.
        for t in target_ids:
            targets.append(AllocationTarget(target_id=t, weight="0", allocated_amount="0"))
        return AllocationResult(
            policy=policy,
            policy_version=policy_version,
            source_amount=to_decimal_string(src) or "0",
            currency=currency,
            targets=targets,
            residual=to_decimal_string(src) or "0",
        )

    for t in target_ids:
        share = _quantize(src * eff_weights[t] / total_w, places)
        allocated_total += share
        targets.append(
            AllocationTarget(
                target_id=t,
                weight=to_decimal_string(eff_weights[t]) or "0",
                allocated_amount=to_decimal_string(share) or "0",
            )
        )

    residual = src - allocated_total
    result = AllocationResult(
        policy=policy,
        policy_version=policy_version,
        source_amount=to_decimal_string(src) or "0",
        currency=currency,
        targets=targets,
        residual=to_decimal_string(residual) or "0",
    )
    result.assert_conserved()
    return result


__all__ = [
    "AllocationPolicy",
    "ALLOCATION_POLICIES",
    "AllocationTarget",
    "AllocationResult",
    "allocate",
]
