"""Derivatives usage-meter hook.

Phase-0 gap (7): usage metering was in-memory only
(``DerivativesProductService.meter_usage`` accumulated into a private dict and
nothing ever left the process). This module exposes a MeteringService-style
hook so a durable/auditable metering sink can be installed without touching the
product facade or the routes.

* :class:`DerivativesMeter` — the hook: ``record`` accumulates a tenant-scoped
  in-memory rollup (deterministic, Decimal-exact) AND, when a sink is installed,
  forwards every record to it. ``snapshot`` returns the current rollup.
* :func:`install_derivatives_meter_sink` — the wiring seam the integration pass
  uses to point records at the real metering authority (e.g. a durable
  ``MeterRecord`` repository) while the product facade keeps serving the same
  in-memory rollup.
* :data:`derivatives_meter` — the process-wide hook the product facade shares,
  so ``meter_usage`` and any worker-side recording observe one consistent view.

The meter names are exactly ``product.USAGE_METERS``; an unknown meter or a
negative quantity is rejected (ValueError) before any accumulation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Optional

from services.derivatives.product import USAGE_METERS

# Sink signature: ``(tenant_id: str, meter: str, quantity: Decimal) -> None``.
# The sink is the durable/auditable authority; the hook still keeps its
# in-memory rollup so local mode and route responses never block on the sink.
MeterSink = Callable[[str, str, Decimal], None]


class DerivativesMeter:
    """In-memory meter rollup + optional MeteringService-style sink hook."""

    def __init__(self) -> None:
        self._usage: dict[tuple[str, str], Decimal] = {}
        self._sink: Optional[MeterSink] = None

    def install_sink(self, sink: Optional[MeterSink]) -> None:
        """Install (or clear, with ``None``) the durable metering sink."""
        self._sink = sink

    def reset(self) -> None:
        """Test/demo hygiene: drop the rollup and detach any installed sink."""
        self._usage.clear()
        self._sink = None

    @property
    def sink_installed(self) -> bool:
        return self._sink is not None

    def record(
        self,
        tenant_id: str,
        meter: str,
        quantity: Decimal | int | str,
    ) -> dict[str, Any]:
        """Accumulate one usage record and forward to the sink if installed.

        Returns the current tenant-scoped rollup for the meter. Rejects unknown
        meters and negative quantities before any state changes.
        """
        if meter not in USAGE_METERS:
            raise ValueError(f"unknown derivatives usage meter: {meter}")
        qty = Decimal(quantity)
        if qty < 0:
            raise ValueError("usage quantity must be non-negative")
        key = (tenant_id, meter)
        self._usage[key] = self._usage.get(key, Decimal("0")) + qty
        if self._sink is not None:
            self._sink(tenant_id, meter, qty)
        return {
            "tenant_id": tenant_id,
            "meter": meter,
            "quantity": str(self._usage[key]),
            "billable": meter != "history_retention_days",
        }

    def snapshot(self, tenant_id: str) -> dict[str, str]:
        """Current rollup for one tenant (all meters), Decimal->string."""
        return {
            meter: str(self._usage.get((tenant_id, meter), Decimal("0")))
            for meter in USAGE_METERS
        }

    def total(self, meter: str) -> Decimal:
        """Cross-tenant total for a meter (operator diagnostics)."""
        if meter not in USAGE_METERS:
            raise ValueError(f"unknown derivatives usage meter: {meter}")
        return sum(
            (qty for (_, m), qty in self._usage.items() if m == meter),
            Decimal("0"),
        )


derivatives_meter = DerivativesMeter()


def install_derivatives_meter_sink(sink: Optional[MeterSink]) -> None:
    """Wire the process-wide derivatives meter to a durable sink (or ``None``)."""
    derivatives_meter.install_sink(sink)


__all__ = [
    "DerivativesMeter",
    "derivatives_meter",
    "install_derivatives_meter_sink",
    "MeterSink",
]
