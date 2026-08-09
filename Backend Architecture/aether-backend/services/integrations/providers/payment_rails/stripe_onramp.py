"""Stripe crypto onramp adapter — onramp session status observability.

Distinct from the billing Stripe provider (``services/billing/providers``):
this adapter observes ``crypto.onramp_session`` lifecycle events and
normalizes session status, customer reference, wallet, totals, and the
purchased asset/network plus the fulfillment transaction hash. Safe
references only — payment method details never leave the sanitizer.
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.providers.payment_rails.base import (
    ParsedProviderEvent,
    PaymentRailAdapter,
    sum_amounts,
)
from services.integrations.providers.payment_rails.models import FundingSession


class StripeOnrampAdapter(PaymentRailAdapter):
    provider_name = "stripe"
    display_name = "Stripe crypto onramp"
    vault_provider_name = "payment_stripe_onramp"
    flows = ("crypto_onramp",)
    webhook_supported = True
    polling_supported = False
    # Stripe Crypto Onramp observability is webhook-only (onramp session events);
    # a SUPPORTED terminal capability, not an unfinished adapter.
    webhook_only = True
    default_rail = "stripe"
    # Stripe signs webhooks with the compound ``Stripe-Signature: t=<unix>,v1=<hex>``
    # header. Declaring the compound scheme here (not the timestamped_hex
    # placeholder) makes the declaration match what ``native_signature_scheme()``
    # and ``verify_signature`` actually do.
    signature_scheme = "stripe_compound"

    cert_supported_operations = ("webhook_ingest", "normalize", "reconcile")
    cert_unsupported_operations = ("status_poll", "backfill", "reconciliation_pull")
    cert_pagination_model = "none"

    STATUS_MAP: dict[str, str] = {
        "initialized": "initiated",
        "requires_payment": "initiated",
        "fulfillment_processing": "pending",
        "fulfillment_complete": "completed",
        "rejected": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "cancelled",
        "refunded": "refunded",
    }

    def parse_webhook(
        self, tenant_id: str, payload: dict[str, Any], raw_hash: str
    ) -> list[ParsedProviderEvent]:
        event_type = str(payload.get("type") or "crypto.onramp_session_updated")
        session = (payload.get("data") or {}).get("object") or {}
        event_id = payload.get("id") or f"{session.get('id')}:{session.get('status')}"
        occurred_at = payload.get("created")
        if isinstance(occurred_at, (int, float)):
            from datetime import datetime, timezone
            occurred_at = datetime.fromtimestamp(occurred_at, tz=timezone.utc).isoformat()
        return [self._make_event(
            provider_event_id=str(event_id),
            event_type=event_type,
            payload=payload,
            raw_hash=raw_hash,
            occurred_at=occurred_at,
        )]

    def normalize_to_funding_session(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[FundingSession]:
        session = (event.payload.get("data") or {}).get("object") or {}
        session_id = session.get("id")
        if not session_id:
            return None
        provider_status = str(session.get("status") or "")
        details = session.get("transaction_details") or {}
        fees = details.get("fees") or {}
        session_meta = session.get("metadata") or {}
        tx_hash = details.get("transaction_hash") or details.get("transaction_id")

        return FundingSession(
            tenant_id=tenant_id,
            provider="stripe",
            flow_type="crypto_onramp",
            rail="stripe",
            status=self.map_status(provider_status),  # type: ignore[arg-type]
            provider_status=provider_status or None,
            status_reason=session.get("rejection_reason") or session.get("cancellation_reason"),
            actor_kind="human",
            user_id=session_meta.get("user_id"),
            session_id=session_meta.get("session_id"),
            journey_id=session_meta.get("journey_id"),
            campaign_id=session_meta.get("campaign_id"),
            fiat_currency=_upper(details.get("source_currency")),
            source_amount=_str(details.get("source_amount")),
            destination_asset=_upper(details.get("destination_currency")),
            destination_chain=details.get("destination_network"),
            destination_amount=_str(details.get("destination_amount")),
            destination_address=details.get("wallet_address"),
            fee_amount=sum_amounts(fees.get("network_fee"), fees.get("transaction_fee")),
            fee_currency=_upper(details.get("source_currency")),
            provider_session_id=str(session_id),
            provider_transaction_id=_str(details.get("transaction_id")),
            provider_customer_ref=_str(session.get("customer")),
            tx_hash=_str(tx_hash),
            idempotency_key=f"stripe:{session_id}",
            occurred_at=event.occurred_at,
        )


def _str(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _upper(value: Any) -> Optional[str]:
    return str(value).upper() if value not in (None, "") else None
