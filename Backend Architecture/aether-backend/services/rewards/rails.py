"""
Aether Backend — Reward Rail Adapters

Rail adapters generate action payloads and deliver them through tenant-owned
channels. Aether never holds funds or executes the final reward; the tenant does.

See docs/source-of-truth/REWARD_RAILS.md for full rail documentation.

Architecture:
    RewardRailAdapter (ABC)
        ├── RecommendOnlyAdapter
        ├── ManualApprovalAdapter
        ├── ManualExportAdapter
        ├── TenantWebhookAdapter
        ├── OnchainClaimAdapter (EVM production; other VMs beta)
        └── Beta stubs (stripe_credit, loyalty_points, coupon, internal_credit, x402_credit)

Rail adapters do not:
    - Hold, transfer, or custody reward tokens.
    - Submit on-chain transactions (onchain_claim returns a proof; tenant submits).
    - Execute direct payouts to users.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import socket
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import ROUND_DOWN
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel

from services.rewards.policy_engine import PolicyDecision, _amount_to_decimal
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.rails")


# ═══════════════════════════════════════════════════════════════════════════
# EXACT REWARD-AMOUNT CONVERSION
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_asset_decimals(*sources) -> Optional[int]:
    """Return explicit asset decimals from the first source that declares them.

    Checks ``asset_decimals`` then ``decimals`` on each supplied dict (rule,
    reward, campaign …). Returns ``None`` if none declare it — callers must
    treat that as *ambiguous* and refuse to assume a default (e.g. 18).
    """
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in ("asset_decimals", "decimals"):
            raw = src.get(key)
            if raw is None:
                continue
            try:
                decimals = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be an integer, got {raw!r}")
            if decimals < 0:
                raise ValueError(f"{key} must be non-negative, got {decimals}")
            return decimals
    return None


def _reward_amount_to_atomic(amount_value, decimals: int) -> int:
    """Convert a human reward amount to its exact atomic integer.

    Uses ``Decimal`` end-to-end (``scaleb`` == exact multiply by 10**decimals);
    an amount with more fractional digits than ``decimals`` allows is rejected
    rather than silently truncated, so no precision is ever lost.
    """
    amount = _amount_to_decimal(amount_value)
    if amount < 0:
        raise ValueError(f"reward_amount must be non-negative, got {amount_value!r}")
    atomic = amount.scaleb(decimals)
    integral = atomic.to_integral_value(rounding=ROUND_DOWN)
    if atomic != integral:
        raise ValueError(
            f"reward_amount {amount_value!r} is not exactly representable with "
            f"{decimals} decimals (would lose precision)"
        )
    return int(integral)


def _redact(_secret: Optional[str]) -> str:
    """Never emit signing material to logs."""
    return "***redacted***"


# ═══════════════════════════════════════════════════════════════════════════
# BASE RAIL ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class DeliveryResult(BaseModel):
    success: bool
    status: str
    error: Optional[str] = None
    delivery_id: Optional[str] = None
    response_code: Optional[int] = None
    latency_ms: Optional[float] = None


class RailUnavailableError(Exception):
    def __init__(self, rail: str, reason: str = "beta_unavailable") -> None:
        self.rail = rail
        self.reason = reason
        super().__init__(f"Rail {rail!r} unavailable: {reason}")


class RewardRailAdapter(ABC):
    rail_name: str

    @abstractmethod
    def validate_config(self, config: dict) -> list[str]:
        """Return validation errors. Empty list = valid."""
        ...

    @abstractmethod
    async def build_action_payload(
        self,
        decision: PolicyDecision,
        rule: dict,
        campaign: dict,
        tenant_id: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Build the payload dict for storage in reward_action_payloads."""
        ...

    @abstractmethod
    async def deliver(self, action: dict, rail_config: dict) -> DeliveryResult:
        """Deliver the payload. May be a no-op for some rails."""
        ...

    async def health_check(self, rail_config: dict) -> dict:
        errors = self.validate_config(rail_config.get("config", {}))
        return {"rail": self.rail_name, "healthy": len(errors) == 0, "errors": errors}

    def _idempotency_key(self, decision: PolicyDecision, tenant_id: str) -> str:
        raw = f"{tenant_id}:{decision.campaign_id}:{decision.rule_id}:{decision.identity}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ═══════════════════════════════════════════════════════════════════════════
# RECOMMEND ONLY
# ═══════════════════════════════════════════════════════════════════════════

class RecommendOnlyAdapter(RewardRailAdapter):
    """Returns eligibility recommendation with no delivery."""

    rail_name = "recommend_only"

    def validate_config(self, config: dict) -> list[str]:
        return []

    async def build_action_payload(self, decision, rule, campaign, tenant_id, idempotency_key=None) -> dict:
        return {
            "rail": self.rail_name,
            "execution_mode": "recommend_only",
            "status": "ready",
            "payload": {
                "type": "reward_recommendation",
                "campaign_id": decision.campaign_id,
                "rule_id": decision.rule_id,
                "reward": decision.reward,
                "decision_reason": decision.decision_reason,
                "attribution": decision.attribution,
                "fraud": decision.fraud,
            },
        }

    async def deliver(self, action: dict, rail_config: dict) -> DeliveryResult:
        return DeliveryResult(success=True, status="ready")


# ═══════════════════════════════════════════════════════════════════════════
# MANUAL APPROVAL
# ═══════════════════════════════════════════════════════════════════════════

class ManualApprovalAdapter(RewardRailAdapter):
    """Queues action for operator review; no automatic delivery."""

    rail_name = "manual_approval"

    def validate_config(self, config: dict) -> list[str]:
        return []

    async def build_action_payload(self, decision, rule, campaign, tenant_id, idempotency_key=None) -> dict:
        return {
            "rail": self.rail_name,
            "execution_mode": "manual_approval",
            "status": "pending_approval",
            "payload": {
                "type": "reward_approval_request",
                "campaign_id": decision.campaign_id,
                "rule_id": decision.rule_id,
                "campaign_name": campaign.get("name"),
                "rule_name": rule.get("name"),
                "reward": decision.reward,
                "identity": decision.identity,
                "attribution": decision.attribution,
                "fraud": decision.fraud,
                "decision_reason": decision.decision_reason,
            },
        }

    async def deliver(self, action: dict, rail_config: dict) -> DeliveryResult:
        raise RailUnavailableError(self.rail_name, "manual_approval requires explicit operator approval")


# ═══════════════════════════════════════════════════════════════════════════
# MANUAL EXPORT
# ═══════════════════════════════════════════════════════════════════════════

class ManualExportAdapter(RewardRailAdapter):
    """Produces a row in the batch export for tenant processing."""

    rail_name = "manual_export"

    def validate_config(self, config: dict) -> list[str]:
        return []

    async def build_action_payload(self, decision, rule, campaign, tenant_id, idempotency_key=None) -> dict:
        return {
            "rail": self.rail_name,
            "execution_mode": "manual_export",
            "status": "ready",
            "payload": {
                "type": "reward_export_row",
                "campaign_id": decision.campaign_id,
                "campaign_name": campaign.get("name"),
                "rule_id": decision.rule_id,
                "rule_name": rule.get("name"),
                "reward_amount": decision.reward.get("amount") if decision.reward else None,
                "reward_unit": decision.reward.get("unit") if decision.reward else None,
                "reward_currency": decision.reward.get("currency") if decision.reward else None,
                "reward_metadata": decision.reward.get("metadata", {}) if decision.reward else {},
                "identity": {
                    "user_id": decision.identity.get("cluster_id") if decision.identity else None,
                    "wallet_address": decision.identity.get("wallet_address") if decision.identity else None,
                },
                "attribution_model": decision.attribution.get("model") if decision.attribution else None,
                "attribution_channel": decision.attribution.get("channel") if decision.attribution else None,
            },
        }

    async def deliver(self, action: dict, rail_config: dict) -> DeliveryResult:
        return DeliveryResult(success=True, status="ready")


# ═══════════════════════════════════════════════════════════════════════════
# TENANT WEBHOOK
# ═══════════════════════════════════════════════════════════════════════════

class TenantWebhookAdapter(RewardRailAdapter):
    """Delivers a signed JSON payload to the tenant's configured webhook URL."""

    rail_name = "tenant_webhook"

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        url = config.get("webhook_url")
        if not url:
            errors.append("webhook_url is required")
        else:
            parsed = urlparse(url) if isinstance(url, str) else None
            if parsed is None or parsed.scheme not in ("http", "https") or not parsed.hostname:
                errors.append(f"webhook_url is malformed (expected http(s)://host/...): {url!r}")
        if not config.get("signing_secret") and not config.get("secret_ref"):
            errors.append("signing_secret or secret_ref is required for HMAC signing")
        return errors

    async def build_action_payload(self, decision, rule, campaign, tenant_id, idempotency_key=None) -> dict:
        idem_key = idempotency_key or str(uuid.uuid4())
        body = {
            "event": "reward.action.ready",
            "idempotency_key": idem_key,
            "tenant_id": tenant_id,
            "campaign_id": decision.campaign_id,
            "campaign_name": campaign.get("name"),
            "rule_id": decision.rule_id,
            "rule_name": rule.get("name"),
            "rail": self.rail_name,
            "reward": decision.reward,
            "attribution": decision.attribution,
            "fraud": {
                "decision": (decision.fraud or {}).get("decision"),
                "score": (decision.fraud or {}).get("score"),
            },
            "identity": {
                "cluster_id": (decision.identity or {}).get("cluster_id"),
                "wallet_address": (decision.identity or {}).get("wallet_address"),
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "rail": self.rail_name,
            "execution_mode": "tenant_webhook",
            "status": "created",
            "payload": body,
            "payload_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
        }

    def _sign_payload(self, secret: str, timestamp, payload_json: str) -> str:
        """Produce HMAC-SHA256 signature for the webhook payload.

        Signed content is ``"{timestamp}.{payload_json}"`` keyed by ``secret``.
        """
        signed_content = f"{timestamp}.{payload_json}".encode()
        sig = hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()
        return f"hmac-sha256={sig}"

    # Byte cap on the amount of tenant response body we read/store.
    _MAX_RESPONSE_BYTES = 2000

    def _validate_destination(self, url, *, is_local: bool) -> Optional[str]:
        """SSRF / transport validation. Returns a failure reason, or ``None`` if allowed.

        Never raises. Fail-closed: any unexpected error is treated as a block.

        Reuses ``services.delivery.security.validate_webhook_url`` for the shared
        DNS-resolving RFC-1918/loopback/link-local/ULA blocklist, then adds
        HTTPS enforcement plus multicast/reserved/non-global checks (which the
        shared list does not cover) and a second DNS resolution to blunt DNS
        rebinding between validation and connect.
        """
        if not url or not isinstance(url, str):
            return "webhook_url missing or not a string"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return f"invalid webhook_url (expected http(s)://host/...): {url!r}"
        if not is_local and parsed.scheme != "https":
            return "webhook_url must use HTTPS outside local mode"

        try:
            from services.delivery.security import validate_webhook_url

            # allow_private=True in local/test keeps loopback reachable.
            validate_webhook_url(url, allow_private=is_local)
        except Exception as exc:  # SSRFBlockedError and any resolution failure → block
            return f"SSRF-blocked destination: {exc}"

        if is_local:
            return None

        # Supplementary ranges not covered by the shared blocklist. Re-resolving
        # here (post initial validation) also narrows the DNS-rebinding window.
        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
        except OSError as exc:
            return f"DNS resolution failed for {parsed.hostname!r}: {exc}"
        for info in infos:
            addr_str = info[4][0]
            try:
                addr = ipaddress.ip_address(addr_str)
            except ValueError:
                continue
            if (
                addr.is_multicast
                or addr.is_reserved
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_private
                or addr.is_unspecified
                or not addr.is_global
            ):
                return (
                    f"webhook_url {url!r} resolves to non-public address "
                    f"{addr_str!r}; SSRF protection active"
                )
        return None

    async def deliver(self, action: dict, rail_config: dict) -> DeliveryResult:
        config = rail_config.get("config", {})
        webhook_url = rail_config.get("webhook_url") or config.get("webhook_url")
        signing_secret = config.get("signing_secret", "")
        timeout_ms = int(config.get("timeout_ms", 10000))
        payload = action.get("payload", {})

        env = os.getenv("AETHER_ENV", "local").lower()
        is_local = env in ("local", "test")

        # ── SSRF / transport validation BEFORE any network I/O ────────────
        reason = self._validate_destination(webhook_url, is_local=is_local)
        if reason is not None:
            metrics.increment(
                "rewards_actions_failed_total",
                labels={"rail": self.rail_name, "reason": "ssrf_blocked"},
            )
            host = urlparse(webhook_url).hostname if isinstance(webhook_url, str) else None
            logger.warning("tenant_webhook delivery blocked host=%s reason=%s", host, reason)
            return DeliveryResult(success=False, status="failed", error=reason)

        try:
            import httpx
        except ImportError:
            return DeliveryResult(success=False, status="failed", error="httpx not available")

        payload_json = json.dumps(payload, sort_keys=True)
        timestamp = int(time.time())
        signature = self._sign_payload(signing_secret, timestamp, payload_json)
        idem_key = payload.get("idempotency_key", str(uuid.uuid4()))

        headers = {
            "Content-Type": "application/json",
            "X-Aether-Signature": signature,
            "X-Aether-Timestamp": str(timestamp),
            "X-Aether-Idempotency-Key": idem_key,
        }

        host = urlparse(webhook_url).hostname
        start = time.monotonic()
        try:
            # follow_redirects=False so a 3xx to an internal host is never chased.
            async with httpx.AsyncClient(
                timeout=timeout_ms / 1000.0,
                follow_redirects=False,
            ) as client:
                resp = await client.post(webhook_url, content=payload_json, headers=headers)
            latency_ms = (time.monotonic() - start) * 1000
            success = 200 <= resp.status_code < 300
            metrics.increment(
                "rewards_webhook_delivery_latency_ms",
                labels={"tenant_id": payload.get("tenant_id", "")},
            )
            # Bounded body read — never buffer/store an unbounded tenant response.
            logger.info(
                "tenant_webhook delivery host=%s status=%s idem=%s sig=%s",
                host, resp.status_code, idem_key, _redact(signature),
            )
            if success:
                metrics.increment("rewards_actions_delivered_total", labels={"rail": self.rail_name})
                return DeliveryResult(
                    success=True,
                    status="delivered",
                    response_code=resp.status_code,
                    latency_ms=latency_ms,
                )
            else:
                return DeliveryResult(
                    success=False,
                    status="failed",
                    error=f"HTTP {resp.status_code}: {resp.text[:self._MAX_RESPONSE_BYTES]}",
                    response_code=resp.status_code,
                    latency_ms=latency_ms,
                )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            metrics.increment("rewards_actions_failed_total", labels={"rail": self.rail_name, "reason": "exception"})
            return DeliveryResult(success=False, status="failed", error=str(exc), latency_ms=latency_ms)


# ═══════════════════════════════════════════════════════════════════════════
# ON-CHAIN CLAIM (EVM production; other VMs beta)
# ═══════════════════════════════════════════════════════════════════════════

class OnchainClaimAdapter(RewardRailAdapter):
    """
    Generates a cryptographic claim proof for tenant-owned EVM contracts.
    Aether signs the proof; the tenant's dApp or the user submits the claim.
    Aether never holds tokens or submits transactions.
    """

    rail_name = "onchain_claim"

    # VM types that are production-verified
    _PRODUCTION_VM_TYPES = {"evm"}
    # Anvil/Hardhat test key
    _TEST_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        vm_type = (config.get("vm_type") or "evm").lower()
        if vm_type not in self._PRODUCTION_VM_TYPES:
            errors.append(f"vm_type={vm_type!r} is in beta; only 'evm' is production-supported")
        if not config.get("chain_id"):
            errors.append("chain_id is required")
        if not config.get("signer_key_ref") and not config.get("oracle_signer_key"):
            errors.append("signer_key_ref or oracle_signer_key is required")
        return errors

    async def build_action_payload(
        self,
        decision: PolicyDecision,
        rule: dict,
        campaign: dict,
        tenant_id: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        env = os.getenv("AETHER_ENV", "local").lower()
        is_local = env in ("local", "test")

        signer_key = self._resolve_signer_key(is_local)
        chain_id = int(campaign.get("chain_id") or os.getenv("EVM_CHAIN_ID", "1"))
        contract_address = campaign.get("contract_address") or os.getenv(
            "EVM_CONTRACT_ADDRESS", "0x5FbDB2315678afecb367f032d93F642f64180aa3"
        )
        wallet_address = (decision.identity or {}).get("wallet_address", "")

        if not wallet_address:
            raise ValueError("wallet_address required for onchain_claim rail")

        # Exact reward → atomic-unit conversion with EXPLICIT decimals (never 18).
        raw_amount = rule.get("reward_amount")
        if raw_amount is None:
            amount_atomic = 0
        else:
            decimals = _resolve_asset_decimals(rule, decision.reward or {}, campaign)
            if decimals is None:
                raise ValueError(
                    "asset decimals must be explicitly specified for onchain_claim "
                    "reward conversion (set 'asset_decimals' or 'decimals' on the rule, "
                    "reward, or campaign); refusing to assume 18"
                )
            amount_atomic = _reward_amount_to_atomic(raw_amount, decimals)

        # Generate proof
        from services.oracle.signer import OracleProofSigner, ProofConfig
        proof_expiry = int(os.getenv("REWARD_PROOF_EXPIRY_SECONDS", "3600"))
        signer = OracleProofSigner(ProofConfig(
            signer_private_key=signer_key,
            contract_address=contract_address,
            chain_id=chain_id,
            proof_expiry_seconds=proof_expiry,
        ))
        proof = await signer.generate_proof(
            user=wallet_address,
            action_type=rule.get("name", "reward"),
            amount_wei=amount_atomic,
        )

        metrics.increment("rewards_proofs_generated_total", labels={"tenant_id": tenant_id})
        return {
            "rail": self.rail_name,
            "execution_mode": "onchain_claim",
            "status": "ready",
            "proof_data": {
                "proof_format": "eip191",
                "wallet_address": wallet_address,
                "action_type": rule.get("name", "reward"),
                "amount": str(amount_atomic),
                "nonce": proof.nonce,
                "expiry": proof.expiry,
                "chain_id": proof.chain_id,
                "contract_address": proof.contract_address,
                "message_hash": proof.message_hash,
                "signature": proof.signature,
                "signer_address": signer.signer_address,
            },
            "payload": {
                "type": "onchain_claim_proof",
                "campaign_id": decision.campaign_id,
                "rule_id": decision.rule_id,
                "tenant_id": tenant_id,
                "vm_type": "evm",
                "chain_id": chain_id,
                "contract_address": contract_address,
                "instruction": "Tenant dApp or user submits claimReward() to the contract using this proof. Aether does not submit the transaction.",
            },
        }

    def _resolve_signer_key(self, is_local: bool) -> str:
        key = os.environ.get("ORACLE_SIGNER_KEY", "")
        disable_local_in_prod = os.getenv("REWARD_DISABLE_LOCAL_SIGNER_IN_PROD", "1") == "1"

        if not key:
            if is_local:
                return self._TEST_KEY
            raise RuntimeError(
                "ORACLE_SIGNER_KEY must be set in non-local environments. "
                "Configure via REWARD_SIGNER_KEY_REF pointing to a secret manager entry."
            )
        if key == self._TEST_KEY and not is_local and disable_local_in_prod:
            raise RuntimeError(
                "Default Hardhat/Anvil test key detected in non-local environment. "
                "Configure ORACLE_SIGNER_KEY via secret manager (REWARD_SIGNER_KEY_REF)."
            )
        return key

    async def deliver(self, action: dict, rail_config: dict) -> DeliveryResult:
        # Proof is returned in the action payload; tenant submits on-chain.
        return DeliveryResult(success=True, status="ready")


# ═══════════════════════════════════════════════════════════════════════════
# BETA RAIL STUBS
# ═══════════════════════════════════════════════════════════════════════════

class _BetaRailStub(RewardRailAdapter):
    """Stub for rails that are not yet production-ready."""

    def validate_config(self, config: dict) -> list[str]:
        return [f"Rail {self.rail_name!r} is in beta and not available for production use"]

    async def build_action_payload(self, decision, rule, campaign, tenant_id, idempotency_key=None) -> dict:
        return {
            "rail": self.rail_name,
            "execution_mode": "manual_export",
            "status": "ready",
            "payload": {
                "type": f"beta_{self.rail_name}_export",
                "note": f"Rail {self.rail_name!r} is in beta. Use manual_export to process this reward.",
                "reward": decision.reward,
                "campaign_id": decision.campaign_id,
                "rule_id": decision.rule_id,
            },
        }

    async def deliver(self, action: dict, rail_config: dict) -> DeliveryResult:
        raise RailUnavailableError(self.rail_name)


class StripeCreditAdapter(_BetaRailStub):
    rail_name = "stripe_credit"


class LoyaltyPointsAdapter(_BetaRailStub):
    rail_name = "loyalty_points"


class CouponAdapter(_BetaRailStub):
    rail_name = "coupon"


class InternalCreditAdapter(_BetaRailStub):
    rail_name = "internal_credit"


class X402CreditAdapter(_BetaRailStub):
    rail_name = "x402_credit"


# ═══════════════════════════════════════════════════════════════════════════
# RAIL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

_RAIL_ADAPTERS: dict[str, RewardRailAdapter] = {
    "recommend_only": RecommendOnlyAdapter(),
    "manual_approval": ManualApprovalAdapter(),
    "manual_export": ManualExportAdapter(),
    "tenant_webhook": TenantWebhookAdapter(),
    "onchain_claim": OnchainClaimAdapter(),
    "stripe_credit": StripeCreditAdapter(),
    "loyalty_points": LoyaltyPointsAdapter(),
    "coupon": CouponAdapter(),
    "internal_credit": InternalCreditAdapter(),
    "x402_credit": X402CreditAdapter(),
}


def get_rail_adapter(rail: str) -> RewardRailAdapter:
    adapter = _RAIL_ADAPTERS.get(rail)
    if adapter is None:
        raise ValueError(f"Unknown rail: {rail!r}. Supported: {sorted(_RAIL_ADAPTERS)}")
    return adapter
