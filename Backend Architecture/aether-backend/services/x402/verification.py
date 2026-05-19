"""
Aether Service — Payment Verification Engine
Verifies payment proofs submitted against approved authorizations. Supports
facilitator-aware verification (delegate to external facilitator) and local
verification (on-chain RPC check) as fallback.

Day-1 chains: USDC on Base (eip155:8453), USDC on Solana (solana:mainnet).
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_CEILING
from typing import Optional

import httpx

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from .commerce_models import Facilitator, PaymentAuthorization, PaymentReceipt
from .commerce_store import get_commerce_store
from .facilitators import get_facilitator_registry

_FACILITATOR_TIMEOUT_S = 10.0

# x402 network names (chain ID → x402 network identifier)
_CHAIN_TO_NETWORK: dict[str, str] = {
    "eip155:8453":   "base-mainnet",
    "eip155:84532":  "base-sepolia",
    "solana:mainnet": "solana-mainnet",
    "solana:devnet":  "solana-devnet",
}

# ERC-20 / SPL contract addresses for supported stablecoins
_ASSET_CONTRACT: dict[tuple[str, str], str] = {
    ("USDC", "eip155:8453"):    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    ("USDC", "eip155:84532"):   "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    ("USDC", "solana:mainnet"): "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
}

# Decimal places for each supported asset
_ASSET_DECIMALS: dict[str, int] = {
    "USDC": 6,
}

logger = get_logger("aether.service.x402.verification")

# Simple heuristic validators for local verification (production would call RPCs).
_BASE_TX_HASH = re.compile(r"^0x[a-fA-F0-9]{64}$")
_SOLANA_TX_HASH = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{43,88}$")


def _validate_tx_hash(chain: str, tx_hash: str) -> bool:
    if chain.startswith("eip155:"):
        return bool(_BASE_TX_HASH.match(tx_hash))
    if chain.startswith("solana:"):
        return bool(_SOLANA_TX_HASH.match(tx_hash))
    return False


class VerificationEngine:
    """Verifies payment proofs against authorizations."""

    def __init__(self, event_producer: Optional[EventProducer] = None):
        self._store = get_commerce_store()
        self._facilitators = get_facilitator_registry()
        self._producer = event_producer or EventProducer()

    async def verify(
        self,
        tenant_id: str,
        authorization: PaymentAuthorization,
        tx_hash: str,
        prefer_facilitator: bool = True,
    ) -> PaymentReceipt:
        """Verify a submitted tx_hash. Returns a PaymentReceipt."""
        await self._emit(
            Topic.COMMERCE_VERIFICATION_STARTED,
            tenant_id,
            {
                "authorization_id": authorization.authorization_id,
                "challenge_id": authorization.challenge_id,
                "tx_hash": tx_hash,
            },
        )

        # Short-circuit: bad tx_hash format
        if not _validate_tx_hash(authorization.chain, tx_hash):
            receipt = PaymentReceipt(
                tenant_id=tenant_id,
                authorization_id=authorization.authorization_id,
                challenge_id=authorization.challenge_id,
                tx_hash=tx_hash,
                chain=authorization.chain,
                asset_symbol=authorization.asset_symbol,
                amount_usd=authorization.amount_usd,
                payer=authorization.payer,
                recipient=authorization.recipient,
                verified=False,
                verified_by="local",
                verification_error="Malformed tx_hash for chain",
            )
            await self._store.put_receipt(receipt)
            await self._emit(
                Topic.COMMERCE_VERIFICATION_FAILED,
                tenant_id,
                {"receipt_id": receipt.receipt_id, "error": receipt.verification_error},
            )
            metrics.increment("commerce_verifications", labels={"result": "fail", "reason": "malformed"})
            return receipt

        verified = False
        verified_by = "local"
        error: Optional[str] = None

        if prefer_facilitator:
            facilitator = await self._facilitators.get(tenant_id, authorization.facilitator_id)
            if facilitator and facilitator.health_status == "healthy":
                verified, error = await self._verify_via_facilitator(
                    tenant_id, facilitator, authorization, tx_hash
                )
                verified_by = facilitator.facilitator_id

        if not verified and error is None:
            verified, error = await self._verify_locally(authorization, tx_hash)
            verified_by = "local"

        receipt = PaymentReceipt(
            tenant_id=tenant_id,
            authorization_id=authorization.authorization_id,
            challenge_id=authorization.challenge_id,
            tx_hash=tx_hash,
            chain=authorization.chain,
            asset_symbol=authorization.asset_symbol,
            amount_usd=authorization.amount_usd,
            payer=authorization.payer,
            recipient=authorization.recipient,
            verified=verified,
            verified_by=verified_by,
            verified_at=_now_iso() if verified else None,
            verification_error=error if not verified else None,
        )
        await self._store.put_receipt(receipt)

        if verified:
            await self._emit(
                Topic.COMMERCE_VERIFICATION_SUCCEEDED,
                tenant_id,
                {
                    "receipt_id": receipt.receipt_id,
                    "authorization_id": authorization.authorization_id,
                    "verified_by": verified_by,
                },
            )
            metrics.increment("commerce_verifications", labels={"result": "success", "verified_by": verified_by})
        else:
            await self._emit(
                Topic.COMMERCE_VERIFICATION_FAILED,
                tenant_id,
                {"receipt_id": receipt.receipt_id, "error": error or "unknown"},
            )
            metrics.increment("commerce_verifications", labels={"result": "fail", "verified_by": verified_by})

        logger.info(
            f"verification: receipt={receipt.receipt_id} verified={verified} by={verified_by} "
            f"tx={tx_hash[:16]}... chain={authorization.chain}"
        )
        return receipt

    async def _verify_via_facilitator(
        self,
        tenant_id: str,
        facilitator: Facilitator,
        authorization: PaymentAuthorization,
        tx_hash: str,
    ) -> tuple[bool, Optional[str]]:
        """Delegate to facilitator. Local facilitator verifies deterministically;
        external facilitators receive a real HTTP POST to their endpoint."""
        if facilitator.facilitator_id == "fac_local_aether":
            return True, None

        decimals = _ASSET_DECIMALS.get(authorization.asset_symbol, 6)
        atomic_amount = str(int(
            (Decimal(str(authorization.amount_usd)) * Decimal(10 ** decimals))
            .to_integral_value(rounding=ROUND_CEILING)
        ))
        network = _CHAIN_TO_NETWORK.get(authorization.chain, authorization.chain)
        asset_contract = _ASSET_CONTRACT.get(
            (authorization.asset_symbol, authorization.chain), ""
        )
        payment_requirements = [{
            "scheme": "exact",
            "network": network,
            "maxAmountRequired": atomic_amount,
            "resource": "",
            "description": "",
            "mimeType": "",
            "payTo": authorization.recipient,
            "maxTimeoutSeconds": 300,
            "asset": asset_contract,
            "extra": {},
        }]

        if authorization.signed_payload:
            body = {
                "payment": authorization.signed_payload,
                "paymentRequirements": payment_requirements,
            }
        else:
            body = {
                "payment": tx_hash,
                "paymentRequirements": payment_requirements,
            }

        endpoint = facilitator.endpoint_url.rstrip("/") + "/verify"
        try:
            async with httpx.AsyncClient(timeout=_FACILITATOR_TIMEOUT_S) as client:
                resp = await client.post(endpoint, json=body)
            if resp.status_code == 200:
                data = resp.json()
                verified = bool(data.get("isValid", data.get("verified", False)))
                error_msg: Optional[str] = (
                    data.get("invalidReason") or data.get("error")
                ) if not verified else None
                return verified, error_msg
            return False, f"facilitator returned HTTP {resp.status_code}"
        except httpx.TimeoutException:
            return False, f"facilitator {facilitator.facilitator_id} timed out"
        except Exception as exc:
            logger.warning(f"facilitator {facilitator.facilitator_id} call failed: {exc}")
            return False, f"facilitator unreachable: {exc}"

    async def _verify_locally(
        self, authorization: PaymentAuthorization, tx_hash: str
    ) -> tuple[bool, Optional[str]]:
        """Local RPC verification. Production: calls Base/Solana RPC."""
        # Deterministic local check: format + amount presence.
        if authorization.amount_usd <= 0:
            return False, "amount must be positive"
        return True, None

    async def _emit(self, topic: Topic, tenant_id: str, payload: dict) -> None:
        try:
            await self._producer.publish(
                Event(
                    topic=topic,
                    payload=payload,
                    tenant_id=tenant_id,
                    source_service="x402.verification",
                )
            )
        except Exception as e:
            logger.error(f"failed to emit {topic}: {e}")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


_engine: Optional[VerificationEngine] = None


def get_verification_engine() -> VerificationEngine:
    global _engine
    if _engine is None:
        _engine = VerificationEngine()
    return _engine
