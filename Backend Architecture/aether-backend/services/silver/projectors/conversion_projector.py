"""Silver conversion projector — Bronze event → canonical_conversions with authority ranking."""

from __future__ import annotations

import hashlib
from typing import Any

from services.silver.projectors.base import BaseProjector, ProjectionResult

# Source authority ranking — higher wins on conflict
_AUTHORITY_RANK: dict[str, int] = {
    "order_completed": 90,       # Commerce webhook (Shopify, Stripe)
    "payment_confirmed": 90,     # Commerce webhook
    "x402_settled": 90,          # On-chain settlement (highest authority)
    "subscription_started": 80,  # Server-confirmed
    "opportunity_closed_won": 70,# CRM
    "lead_created": 60,          # CRM / server
    "trial_started": 50,         # Client-observed
    "reward_redeemed": 50,       # Rewards system
    "signup_completed": 50,      # Client-observed
    "checkout_completed": 80,    # Commerce webhook
}

_CONVERSION_TYPE_MAP: dict[str, str] = {
    "order_completed": "purchase",
    "payment_confirmed": "payment",
    "lead_created": "lead",
    "trial_started": "trial",
    "subscription_started": "subscription",
    "opportunity_closed_won": "closed_won",
    "x402_settled": "x402_settlement",
    "reward_redeemed": "reward_redemption",
    "signup_completed": "signup",
    "checkout_completed": "purchase",
}


class ConversionProjector(BaseProjector):
    """Projects commerce/conversion events into canonical_conversions.

    Authority ranking ensures the most-authoritative source record wins.
    A lower-authority event arriving later for the same dedup_key is
    preserved in evidence_ids but does not overwrite the canonical row.

    Idempotency: sha256(tenant_id + source_event_id + conversion_type).
    """

    handles: frozenset[str] = frozenset(_CONVERSION_TYPE_MAP.keys())

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        ctx = event.get("context") or {}
        props = event.get("properties") or {}

        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        event_type = event.get("type", "")
        conversion_type = _CONVERSION_TYPE_MAP.get(event_type)

        if not conversion_type:
            return ProjectionResult(table="canonical_conversions", rows=[], skipped=True, skip_reason="unknown_event_type")

        source_event_id = event.get("messageId") or event.get("id")
        authority_rank = _AUTHORITY_RANK.get(event_type, 50)

        # Deduplication key — stable across re-deliveries of the same commercial event
        order_id = props.get("order_id") or props.get("orderId")
        payment_id = props.get("payment_id") or props.get("paymentId")
        external_id = props.get("external_conversion_id") or props.get("externalId")
        natural_key = order_id or payment_id or external_id or source_event_id
        dedup_key = hashlib.sha256(
            f"{tenant_id}:{conversion_type}:{natural_key}".encode()
        ).hexdigest()

        gross_value = _safe_num(
            props.get("revenue") or props.get("gross_value") or props.get("total") or props.get("amount")
        )
        discount_value = _safe_num(props.get("discount") or props.get("discount_value"))
        tax_value = _safe_num(props.get("tax") or props.get("tax_value"))
        shipping_value = _safe_num(props.get("shipping") or props.get("shipping_value"))
        refund_value = _safe_num(props.get("refund") or props.get("refund_value"))

        row: dict[str, Any] = {
            "tenant_id": tenant_id,
            "conversion_type": conversion_type,
            "conversion_name": props.get("conversion_name") or props.get("event_name"),
            "goal_id": props.get("goal_id"),
            "profile_id": event.get("userId"),
            "cluster_id": ctx.get("clusterId"),
            "account_id": ctx.get("accountId") or props.get("account_id"),
            "organization_id": ctx.get("orgId"),
            "wallet_id": ctx.get("walletId") or props.get("wallet_id"),
            "agent_id": ctx.get("agentId"),
            "order_id": order_id,
            "payment_id": payment_id,
            "subscription_id": props.get("subscription_id") or props.get("subscriptionId"),
            "invoice_id": props.get("invoice_id"),
            "opportunity_id": props.get("opportunity_id"),
            "transaction_hash": props.get("transaction_hash") or props.get("txHash"),
            "external_conversion_id": external_id,
            "gross_value": gross_value,
            "discount_value": discount_value or "0",
            "tax_value": tax_value or "0",
            "shipping_value": shipping_value or "0",
            "refund_value": refund_value or "0",
            "currency": props.get("currency", "USD"),
            "normalized_currency": "USD",
            "exchange_rate": "1.0",
            "quantity": int(props.get("quantity", 1)),
            "product_ids": props.get("product_ids") or _extract_product_ids(props),
            "line_items": props.get("products") or props.get("line_items") or [],
            "occurred_at": event.get("timestamp") or props.get("occurred_at"),
            "observed_at": event.get("receivedAt") or event.get("timestamp"),
            "confirmed_at": props.get("confirmed_at"),
            "conversion_status": "confirmed",
            "conversion_source": event_type,
            "authority_rank": authority_rank,
            "deduplication_key": dedup_key,
            "attribution_eligible": True,
            "consent_snapshot_id": ctx.get("consentSnapshotId"),
            "identity_version": ctx.get("identityVersion"),
            "provenance": {"source_event_type": event_type, "source_event_id": source_event_id},
            "evidence_ids": [source_event_id] if source_event_id else [],
            "source_connector_id": ctx.get("sourceConnectorId"),
            "source_event_id": source_event_id,
            "schema_version": 1,
        }

        return ProjectionResult(table="canonical_conversions", rows=[row])


def _safe_num(value: Any) -> str | None:
    if value is None:
        return None
    try:
        from decimal import Decimal
        return str(Decimal(str(value)))
    except Exception:
        return None


def _extract_product_ids(props: dict[str, Any]) -> list[str]:
    products = props.get("products") or []
    ids = []
    for p in products:
        if isinstance(p, dict):
            pid = p.get("product_id") or p.get("id")
            if pid:
                ids.append(str(pid))
    return ids
