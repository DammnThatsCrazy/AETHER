"""Silver projector for web3 and web3 lifecycle events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_WEB3_TYPES = frozenset({
    # SDK canonical event names. A client transaction event is only a source
    # observation; it must not be mistaken for verified payment/finality.
    "wallet",
    "transaction",
    "wallet_connected",
    "wallet_disconnected",
    "transaction_initiated",
    "transaction_submitted",
    "transaction_confirmed",
    "transaction_failed",
    "contract_action",
    "transaction_pending_observed",
    "transaction_confirmed_observed",
    "transaction_reverted_observed",
    "transaction_reorged_observed",
    "token_approval_observed",
    "allowance_changed_observed",
    "bridge_transfer_observed",
    "settlement_finality_observed",
})


class Web3TransactionProjector(BaseProjector):
    handles = _WEB3_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        event_type = str(event.get("type") or "")
        action = str(p.get("action") or "").strip().lower()
        if event_type == "wallet":
            status = {
                "connect": "wallet_connected_observed",
                "disconnect": "wallet_disconnected_observed",
            }.get(action, "wallet_state_unknown")
        elif event_type == "transaction":
            status = "source_observed"
        else:
            status = p.get("status")
        row.update({
            "tx_hash": p.get("txHash") or p.get("transactionHash"),
            "chain_id": p.get("chainId") or p.get("chain_id"),
            "contract_address": p.get("contractAddress") or p.get("to"),
            "from_address": p.get("from") or p.get("walletAddress") or p.get("address"),
            "to_address": p.get("to") or p.get("contractAddress"),
            "value_wei": str(p.get("value") or ""),
            "status": status,
            "token_address": p.get("tokenAddress"),
            "allowance_amount": str(p.get("allowance") or ""),
        })
        return ProjectionResult(table="silver_web3_transaction_facts", rows=[row])
