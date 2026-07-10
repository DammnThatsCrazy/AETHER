"""Bridge (bridge.xyz) payment rail adapter — virtual account and activity
observability.

Bridge issues virtual bank accounts whose deposits settle to crypto
destinations. Aether observes virtual-account state and activity history
(via Bridge-shaped webhooks and polling); account references are stored
masked — full bank account or routing numbers are never persisted.

Observation-only: Bridge executes settlement; Aether records it.
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.providers.payment_rails.base import (
    ParsedProviderEvent,
    PaymentRailAdapter,
)
from services.integrations.providers.payment_rails.models import FundingSession

_ACTIVITY_FLOWS = {
    "payment_submitted": "bank_deposit",
    "payment_processed": "bank_deposit",
    "funds_received": "bank_deposit",
    "payment_returned": "refund",
    "refund": "refund",
    "payout": "settlement",
    "payment_sent": "settlement",
}


class BridgeAdapter(PaymentRailAdapter):
    provider_name = "bridge"
    display_name = "Bridge"
    vault_provider_name = "payment_bridge"
    flows = ("bank_deposit", "settlement", "refund")
    webhook_supported = True
    polling_supported = True
    default_rail = "bridge"
    signature_scheme = "timestamped_hex"

    STATUS_MAP: dict[str, str] = {
        "created": "initiated",
        "awaiting_funds": "initiated",
        "submitted": "submitted",
        "in_review": "pending",
        "processing": "pending",
        "funds_received": "pending",
        "payment_submitted": "submitted",
        "payment_processed": "completed",
        "processed": "completed",
        "completed": "completed",
        "payment_returned": "refunded",
        "returned": "refunded",
        "refunded": "refunded",
        "failed": "failed",
        "error": "failed",
        "canceled": "cancelled",
        "cancelled": "cancelled",
    }

    def parse_webhook(
        self, tenant_id: str, payload: dict[str, Any], raw_hash: str
    ) -> list[ParsedProviderEvent]:
        event_type = str(payload.get("event_type") or payload.get("type") or "bridge.event")
        data = dict(payload.get("event_object") or payload.get("data") or {})
        # The masked reference is derived BEFORE sanitization strips the raw
        # bank account number; only the last four digits ever survive parsing.
        deposit = data.get("source_deposit_instructions") or {}
        account_number = str(deposit.get("bank_account_number") or "")
        if account_number:
            data["masked_account_ref"] = f"****{account_number[-4:]}"
        event_id = (
            payload.get("event_id")
            or payload.get("id")
            or f"{data.get('id')}:{data.get('status') or data.get('type')}"
        )
        return [self._make_event(
            provider_event_id=str(event_id),
            event_type=event_type,
            payload={"data": data, "event_type": event_type},
            raw_hash=raw_hash,
            occurred_at=payload.get("event_created_at") or data.get("updated_at"),
        )]

    def normalize_to_funding_session(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[FundingSession]:
        data = event.payload.get("data") or {}
        if "virtual_account" in event.event_type and "activity" not in event.event_type:
            return None  # account lifecycle only (see extract_virtual_account)

        activity_id = data.get("id") or data.get("deposit_id")
        if not activity_id:
            return None

        activity_type = str(data.get("type") or data.get("activity_type") or "funds_received")
        flow_type = _ACTIVITY_FLOWS.get(activity_type, "bank_deposit")
        provider_status = str(data.get("status") or activity_type)
        status = self.map_status(provider_status)

        source = data.get("source") or {}
        destination = data.get("destination") or {}
        source_rail = str(source.get("payment_rail") or "").lower()
        rail = source_rail if source_rail in ("ach", "wire", "sepa") else "bridge"

        return FundingSession(
            tenant_id=tenant_id,
            provider="bridge",
            flow_type=flow_type,  # type: ignore[arg-type]
            rail=rail,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            provider_status=provider_status or None,
            status_reason=data.get("return_reason") or data.get("failure_reason"),
            actor_kind="human",
            user_id=data.get("external_user_id"),
            org_id=data.get("external_org_id"),
            source_amount=_amount(data.get("amount")),
            fiat_currency=_upper(source.get("currency") or data.get("currency")),
            destination_asset=_upper(destination.get("currency")),
            destination_chain=destination.get("payment_rail") or destination.get("chain"),
            destination_amount=_amount(data.get("destination_amount") or data.get("amount")),
            destination_address=destination.get("address") or destination.get("to_address"),
            fee_amount=_amount(_fee(data)),
            fee_currency=_upper(source.get("currency") or data.get("currency")),
            provider_session_id=str(activity_id),
            provider_transaction_id=data.get("deposit_id") or str(activity_id),
            provider_customer_ref=data.get("customer_id"),
            virtual_account_id=data.get("virtual_account_id"),
            tx_hash=destination.get("transaction_hash") or data.get("destination_tx_hash"),
            idempotency_key=f"bridge:{activity_id}",
            occurred_at=event.occurred_at,
            metadata={"activity_type": activity_type},
        )

    def extract_virtual_account(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[dict[str, Any]]:
        if "virtual_account" not in event.event_type or "activity" in event.event_type:
            return None
        data = event.payload.get("data") or {}
        account_id = data.get("id") or data.get("virtual_account_id")
        if not account_id:
            return None
        deposit = data.get("source_deposit_instructions") or {}
        destination = data.get("destination") or {}
        return {
            "tenant_id": tenant_id,
            "provider": "bridge",
            "provider_virtual_account_id": str(account_id),
            "provider_customer_ref": data.get("customer_id"),
            # Masked reference only (pre-computed in parse_webhook before
            # sanitization) — never the full account/routing number.
            "masked_account_ref": data.get("masked_account_ref"),
            "currency": _upper(deposit.get("currency") or data.get("currency")),
            "destination_address": destination.get("address"),
            "destination_chain": destination.get("payment_rail") or destination.get("chain"),
            "status": "deactivated" if str(data.get("status")).lower() == "deactivated" else "active",
        }

    def _parse_poll_records(
        self, tenant_id: str, records: list[dict[str, Any]], **params: Any
    ) -> list[ParsedProviderEvent]:
        events: list[ParsedProviderEvent] = []
        for record in records:
            record_id = record.get("id")
            if not record_id:
                continue
            record_kind = "virtual_account" if record.get("source_deposit_instructions") else (
                "virtual_account.activity"
            )
            events.append(self._make_event(
                provider_event_id=f"{record_id}:{record.get('status') or record.get('type')}",
                event_type=f"{record_kind}_polled" if record_kind == "virtual_account" else
                "virtual_account.activity_polled",
                payload={"data": record},
                occurred_at=record.get("updated_at") or record.get("created_at"),
                source="polling",
            ))
        return events


def _amount(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _upper(value: Any) -> Optional[str]:
    return str(value).upper() if value not in (None, "") else None


def _fee(data: dict[str, Any]) -> Any:
    fee = data.get("developer_fee") or data.get("fee")
    if isinstance(fee, dict):
        return fee.get("amount")
    return fee
