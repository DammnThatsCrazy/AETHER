"""Stripe webhook adapter — merchant payment and onramp observability.

Distinct from the billing Stripe provider (``services/billing/providers``):
this adapter observes ``crypto.onramp_session`` lifecycle events and signed
``payment_intent.succeeded`` events. Merchant payments carry only exact amount,
currency, processor IDs, and an optional explicit ``aether_order_ref``. Safe
references only — payment method details never leave the sanitizer.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from services.integrations.providers.payment_rails.base import (
    ParsedProviderEvent,
    PaymentRailAdapter,
    sum_amounts,
)
from services.integrations.providers.payment_rails.models import FundingSession


class StripeOnrampAdapter(PaymentRailAdapter):
    provider_name = "stripe"
    display_name = "Stripe payments and crypto onramp"
    vault_provider_name = "payment_stripe_onramp"
    flows = ("crypto_onramp", "commerce_payment")
    webhook_supported = True
    polling_supported = False
    # Stripe Crypto Onramp observability is webhook-only (onramp session events);
    # a SUPPORTED terminal capability, not an unfinished adapter.
    webhook_only = True
    default_rail = "stripe"
    signature_scheme = "timestamped_hex"  # Stripe `t=…,v1=…` HMAC scheme

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
        if str(event.event_type or "") == "payment_intent.succeeded":
            return self._normalize_payment_intent(tenant_id, event, session)
        if str(event.event_type or "") == "charge.refunded":
            # Refunds are distinct source facts in the commerce evidence ledger,
            # not replacement funding-session states.
            return None
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

    @staticmethod
    def _normalize_payment_intent(
        tenant_id: str, event: ParsedProviderEvent, intent: dict[str, Any]
    ) -> Optional[FundingSession]:
        """Normalize a signed merchant PaymentIntent success.

        Stripe amounts arrive in minor units. Malformed amounts are rejected;
        currencies outside the explicit scale table remain outside order
        reconciliation rather than being guessed or rounded.
        """
        intent_id = str(intent.get("id") or "").strip()
        currency = str(intent.get("currency") or "").strip().upper()
        raw_amount = intent.get("amount_received")
        if raw_amount is None:
            raw_amount = intent.get("amount")
        amount = _stripe_minor_to_major(raw_amount, currency)
        if not intent_id or not currency or amount is None:
            return None

        raw_metadata = intent.get("metadata") or {}
        order_ref = raw_metadata.get("aether_order_ref") if isinstance(raw_metadata, dict) else None
        metadata: dict[str, Any] = {
            "commerce_payment_amount": amount,
            "commerce_payment_currency": currency,
        }
        safe_order_ref = _safe_reference(order_ref, limit=512)
        if safe_order_ref:
            metadata["commerce_order_ref"] = safe_order_ref

        return FundingSession(
            tenant_id=tenant_id,
            provider="stripe",
            flow_type="commerce_payment",
            rail="stripe",
            status="completed",
            provider_status="succeeded",
            actor_kind="service",
            source_amount=amount,
            fiat_currency=currency,
            provider_session_id=intent_id,
            provider_transaction_id=intent_id,
            idempotency_key=f"stripe:payment_intent:{intent_id}",
            occurred_at=event.occurred_at,
            metadata=metadata,
        )

    @staticmethod
    def extract_commerce_adjustments(event: ParsedProviderEvent) -> list[dict[str, str]]:
        """Whitelist explicit Stripe refund facts from a signed charge event."""
        if str(event.event_type or "") != "charge.refunded":
            return []
        charge = (event.payload.get("data") or {}).get("object") or {}
        metadata = charge.get("metadata") or {}
        order_ref = _safe_reference(
            metadata.get("aether_order_ref") if isinstance(metadata, dict) else None,
            limit=512,
        )
        payment_intent_id = _safe_reference(charge.get("payment_intent"), limit=512)
        currency = str(charge.get("currency") or "").upper()
        refunds = (charge.get("refunds") or {}).get("data") or []
        if not order_ref or not payment_intent_id or not currency or not isinstance(refunds, list):
            return []

        results: list[dict[str, str]] = []
        for refund in refunds:
            if not isinstance(refund, dict) or refund.get("status") != "succeeded":
                continue
            refund_id = _safe_reference(refund.get("id"), limit=512)
            amount = _stripe_minor_to_major(refund.get("amount"), currency)
            if not refund_id or amount is None:
                continue
            results.append({
                "commerce_order_ref": order_ref,
                "provider": "stripe",
                "adjustment_id": refund_id,
                "reverses_payment_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "occurred_at": event.occurred_at,
            })
        return results


def _str(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _upper(value: Any) -> Optional[str]:
    return str(value).upper() if value not in (None, "") else None


def _safe_reference(value: Any, *, limit: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    reference = value.strip()
    if not reference or len(reference) > limit or any(
        ord(char) < 32 or ord(char) == 127 for char in reference
    ):
        return None
    return reference


def _stripe_minor_to_major(value: Any, currency: str) -> str | None:
    """Convert a Stripe integer minor-unit amount without float arithmetic."""
    if not currency or not currency.isalpha() or len(currency) != 3:
        return None
    zero_decimal = {
        "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
        "PYG", "RWF", "VND", "VUV", "XAF", "XOF", "XPF",
    }
    two_decimal = {
        "AED", "ARS", "AUD", "BRL", "CAD", "CHF", "CNY", "COP", "CZK",
        "DKK", "EGP", "EUR", "GBP", "HKD", "IDR", "ILS", "INR", "KES",
        "MAD", "MXN", "MYR", "NGN", "NOK", "NZD", "PHP", "PKR", "PLN",
        "QAR", "RON", "SAR", "SEK", "SGD", "THB", "TRY", "UAH",
        "USD", "ZAR",
    }
    if currency not in zero_decimal and currency not in two_decimal:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount != amount.to_integral_value():
        return None
    exponent = 0 if currency in zero_decimal else 2
    return format(amount.scaleb(-exponent), "f")
