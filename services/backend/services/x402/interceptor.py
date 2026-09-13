"""
Aether Service — x402 Interceptor
Captures 3 HTTP headers for agent-to-service micropayments:
  1. PAYMENT-REQUIRED  (402 response -> payment terms)
  2. X-PAYMENT          (client request -> payment proof)
  3. X-PAYMENT-RESPONSE (server response -> confirmation)

All captured payments are routed to the economic graph and commerce service.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from services.value.models import to_decimal

from .models import (
    CapturedX402Transaction,
    PaymentProof,
    PaymentResponse,
    PaymentTerms,
)

logger = get_logger("aether.service.x402.interceptor")

# Card fee rate for computing fee_eliminated_usd
CARD_FEE_RATE = 0.029
# Exact decimal fee factor (mirror of CARD_FEE_RATE). Fee elimination is money
# arithmetic: amount * rate is computed in Decimal so a fractional amount never
# produces a binary-float artifact at the round boundary (e.g. $0.05 * 2.9%
# yields 0.0014500000000000001 in float but exactly 0.00145 in Decimal, which
# rounds half-even to 0.0014 — not 0.0015).
_FEE_FACTOR_DEC = Decimal(str(CARD_FEE_RATE))
_FEE_ROUND = Decimal("0.0001")  # 4 dp, mirrors the legacy round(..., 4)

# Maximum header value size (8 KB)
_MAX_HEADER_SIZE = 8192

# Maximum in-memory captures before eviction (prevents OOM)
_MAX_CAPTURES = 10_000


class X402Interceptor:
    """
    Captures x402 HTTP payment headers and constructs transaction records.
    In production, sits as middleware or sidecar proxy.
    """

    def __init__(self, event_producer: Optional[EventProducer] = None):
        self._producer = event_producer or EventProducer()
        self._captures: list[CapturedX402Transaction] = []

    def parse_payment_required(self, header_value: str) -> PaymentTerms:
        """Parse PAYMENT-REQUIRED header (402 response)."""
        if len(header_value) > _MAX_HEADER_SIZE:
            raise ValueError("Header value too large")

        if not header_value.startswith("{"):
            raise ValueError("Malformed payment header")

        data = json.loads(header_value)

        # Validate amount is a positive number
        if not isinstance(data.get("amount"), (int, float)) or data.get("amount", 0) < 0:
            raise ValueError("Invalid amount")

        return PaymentTerms(
            amount=data.get("amount", 0.0),
            token=data.get("token", "USDC"),
            chain=data.get("chain", "eip155:1"),
            recipient=data.get("recipient", ""),
            memo=data.get("memo"),
            expires_at=data.get("expires_at"),
        )

    def parse_payment_proof(self, header_value: str) -> PaymentProof:
        """Parse X-PAYMENT header (client request with payment proof)."""
        if len(header_value) > _MAX_HEADER_SIZE:
            raise ValueError("Header value too large")

        if not header_value.startswith("{"):
            raise ValueError("Malformed payment header")

        data = json.loads(header_value)

        # Validate amount is a positive number
        if not isinstance(data.get("amount"), (int, float)) or data.get("amount", 0) < 0:
            raise ValueError("Invalid amount")

        return PaymentProof(
            tx_hash=data.get("tx_hash", ""),
            payer=data.get("payer", ""),
            chain=data.get("chain", "eip155:1"),
            amount=data.get("amount", 0.0),
            token=data.get("token", "USDC"),
        )

    def parse_payment_response(self, header_value: str) -> PaymentResponse:
        """Parse X-PAYMENT-RESPONSE header (server confirmation)."""
        if len(header_value) > _MAX_HEADER_SIZE:
            raise ValueError("Header value too large")

        if not header_value.startswith("{"):
            raise ValueError("Malformed payment header")

        data = json.loads(header_value)
        return PaymentResponse(
            verified=data.get("verified", False),
            receipt_id=data.get("receipt_id"),
            settled_at=data.get("settled_at"),
        )

    async def capture(
        self,
        payer_agent_id: str,
        payee_service_id: str,
        terms: PaymentTerms,
        proof: Optional[PaymentProof] = None,
        response: Optional[PaymentResponse] = None,
        request_url: str = "",
        request_method: str = "GET",
    ) -> CapturedX402Transaction:
        """Capture a complete x402 transaction from parsed headers."""
        amount_usd = terms.amount  # Assumes stablecoin / USD-denominated
        # Fee elimination is money math — convert to Decimal at the boundary and
        # round half-even at 4 dp. The float value written to the wire model is
        # produced from the exact decimal only after the arithmetic is done.
        amount_dec = to_decimal(amount_usd)
        if amount_dec is None:
            raise ValueError("Invalid amount")  # unparseable amount is never 0
        fee_dec = (amount_dec * _FEE_FACTOR_DEC).quantize(
            _FEE_ROUND, rounding=ROUND_HALF_EVEN
        )
        fee_eliminated = float(fee_dec)

        tx = CapturedX402Transaction(
            capture_id=str(uuid.uuid4()),
            payer_agent_id=payer_agent_id,
            payee_service_id=payee_service_id,
            terms=terms,
            proof=proof,
            response=response,
            request_url=request_url,
            request_method=request_method,
            amount_usd=amount_usd,
            fee_eliminated_usd=fee_eliminated,
        )

        # Record capture locally (evict oldest if at capacity)
        if len(self._captures) >= _MAX_CAPTURES:
            self._captures = self._captures[-(_MAX_CAPTURES // 2):]
            logger.warning(f"x402 capture buffer evicted: trimmed to {len(self._captures)} entries")
        self._captures.append(tx)

        # Publish event (non-critical — capture still succeeds if publish fails)
        try:
            await self._producer.publish(Event(
                topic=Topic.X402_PAYMENT_CAPTURED,
                payload=tx.model_dump(),
                source_service="x402",
            ))
        except Exception as e:
            logger.error(f"Failed to publish x402 capture event: {e}")

        metrics.increment("x402_payments_captured", labels={"chain": terms.chain})
        logger.info(
            f"x402 captured: {tx.capture_id} | {payer_agent_id}->{payee_service_id} "
            f"| ${amount_usd} {terms.token} on {terms.chain}"
        )
        return tx

    @property
    def capture_count(self) -> int:
        return len(self._captures)

    def get_captures(self, agent_id: Optional[str] = None) -> list[CapturedX402Transaction]:
        """Get captured transactions, optionally filtered by agent."""
        if agent_id:
            return [c for c in self._captures if c.payer_agent_id == agent_id]
        return list(self._captures)
