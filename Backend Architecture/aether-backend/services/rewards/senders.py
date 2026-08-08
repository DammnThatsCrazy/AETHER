"""Reward-rail sender indirection for the durable delivery outbox.

The outbox used to hardcode ``TenantWebhookAdapter`` and could dispatch only
``tenant_webhook``. This registry maps each deliverable rail to a ``RailSender``
so the SAME durable, leased, receipt-backed outbox delivers every rail
(webhook, internal ledger, Stripe credit, x402 credit). Rails that do not
deliver through the outbox (recommend_only / manual_* / onchain_claim) declare
``manual`` and are never enqueued.

``RAIL_SENDERS`` is validated bidirectionally against ``rails._RAIL_ADAPTERS``
and ``rail_matrix.RAIL_MATRIX`` by ``check_reward_rail_matrix.py`` — a new rail
without a sender classification is a fail-closed error.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Awaitable, Callable, Optional, Protocol

from shared.logger.logger import get_logger

logger = get_logger("aether.rewards.senders")


class SenderResult:
    """Outcome of a send attempt (mirrors the outbox's existing shape)."""

    def __init__(
        self,
        outcome: str,               # success | retryable | fatal
        *,
        external_id: Optional[str] = None,
        response_code: Optional[int] = None,
        error: Optional[str] = None,
        raw: Optional[dict] = None,
    ) -> None:
        self.outcome = outcome
        self.external_id = external_id
        self.response_code = response_code
        self.error = error
        self.raw = raw or {}


class RailSender(Protocol):
    delivery_mode: str  # sync_api | onchain_claim | internal_ledger | manual

    async def send(self, job: dict) -> SenderResult: ...


# ── internal_credit ────────────────────────────────────────────────────────


class InternalCreditSender:
    delivery_mode = "internal_ledger"

    async def send(self, job: dict) -> SenderResult:
        from services.rewards.credit_ledger import get_internal_credit_ledger

        pc = job.get("provider_config") or {}
        payload = job.get("payload") or {}
        recipient = payload.get("recipient_id") or pc.get("recipient_id")
        amount = Decimal(str(payload.get("amount", pc.get("amount", "0"))))
        idem = payload.get("idempotency_key") or job.get("idempotency_key")
        if not recipient or amount <= 0 or not idem:
            return SenderResult("fatal", error="internal_credit missing recipient/amount/idempotency")
        entry = await get_internal_credit_ledger().credit(
            tenant_id=job.get("tenant_id", ""),
            recipient_id=recipient,
            campaign_id=payload.get("campaign_id", ""),
            amount=amount,
            currency=payload.get("currency", "USD"),
            idempotency_key=idem,
            action_id=job.get("action_id"),
        )
        return SenderResult("success", external_id=entry.get("id"))


# ── stripe_credit ──────────────────────────────────────────────────────────


class StripeCreditSender:
    delivery_mode = "sync_api"

    async def send(self, job: dict) -> SenderResult:
        pc = job.get("provider_config") or {}
        payload = job.get("payload") or {}
        tenant_id = job.get("tenant_id", "")
        idem = payload.get("idempotency_key") or job.get("idempotency_key")

        # Resolve the tenant's Stripe key from the credential authority.
        secret_ref = pc.get("secret_ref") or payload.get("secret_ref")
        try:
            from services.providers.credentials.authority import credential_authority
            from services.rewards.webhook_secret import credential_environment

            env = credential_environment()
            key = await credential_authority.get_active_secret(
                tenant_id, "stripe_credit", env, "server_api_key"
            )
        except Exception:  # noqa: BLE001
            key = None
        if not key:
            return SenderResult(
                "fatal",
                error="no active Stripe credential for tenant "
                "(provider=stripe_credit slot=server_api_key)",
            )

        customer = payload.get("customer_ref") or pc.get("stripe_customer_id")
        if not customer:
            return SenderResult("fatal", error="no Stripe customer reference on the reward action")

        amount = Decimal(str(payload.get("amount", "0")))
        currency = payload.get("currency", "usd")
        # Customer-balance credit is a NEGATIVE balance transaction in Stripe
        # (a credit reduces what the customer owes). Idempotent via idem key.
        try:
            result = await self._stripe_customer_balance_credit(
                key, customer, amount, currency, idem
            )
        except _StripeRetryable as exc:
            return SenderResult("retryable", error=str(exc))
        except Exception as exc:  # noqa: BLE001 — provider/client error
            return SenderResult("fatal", error=f"stripe credit failed: {exc}")
        return SenderResult("success", external_id=result.get("id"))

    async def _stripe_customer_balance_credit(
        self, api_key: str, customer: str, amount: Decimal, currency: str, idem: str
    ) -> dict:
        """Idempotent Stripe customer-balance credit transaction.

        Amounts are minor units (cents). Uses Stripe's Idempotency-Key so a
        redelivered outbox job never double-credits. In local/test (no network)
        returns a deterministic stub so the flow is exercisable offline.
        """
        import os

        minor = int((amount * Decimal(100)).to_integral_value())
        if os.getenv("AETHER_ENV", "local").lower() in ("local", "test"):
            return {"id": f"cbt_local_{idem[:16]}", "amount": -minor, "currency": currency}

        import httpx

        url = f"https://api.stripe.com/v1/customers/{customer}/balance_transactions"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Idempotency-Key": f"reward-{idem}",
                    },
                    data={"amount": -minor, "currency": currency},
                )
        except httpx.TimeoutException as exc:
            raise _StripeRetryable(f"stripe timeout: {exc}") from exc
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _StripeRetryable(f"stripe {resp.status_code}")
        raise RuntimeError(f"stripe {resp.status_code}: {resp.text[:200]}")


class _StripeRetryable(Exception):
    pass


# ── x402_credit ────────────────────────────────────────────────────────────


class X402CreditSender:
    delivery_mode = "internal_ledger"

    async def send(self, job: dict) -> SenderResult:
        """Record an x402 reward credit grant (sandbox/explicit-beta).

        No custody: this posts a credit grant into the internal ledger tagged
        as x402-origin (a full commerce-control-plane authorization is the
        live-tier path, gated on external facilitator credentials).
        """
        from services.rewards.credit_ledger import get_internal_credit_ledger

        payload = job.get("payload") or {}
        recipient = payload.get("recipient_id")
        amount = Decimal(str(payload.get("amount", "0")))
        idem = payload.get("idempotency_key") or job.get("idempotency_key")
        if not recipient or amount <= 0 or not idem:
            return SenderResult("fatal", error="x402_credit missing recipient/amount/idempotency")
        entry = await get_internal_credit_ledger().credit(
            tenant_id=job.get("tenant_id", ""),
            recipient_id=recipient,
            campaign_id=payload.get("campaign_id", ""),
            amount=amount,
            currency=payload.get("currency", "USD"),
            idempotency_key=f"x402:{idem}",
            action_id=job.get("action_id"),
        )
        return SenderResult("success", external_id=entry.get("id"))


# ── tenant_webhook (delegates to the existing hardened sender) ─────────────


class WebhookSenderShim:
    delivery_mode = "sync_api"

    async def send(self, job: dict) -> SenderResult:
        from services.rewards.delivery_outbox import RewardWebhookSender
        from services.rewards.delivery_outbox import SenderResult as _OutboxSenderResult  # noqa: F401

        result = await RewardWebhookSender().send(job)
        return SenderResult(
            result.outcome,
            external_id=result.external_id,
            response_code=result.response_code,
            error=result.error,
            raw=result.raw,
        )


# ── registry ────────────────────────────────────────────────────────────────

# Rails delivered through the outbox → their sender. Rails NOT here declare a
# manual/none delivery mode in the rail matrix and are never enqueued.
RAIL_SENDERS: dict[str, RailSender] = {
    "tenant_webhook": WebhookSenderShim(),
    "internal_credit": InternalCreditSender(),
    "stripe_credit": StripeCreditSender(),
    "x402_credit": X402CreditSender(),
}


def get_sender(rail: str) -> Optional[RailSender]:
    return RAIL_SENDERS.get(rail)


def has_sender(rail: str) -> bool:
    return rail in RAIL_SENDERS


__all__ = [
    "RailSender",
    "SenderResult",
    "RAIL_SENDERS",
    "get_sender",
    "has_sender",
    "InternalCreditSender",
    "StripeCreditSender",
    "X402CreditSender",
    "WebhookSenderShim",
]
