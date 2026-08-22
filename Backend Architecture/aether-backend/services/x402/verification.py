"""
Aether Service — Payment Verification Engine
Verifies payment proofs submitted against approved authorizations. Supports
facilitator-aware verification (delegate to external facilitator) and local
verification (on-chain RPC check) as fallback.

Day-1 chains: USDC on Base (eip155:8453), USDC on Solana (solana:mainnet).
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, ROUND_CEILING
from typing import Optional

import httpx

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from .commerce_models import Facilitator, FacilitatorMode, PaymentAuthorization, PaymentReceipt
from .commerce_store import get_commerce_store
from .facilitators import get_facilitator_registry

_FACILITATOR_TIMEOUT_S = 10.0


def _is_local_env() -> bool:
    import os
    return os.getenv("AETHER_ENV", "local").lower() in ("local", "test")


# Stable semantic verdict tokens (prefix of the error string → token). HTTP
# reachability is never a verdict; only the provider's semantic result is.
_VERDICT_PREFIXES = (
    "verification_unavailable",
    "payer_mismatch",
    "amount_below_required",
    "not_finalized",
    "reverted",
    "no_matching_transfer",
    "malformed",
)


def _receipt_id_for(tenant_id: str, authorization_id: str) -> str:
    """Deterministic receipt id per (tenant, authorization) — one receipt row per
    authorization, so re-verification upserts rather than colliding on the
    commerce_receipts (tenant_id, authorization_id) unique index."""
    digest = hashlib.sha256(
        f"{tenant_id}\x00{authorization_id}".encode("utf-8")
    ).hexdigest()
    return f"rcpt_{digest[:40]}"


def _verdict_token(error: Optional[str]) -> str:
    if not error:
        return "verification_failed"
    for prefix in _VERDICT_PREFIXES:
        if error.startswith(prefix) or error.lower().startswith(prefix):
            return prefix
    if "malformed" in (error or "").lower():
        return "malformed"
    return "verification_failed"


# Verdict tokens that are RETRYABLE: the chain hasn't finalized the tx yet, or
# the RPC/facilitator couldn't be reached — the *payment itself* was never
# adjudicated, so a later re-check can still succeed. Every other verdict
# (verified, or a definitive failure like reverted/payer_mismatch/
# amount_below_required/no_matching_transfer/malformed) is TERMINAL: a retry
# can never change the outcome, so it is safe to cache/idempotency-lock on.
#
# This distinction matters because the idempotency store
# (services.x402.idempotency) is consulted by control_plane.verify_and_settle
# before it ever re-verifies a payment_identifier. Caching a retryable
# verdict would permanently strand a normally-submitted-but-not-yet-final
# payment behind the cached failure until the cache entry's TTL expires, with
# no settlement for the reconciliation worker (services.x402.reconciliation)
# to revisit in the meantime — so retryable verdicts must NEVER be cached.
_RETRYABLE_VERDICTS = frozenset({"not_finalized", "verification_unavailable"})


def is_terminal_verdict(verdict: Optional[str]) -> bool:
    """True when `verdict` is a definitive outcome safe to cache in the
    payment-identifier idempotency store. False for a retryable verdict
    (``not_finalized`` / ``verification_unavailable``), where the caller must
    let the next attempt re-check the chain instead of caching the failure."""
    return verdict not in _RETRYABLE_VERDICTS

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

# Decimal places for each supported asset. Unknown assets are NOT defaulted to
# 6 — an unknown asset is a hard error, never a silent assumption.
_ASSET_DECIMALS: dict[str, int] = {
    "USDC": 6,
}

# Minimum confirmations before a payment is treated as final (per chain family).
_MIN_CONFIRMATIONS = {"eip155": 2, "solana": 1}

logger = get_logger("aether.service.x402.verification")


class AssetDecimalsError(ValueError):
    """The asset's decimal precision is not declared — refuse to assume."""


def _asset_decimals(symbol: str) -> int:
    try:
        return _ASSET_DECIMALS[symbol]
    except KeyError:
        raise AssetDecimalsError(
            f"decimals for asset {symbol!r} are not declared; refusing to assume 6"
        )


def _expected_atomic(amount_usd: float, symbol: str) -> int:
    decimals = _asset_decimals(symbol)
    return int(
        (Decimal(str(amount_usd)) * Decimal(10 ** decimals)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )

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
                environment=authorization.environment,
                asset_symbol=authorization.asset_symbol,
                amount_usd=authorization.amount_usd,
                payer=authorization.payer,
                recipient=authorization.recipient,
                verified=False,
                verified_by="local",
                verification_verdict="malformed",
                verification_error="malformed tx_hash for chain",
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
            if facilitator and facilitator.health_status != "down":
                verified, error = await self._verify_via_facilitator(
                    tenant_id, facilitator, authorization, tx_hash
                )
                verified_by = facilitator.facilitator_id

        if not verified and error is None:
            verified, error = await self._verify_locally(authorization, tx_hash)
            verified_by = "local"

        verdict = "verified" if verified else _verdict_token(error)
        # Deterministic receipt id per (tenant, authorization) so a re-verification
        # — e.g. retrying a payment that first returned the retryable
        # not_finalized / verification_unavailable verdict — UPSERTS the same
        # receipt row (ON CONFLICT (id) DO UPDATE) instead of inserting a second
        # receipt that violates the commerce_receipts (tenant_id, authorization_id)
        # unique index and blocks the retry from ever re-checking the chain.
        receipt = PaymentReceipt(
            receipt_id=_receipt_id_for(tenant_id, authorization.authorization_id),
            tenant_id=tenant_id,
            authorization_id=authorization.authorization_id,
            challenge_id=authorization.challenge_id,
            tx_hash=tx_hash,
            chain=authorization.chain,
            environment=authorization.environment,
            asset_symbol=authorization.asset_symbol,
            amount_usd=authorization.amount_usd,
            payer=authorization.payer,
            recipient=authorization.recipient,
            verified=verified,
            verified_by=verified_by,
            verification_verdict=verdict,
            verified_at=_now_iso() if verified else None,
            verification_error=error if not verified else None,
        )
        # The deterministic receipt id makes put_receipt an upsert. Never let a
        # NON-verified re-verification (a retryable facilitator/RPC outage on a
        # later retry) downgrade an already-VERIFIED receipt that a settlement
        # still references — keep and return the existing terminal receipt.
        if not verified:
            existing = await self._store.get_receipt(tenant_id, receipt.receipt_id)
            if existing is not None and getattr(existing, "verified", False):
                logger.info(
                    "verification: keeping existing verified receipt %s; not "
                    "downgrading on a %s re-verification",
                    receipt.receipt_id, verdict,
                )
                return existing
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
        """Delegate to facilitator. The internal LOCAL facilitator confers
        verification only in the local environment; external facilitators
        receive a real HTTP POST and their SEMANTIC verdict (isValid/verified)
        decides — HTTP reachability alone never verifies a payment."""
        if (
            facilitator.mode == FacilitatorMode.LOCAL
            or facilitator.facilitator_id == "fac_local_aether"
        ):
            if not _is_local_env():
                # The internal facilitator has no chain access. Outside local
                # it must never confer verification — hand off to the on-chain
                # RPC verifier (error=None → engine falls through to
                # _verify_locally, which does a real receipt/transfer check).
                return False, None
            if authorization.amount_usd <= 0:
                return False, "amount must be positive"
            await self._facilitators.update_health(
                tenant_id, facilitator.facilitator_id, "healthy", success=True
            )
            return True, None

        try:
            atomic_amount = str(_expected_atomic(authorization.amount_usd, authorization.asset_symbol))
        except AssetDecimalsError as exc:
            return False, str(exc)
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

        # A facilitator that declares a credential slot must authenticate. Resolve
        # its tenant/environment-bound API key from the credential authority and
        # attach it as a bearer token. If it requires one but none is configured,
        # hand off to the on-chain RPC verifier (return False, None → verify()
        # falls through to _verify_locally) rather than sending an
        # unauthenticated request the facilitator would reject as a terminal
        # failure, which would strand an otherwise-valid payment.
        headers: dict[str, str] = {}
        if facilitator.credential_slot:
            from shared.common.common import NotFoundError

            from services.providers.credentials.authority import credential_authority

            try:
                api_key = await credential_authority.get_active_secret(
                    tenant_id,
                    facilitator.facilitator_id,
                    authorization.environment,
                    facilitator.credential_slot,
                )
            except NotFoundError:
                api_key = None
            except Exception:  # noqa: BLE001 — treat any resolution failure as unconfigured
                api_key = None
            if not api_key:
                logger.info(
                    "facilitator %s requires credential slot %s but none is configured "
                    "for tenant=%s env=%s — falling through to on-chain RPC verification",
                    facilitator.facilitator_id, facilitator.credential_slot,
                    tenant_id, authorization.environment,
                )
                return False, None
            headers["Authorization"] = f"Bearer {api_key}"

        endpoint = facilitator.endpoint_url.rstrip("/") + "/verify"
        try:
            async with httpx.AsyncClient(timeout=_FACILITATOR_TIMEOUT_S) as client:
                resp = await client.post(endpoint, json=body, headers=headers)
            if resp.status_code == 200:
                # A 200 is a real verdict either way — the facilitator is
                # reachable and functioning even when the payment is invalid.
                await self._facilitators.update_health(
                    tenant_id, facilitator.facilitator_id, "healthy", success=True
                )
                data = resp.json()
                verified = bool(data.get("isValid", data.get("verified", False)))
                error_msg: Optional[str] = (
                    data.get("invalidReason") or data.get("error")
                ) if not verified else None
                return verified, error_msg
            await self._facilitators.update_health(
                tenant_id, facilitator.facilitator_id, "degraded", success=False
            )
            # A 5xx / 429 is a transient facilitator OUTAGE, not a payment
            # verdict — classify it RETRYABLE (verification_unavailable) so
            # verify_and_settle does not cache it for 24h and strand an
            # otherwise-valid payment. A definitive 4xx rejection stays terminal.
            if resp.status_code >= 500 or resp.status_code == 429:
                return False, f"verification_unavailable: facilitator returned HTTP {resp.status_code}"
            return False, f"facilitator returned HTTP {resp.status_code}"
        except httpx.TimeoutException:
            await self._facilitators.update_health(
                tenant_id, facilitator.facilitator_id, "down", success=False
            )
            return False, f"verification_unavailable: facilitator {facilitator.facilitator_id} timed out"
        except Exception as exc:
            logger.warning(f"facilitator {facilitator.facilitator_id} call failed: {exc}")
            await self._facilitators.update_health(
                tenant_id, facilitator.facilitator_id, "down", success=False
            )
            return False, f"verification_unavailable: facilitator unreachable: {exc}"

    async def _verify_locally(
        self, authorization: PaymentAuthorization, tx_hash: str
    ) -> tuple[bool, Optional[str]]:
        """Dispatch to per-tenant RPC verification; deterministic stub in local dev."""
        if _is_local_env():
            if authorization.amount_usd <= 0:
                return False, "amount must be positive"
            return True, None

        if authorization.chain.startswith("eip155:"):
            return await self._verify_evm(authorization, tx_hash)
        if authorization.chain.startswith("solana:"):
            return await self._verify_solana(authorization, tx_hash)
        return False, f"unsupported chain for local verification: {authorization.chain}"

    async def _resolve_rpc(self, authorization: PaymentAuthorization):
        """Resolve the tenant's RPC endpoint+key for this authorization.

        Returns a ResolvedRpc, or raises RpcUnavailableError (mapped by the
        caller to the ``verification_unavailable`` verdict — never auto-pass)."""
        from services.x402.rpc_resolver import resolve_rpc

        return await resolve_rpc(
            authorization.tenant_id, authorization.environment, authorization.chain
        )

    async def _verify_evm(
        self, authorization: PaymentAuthorization, tx_hash: str
    ) -> tuple[bool, Optional[str]]:
        """Verify an ERC-20 USDC Transfer on an EVM chain via the tenant's RPC.

        Checks: receipt status, matching Transfer log (contract + recipient +
        PAYER + amount), and finality (current head minus tx block ≥ minimum
        confirmations). Returns a stable verdict token on failure.
        """
        from services.x402.rpc_resolver import RpcUnavailableError

        contract = _ASSET_CONTRACT.get((authorization.asset_symbol, authorization.chain))
        if not contract:
            return False, f"no contract for {authorization.asset_symbol}/{authorization.chain}"
        try:
            expected_min = _expected_atomic(authorization.amount_usd, authorization.asset_symbol)
        except AssetDecimalsError as exc:
            return False, str(exc)
        try:
            rpc = await self._resolve_rpc(authorization)
        except RpcUnavailableError as exc:
            return False, f"verification_unavailable: {exc}"

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(rpc.request_url(), headers=rpc.headers(), json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "eth_getTransactionReceipt",
                    "params": [tx_hash],
                })
                resp.raise_for_status()
                data = resp.json()
                # finality: current head vs tx block
                head_resp = await client.post(rpc.request_url(), headers=rpc.headers(), json={
                    "jsonrpc": "2.0", "id": 2, "method": "eth_blockNumber", "params": [],
                })
                head_resp.raise_for_status()
                head = int(head_resp.json().get("result", "0x0"), 16)
        except httpx.TimeoutException:
            return False, "verification_unavailable: EVM RPC timeout"
        except Exception as exc:
            return False, f"verification_unavailable: EVM RPC error: {exc}"

        result = data.get("result")
        if result is None:
            return False, "not_finalized: transaction not found or not yet mined"
        if result.get("status") != "0x1":
            return False, "reverted: transaction reverted on-chain"

        tx_block = int(result.get("blockNumber", "0x0"), 16)
        min_conf = _MIN_CONFIRMATIONS["eip155"]
        if tx_block == 0 or head - tx_block + 1 < min_conf:
            return False, f"not_finalized: {max(0, head - tx_block + 1)} < {min_conf} confirmations"

        # keccak256("Transfer(address,address,uint256)")
        TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        recipient_padded = "0x" + authorization.recipient.lower().lstrip("0x").zfill(64)
        payer_padded = "0x" + authorization.payer.lower().lstrip("0x").zfill(64)

        # Scan EVERY candidate Transfer log (contract + recipient match) before
        # giving up — a batched/multicall tx can contain several transfers to
        # the same recipient, and only one of them needs to satisfy every
        # predicate (payer + recipient + amount). Returning on the FIRST
        # candidate wrongly rejects a valid later transfer. The failure
        # reason from the first non-matching candidate is preserved for the
        # all-fail case, so a single-candidate receipt behaves exactly as
        # before.
        first_failure: Optional[str] = None
        for log in result.get("logs", []):
            topics = log.get("topics", [])
            if not (
                log.get("address", "").lower() == contract.lower()
                and len(topics) >= 3
                and topics[0].lower() == TRANSFER_TOPIC
                and topics[2].lower() == recipient_padded
            ):
                continue
            # payer binding: the Transfer's `from` (topics[1]) must be the
            # authorized payer — a payment from a different wallet is not
            # this authorization's payment.
            if topics[1].lower() != payer_padded:
                if first_failure is None:
                    first_failure = "payer_mismatch: transfer from unauthorized wallet"
                continue
            raw_amount = int(log.get("data", "0x0"), 16)
            if raw_amount >= expected_min:
                return True, None
            if first_failure is None:
                first_failure = f"amount_below_required: {raw_amount} < {expected_min}"

        if first_failure is not None:
            return False, first_failure
        return False, "no_matching_transfer: no matching USDC Transfer log found"

    async def _verify_solana(
        self, authorization: PaymentAuthorization, tx_hash: str
    ) -> tuple[bool, Optional[str]]:
        """Verify an SPL USDC transfer on Solana via the tenant's RPC.

        Checks: tx success, matching transfer (mint + destination + PAYER
        authority + amount), and commitment finality (`finalized`).
        """
        from services.x402.rpc_resolver import RpcUnavailableError

        mint = _ASSET_CONTRACT.get((authorization.asset_symbol, authorization.chain))
        try:
            expected_min = _expected_atomic(authorization.amount_usd, authorization.asset_symbol)
        except AssetDecimalsError as exc:
            return False, str(exc)
        try:
            rpc = await self._resolve_rpc(authorization)
        except RpcUnavailableError as exc:
            return False, f"verification_unavailable: {exc}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(rpc.request_url(), headers=rpc.headers(), json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTransaction",
                    "params": [tx_hash, {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0,
                        "commitment": "finalized",
                    }],
                })
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            return False, "verification_unavailable: Solana RPC timeout"
        except Exception as exc:
            return False, f"verification_unavailable: Solana RPC error: {exc}"

        result = data.get("result")
        if result is None:
            # finalized commitment returned nothing → not yet final (or missing)
            return False, "not_finalized: transaction not found at finalized commitment"
        if result.get("meta", {}).get("err") is not None:
            return False, "reverted: transaction failed on-chain"

        instructions = (
            result.get("transaction", {}).get("message", {}).get("instructions", [])
        )
        inner: list = []
        for group in result.get("meta", {}).get("innerInstructions", []):
            inner.extend(group.get("instructions", []))

        # Scan EVERY candidate spl-token transfer instruction (mint +
        # destination match) before giving up — see the matching comment in
        # _verify_evm. The first non-matching candidate's failure reason is
        # preserved for the all-fail case.
        first_failure: Optional[str] = None
        for ix in instructions + inner:
            if ix.get("program") != "spl-token":
                continue
            parsed = ix.get("parsed", {})
            ix_type = parsed.get("type", "")
            info = parsed.get("info", {})
            if ix_type not in ("transfer", "transferChecked"):
                continue
            if mint and info.get("mint") and info["mint"] != mint:
                continue
            if info.get("destination") != authorization.recipient:
                continue
            # payer binding: the transfer authority/source must be the payer.
            authority = info.get("authority") or info.get("source")
            if authority and authority != authorization.payer:
                if first_failure is None:
                    first_failure = "payer_mismatch: transfer authority is not the payer"
                continue
            raw = info.get("amount") or info.get("tokenAmount", {}).get("amount", "0")
            if int(raw) >= expected_min:
                return True, None
            if first_failure is None:
                first_failure = f"amount_below_required: {raw} < {expected_min}"

        if first_failure is not None:
            return False, first_failure
        return False, "no_matching_transfer: no matching SPL token transfer found"

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
