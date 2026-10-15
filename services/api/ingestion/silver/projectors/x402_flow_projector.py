"""Silver projector for x402 payment-required flow events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_X402_TYPES = frozenset({
    "x402_payment_required_observed",
    "x402_payment_initiated_observed",
    "x402_payment_verified_observed",
    "x402_payment_failed_observed",
    "x402_resource_unlocked_observed",
    "x402_settlement_confirmed_observed",
})


class X402FlowProjector(BaseProjector):
    handles = _X402_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "flow_type": event["type"],
            "resource_id": p.get("resourceId"),
            "payment_required": p.get("paymentRequired"),
            "amount": p.get("amount"),
            "currency": p.get("currency", "USD"),
            "settled": event["type"] in {
                "x402_payment_verified_observed",
                "x402_resource_unlocked_observed",
                "x402_settlement_confirmed_observed",
            },
            "settlement_tx_hash": p.get("settlementTxHash") or p.get("txHash"),
        })
        return ProjectionResult(table="silver_x402_flow_facts", rows=[row])
