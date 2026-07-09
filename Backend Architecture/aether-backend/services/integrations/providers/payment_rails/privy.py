"""Privy payment rail adapter — fiat onramp / bank deposit / crypto deposit
address observability.

Privy funding flows frequently route through an underlying processor
(Stripe, MoonPay, Coinbase, Meld); the underlying processor is preserved as
``provider_detail`` plus a sanitized ``metadata.underlying`` block so
reconciliation against the underlying provider's own truth is possible when
both are observed. Journey/campaign/actor/user/wallet/chain/asset/source-
currency/session context is preserved on the canonical funding session.

Observation-only: Privy executes the flows; Aether records them.
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.providers.payment_rails.base import (
    ParsedProviderEvent,
    PaymentRailAdapter,
)
from services.integrations.providers.payment_rails.models import FundingSession

_KNOWN_PROCESSORS = ("stripe", "moonpay", "coinbase", "meld")

_FLOW_RAILS = {
    "fiat_onramp": "fiat",
    "bank_deposit": "bank_transfer",
    "crypto_deposit": "onchain",
}


class PrivyAdapter(PaymentRailAdapter):
    provider_name = "privy"
    display_name = "Privy"
    vault_provider_name = "payment_privy"
    flows = ("fiat_onramp", "bank_deposit", "crypto_deposit")
    webhook_supported = True
    polling_supported = False
    default_rail = "fiat"
    signature_scheme = "timestamped_hex"

    STATUS_MAP: dict[str, str] = {
        "created": "initiated",
        "initiated": "initiated",
        "awaiting_payment": "initiated",
        "awaiting_funds": "initiated",
        "submitted": "submitted",
        "processing": "pending",
        "confirming": "pending",
        "confirmed": "completed",
        "completed": "completed",
        "succeeded": "completed",
        "failed": "failed",
        "errored": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "refunded": "refunded",
    }

    def parse_webhook(
        self, tenant_id: str, payload: dict[str, Any], raw_hash: str
    ) -> list[ParsedProviderEvent]:
        event_type = str(payload.get("type") or payload.get("event") or "privy.event")
        data = payload.get("data") or {}
        event_id = payload.get("id") or (
            f"{data.get('funding_id') or data.get('id')}:{data.get('status')}"
        )
        return [self._make_event(
            provider_event_id=str(event_id),
            event_type=event_type,
            payload=payload,
            raw_hash=raw_hash,
            occurred_at=payload.get("created_at") or data.get("updated_at"),
        )]

    def normalize_to_funding_session(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[FundingSession]:
        if event.event_type.startswith("deposit_address."):
            return None  # side record only (see extract_deposit_address)
        data = event.payload.get("data") or {}
        funding_id = data.get("funding_id") or data.get("id")
        if not funding_id:
            return None
        flow_type = str(data.get("flow") or data.get("flow_type") or "fiat_onramp")
        if flow_type not in self.flows:
            flow_type = "fiat_onramp"
        provider_status = str(data.get("status") or "")
        status = self.map_status(provider_status)

        processor = str(data.get("provider") or data.get("processor") or "").lower() or None
        provider_detail = processor if processor in _KNOWN_PROCESSORS else processor

        agent_id = data.get("agent_id")
        actor_kind = str(data.get("actor_kind") or ("agent" if agent_id else "human"))

        metadata: dict[str, Any] = {}
        if provider_detail:
            metadata["underlying"] = {
                "provider": provider_detail,
                "transaction_id": data.get("provider_transaction_id"),
            }

        return FundingSession(
            tenant_id=tenant_id,
            provider="privy",
            provider_detail=provider_detail,
            flow_type=flow_type,  # type: ignore[arg-type]
            rail=_FLOW_RAILS.get(flow_type, self.default_rail),  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            provider_status=provider_status or None,
            status_reason=data.get("failure_reason") or data.get("status_reason"),
            actor_kind=actor_kind,  # type: ignore[arg-type]
            user_id=data.get("user_id"),
            agent_id=agent_id,
            org_id=data.get("org_id"),
            session_id=data.get("session_id"),
            device_id=data.get("device_id"),
            journey_id=data.get("journey_id"),
            campaign_id=data.get("campaign_id"),
            source_asset=data.get("source_asset"),
            source_chain=data.get("source_chain"),
            source_amount=_amount(data.get("source_amount") or data.get("amount")),
            fiat_currency=_upper(data.get("source_currency") or data.get("fiat_currency")),
            destination_asset=_upper(data.get("asset") or data.get("destination_asset")),
            destination_chain=data.get("chain") or data.get("destination_chain"),
            destination_amount=_amount(data.get("destination_amount")),
            destination_address=data.get("wallet_address") or data.get("destination_address"),
            fee_amount=_amount(data.get("fee_amount")),
            fee_currency=_upper(data.get("fee_currency") or data.get("source_currency")),
            provider_session_id=str(funding_id),
            provider_transaction_id=data.get("provider_transaction_id"),
            provider_customer_ref=data.get("user_id"),
            deposit_address_id=data.get("deposit_address_id"),
            tx_hash=data.get("tx_hash") or data.get("transaction_hash"),
            idempotency_key=f"privy:{funding_id}",
            occurred_at=event.occurred_at,
            metadata=metadata,
        )

    def extract_deposit_address(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[dict[str, Any]]:
        if not event.event_type.startswith("deposit_address."):
            return None
        data = event.payload.get("data") or {}
        address = data.get("address")
        if not address:
            return None
        return {
            "tenant_id": tenant_id,
            "provider": "privy",
            "provider_address_id": data.get("id") or data.get("deposit_address_id"),
            "address": address,
            "chain": data.get("chain") or "unknown",
            "asset": _upper(data.get("asset")),
            "user_id": data.get("user_id"),
            "wallet_id": data.get("wallet_id"),
            "status": "inactive" if event.event_type.endswith(".deactivated") else "active",
        }


def _amount(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _upper(value: Any) -> Optional[str]:
    return str(value).upper() if value not in (None, "") else None
