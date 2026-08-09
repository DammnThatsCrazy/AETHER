"""deBridge adapter — DLN order + deBridgeGate message observation (fixture-proven).

Implementation status: CREDENTIAL_GATED. Decode/correlation/reorg logic is
complete and proven against fixtures; LIVE scanning requires configured per-chain
RPC endpoints (and, for attestation, the deBridge validator API), which this
environment does not hold. The RPC client is injected so tests and future live
wiring share one code path — identical seam to the LayerZero V2 reference adapter.

Observation-only. Aether never solves, fulfils, claims, signs, or recovers
deBridge orders/messages (``execution_by_aether=False``).

SECURITY / FINALITY SEMANTICS (do not flatten against other providers)
----------------------------------------------------------------------
deBridge secures cross-chain state with an **off-chain validator set**: deBridge
validators observe finalized source-chain events and produce signatures that
authorize a destination action. Two product lines are observed:

  * DLN (deBridge Liquidity Network) — an *intent/solver* market. A maker posts
    an order on the give chain (``CreatedOrder``); a taker/solver fulfils it on
    the take chain (``FulfilledOrder``); the solver later unlocks/claims the
    maker's funds on the give chain (``ClaimedOrder``), gated by validator
    signatures. Canonical id: ``orderId``.
  * deBridgeGate — generic messaging. ``Sent`` on source, ``Claimed`` on
    destination once validator signatures are presented. Canonical id:
    ``submissionId``.

The attestation itself (validator signatures) is **off-chain** and observable
only through the deBridge API (credential-gated). This is materially DIFFERENT
from Hyperlane's recipient-configured ISM, from LayerZero's on-chain DVN
``PacketVerified`` event, and from IBC's on-chain light-client proof. We do NOT
synthesize a "verified" phase from chain logs; the on-chain observable phases are
source -> delivered (-> settled for DLN unlock).

Mapping (provider-native -> canonical):
    DlnSource / deBridgeGate        -> InteropGateway
    orderId / submissionId          -> correlation key alias + provider ref
    CreatedOrder / Sent             -> phase "sent"      (source ref, side=source)
    FulfilledOrder / Claimed        -> phase "delivered" (dest ref,  side=destination)
    ClaimedOrder (DLN unlock)       -> phase "settled"
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from eth_utils import keccak

from services.integrations.connectors.base import ImplementationStatus
from services.interop.foundation import utc_now_iso
from services.interop.providers.base import InteropProviderAdapter, OperationalFieldsMixin
from services.interop.providers.transport import RpcRateLimited

# ── event signatures ────────────────────────────────────────────────────────
# DLN Order modelled as a dynamic tuple (production carries variable-length
# address/bytes fields, so it is dynamic and encoded behind an offset). The
# fixtures model that dynamic layout; the decoder reads the static financial
# words plus the top-level orderId.
SIG_CREATED_ORDER = "CreatedOrder((uint64,uint256,uint256,uint256,uint256,bytes32),bytes32,uint256,uint256,uint32)"
SIG_FULFILLED_ORDER = "FulfilledOrder((uint64,uint256,uint256,uint256,uint256,bytes32),bytes32,address)"
SIG_CLAIMED_ORDER = "ClaimedOrder(bytes32,address,uint256)"
SIG_SENT = "Sent(bytes32,bytes32,uint256,uint256,uint256)"
SIG_CLAIMED = "Claimed(bytes32,bytes32,uint256,uint256)"

TOPIC_CREATED_ORDER = "0x" + keccak(text=SIG_CREATED_ORDER).hex()
TOPIC_FULFILLED_ORDER = "0x" + keccak(text=SIG_FULFILLED_ORDER).hex()
TOPIC_CLAIMED_ORDER = "0x" + keccak(text=SIG_CLAIMED_ORDER).hex()
TOPIC_SENT = "0x" + keccak(text=SIG_SENT).hex()
TOPIC_CLAIMED = "0x" + keccak(text=SIG_CLAIMED).hex()

# deBridge chain id -> network metadata (EVM native chain ids; extended via config).
DEFAULT_CHAIN_NETWORKS: dict[int, dict[str, str]] = {
    1: {"network_id": "ethereum-mainnet", "native_chain_id": "1"},
    56: {"network_id": "bnb-mainnet", "native_chain_id": "56"},
    137: {"network_id": "polygon-mainnet", "native_chain_id": "137"},
    42161: {"network_id": "arbitrum-mainnet", "native_chain_id": "42161"},
    8453: {"network_id": "base-mainnet", "native_chain_id": "8453"},
}

DEFAULT_CONFIRMATIONS = 12
DEFAULT_MAX_BLOCK_SPAN = 2000
_RECENT_HASHES_KEPT = 32


class RateLimited(RpcRateLimited):
    """Raised by the injected RPC client on provider throttling; scan resumes."""


class RpcClient(Protocol):
    async def get_head(self, network_id: str) -> dict[str, Any]: ...
    async def get_logs(
        self, network_id: str, from_block: int, to_block: int,
    ) -> list[dict[str, Any]]: ...
    async def get_block_hash(self, network_id: str, block_number: int) -> str: ...


def _strip0x(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def _word(value: int) -> bytes:
    return value.to_bytes(32, "big")


# ── DLN Order encode/decode (drift-proof: fixtures use these encoders) ───────
# Order tail = static words [makerOrderNonce, giveChainId, giveAmount,
# takeChainId, takeAmount] + maker(bytes32).

def encode_dln_order(
    maker_nonce: int, give_chain_id: int, give_amount: int,
    take_chain_id: int, take_amount: int, maker32: bytes,
) -> bytes:
    if len(maker32) != 32:
        raise ValueError("maker must be a 32-byte value")
    return (
        _word(maker_nonce) + _word(give_chain_id) + _word(give_amount)
        + _word(take_chain_id) + _word(take_amount) + maker32
    )


def decode_dln_order(order_tail: bytes) -> dict[str, Any]:
    if len(order_tail) < 192:
        raise ValueError("DLN order tail too short")
    return {
        "maker_order_nonce": int.from_bytes(order_tail[0:32], "big"),
        "give_chain_id": int.from_bytes(order_tail[32:64], "big"),
        "give_amount": str(int.from_bytes(order_tail[64:96], "big")),
        "take_chain_id": int.from_bytes(order_tail[96:128], "big"),
        "take_amount": str(int.from_bytes(order_tail[128:160], "big")),
        "maker": "0x" + order_tail[160:192][-20:].hex(),
    }


def encode_created_order_data(
    order_id: bytes, order_tail: bytes,
    native_fix_fee: int = 0, percent_fee: int = 0, referral_code: int = 0,
) -> str:
    """CreatedOrder(order, bytes32 orderId, uint256 nativeFixFee,
    uint256 percentFee, uint32 referralCode). Order is dynamic -> head[0] is its
    offset; orderId sits at head[1]."""
    if len(order_id) != 32:
        raise ValueError("order_id must be 32 bytes")
    head_words = 5
    order_offset = head_words * 32
    data = (
        _word(order_offset) + order_id + _word(native_fix_fee)
        + _word(percent_fee) + _word(referral_code) + order_tail
    )
    return "0x" + data.hex()


def encode_fulfilled_order_data(order_id: bytes, order_tail: bytes, taker: str) -> str:
    """FulfilledOrder(order, bytes32 orderId, address taker)."""
    if len(order_id) != 32:
        raise ValueError("order_id must be 32 bytes")
    head_words = 3
    order_offset = head_words * 32
    data = (
        _word(order_offset) + order_id + _word(int(taker, 16)) + order_tail
    )
    return "0x" + data.hex()


def encode_claimed_order_data(order_id: bytes, beneficiary: str, give_amount: int) -> str:
    """ClaimedOrder(bytes32 orderId, address beneficiary, uint256 giveAmount)."""
    if len(order_id) != 32:
        raise ValueError("order_id must be 32 bytes")
    return "0x" + (_word(int.from_bytes(order_id, "big")) + _word(int(beneficiary, 16)) + _word(give_amount)).hex()


def encode_sent_data(submission_id: bytes, amount: int, nonce: int) -> str:
    """Gate Sent data (submissionId at word 0); debridgeId/chainIdTo are indexed."""
    if len(submission_id) != 32:
        raise ValueError("submission_id must be 32 bytes")
    return "0x" + (submission_id + _word(amount) + _word(nonce)).hex()


def encode_claimed_data(submission_id: bytes, amount: int, nonce: int) -> str:
    """Gate Claimed data (submissionId at word 0); debridgeId/chainIdFrom indexed."""
    if len(submission_id) != 32:
        raise ValueError("submission_id must be 32 bytes")
    return "0x" + (submission_id + _word(amount) + _word(nonce)).hex()


class DebridgeAdapter(OperationalFieldsMixin, InteropProviderAdapter):
    provider_id = "debridge"
    provider_kind = "debridge"
    display_name = "deBridge (DLN + Gate observation adapter)"
    protocol_products = ("messaging", "intent", "asset_transfer")
    supported_versions = ("dln-v1", "gate-v1")
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    adapter_version = "0.1.0"
    capabilities = (
        "message_observation", "intent_observation", "delivery_observation",
        "settlement_observation", "historical_backfill", "direct_rpc_observation",
        "reorg_recovery",
    )
    known_limitations = (
        "CreatedOrder/FulfilledOrder/ClaimedOrder (DLN) and Sent/Claimed (Gate) "
        "decode, id correlation, out-of-order join, and reorg/rewind are complete "
        "and fixture-proven. Live scanning requires per-chain RPC endpoints "
        "(credential-gated). deBridge attestation is an OFF-CHAIN validator-set "
        "signature observable only through the deBridge API (credential-gated); "
        "the adapter never synthesizes a verified phase from chain logs."
    )
    cert_required_credentials = ("per_chain_rpc_url", "debridge_api_key")
    cert_required_endpoints = ("evm_json_rpc", "debridge_stats_api")
    cert_secret_ref_names = ("debridge_rpc_url", "debridge_api_key")

    def __init__(
        self,
        rpc_client: Optional[RpcClient] = None,
        chain_networks: Optional[dict[int, dict[str, str]]] = None,
        confirmations: int = DEFAULT_CONFIRMATIONS,
        max_block_span: int = DEFAULT_MAX_BLOCK_SPAN,
    ) -> None:
        self.rpc = rpc_client
        self.chain_networks = chain_networks or dict(DEFAULT_CHAIN_NETWORKS)
        self.confirmations = confirmations
        self.max_block_span = max_block_span

    # ── decoding ────────────────────────────────────────────────────────────

    def _network(self, chain_id: int) -> str:
        return self.chain_networks.get(chain_id, {}).get("network_id", f"debridge-chain:{chain_id}")

    def _endpoint_ref(self, raw_log: dict[str, Any], gateway: str) -> dict[str, Any]:
        network_id = raw_log.get("network_id", "unknown")
        return {
            "network_id": network_id,
            "native_chain_id": raw_log.get("native_chain_id", ""),
            "transaction_hash": raw_log.get("transactionHash"),
            "block_number": _as_block_number(raw_log.get("blockNumber", 0)),
            "block_hash": raw_log.get("blockHash"),
            "log_index": _as_int(raw_log.get("logIndex", 0)),
            "gateway_id": f"debridge:{gateway}:{network_id}",
        }

    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        topics = raw_log.get("topics") or []
        if not topics:
            return None
        topic0 = topics[0].lower()

        if topic0 == TOPIC_CREATED_ORDER:
            return self._decode_created_order(raw_log)
        if topic0 == TOPIC_FULFILLED_ORDER:
            return self._decode_fulfilled_order(raw_log)
        if topic0 == TOPIC_CLAIMED_ORDER:
            return self._decode_claimed_order(raw_log)
        if topic0 == TOPIC_SENT:
            return self._decode_sent(raw_log)
        if topic0 == TOPIC_CLAIMED:
            return self._decode_claimed(raw_log)
        return None

    def _base(self, raw_log: dict[str, Any], gateway: str) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "observed_at": raw_log.get("observed_at") or utc_now_iso(),
            "endpoint_ref": self._endpoint_ref(raw_log, gateway),
        }

    def _decode_created_order(self, raw_log: dict[str, Any]) -> dict[str, Any]:
        data = _strip0x(raw_log["data"])
        order_offset = int.from_bytes(data[0:32], "big")
        order_id = "0x" + data[32:64].hex()
        order = decode_dln_order(data[order_offset:])
        return {
            **self._base(raw_log, "dln_source"),
            "phase": "sent",
            "protocol_product": "intent",
            "correlation_key": f"dbr:order:{order_id}",
            "sequence": str(order["maker_order_nonce"]),
            "source_network_id": self._network(order["give_chain_id"]),
            "destination_network_id": self._network(order["take_chain_id"]),
            "provider_message_refs": [
                {"alias_type": "order_id", "alias_value": order_id, "canonical": True},
                {"alias_type": "give_chain_id", "alias_value": str(order["give_chain_id"]), "canonical": False},
                {"alias_type": "take_chain_id", "alias_value": str(order["take_chain_id"]), "canonical": False},
            ],
            "provider_native_stage": "CreatedOrder",
            "provider_extension": {
                "give_amount": order["give_amount"],
                "take_amount": order["take_amount"],
                "maker": order["maker"],
            },
        }

    def _decode_fulfilled_order(self, raw_log: dict[str, Any]) -> dict[str, Any]:
        data = _strip0x(raw_log["data"])
        order_offset = int.from_bytes(data[0:32], "big")
        order_id = "0x" + data[32:64].hex()
        taker = "0x" + data[64:96][-20:].hex()
        order = decode_dln_order(data[order_offset:])
        return {
            **self._base(raw_log, "dln_destination"),
            "phase": "delivered",
            "protocol_product": "intent",
            "correlation_key": f"dbr:order:{order_id}",
            "source_network_id": self._network(order["give_chain_id"]),
            "destination_network_id": self._network(order["take_chain_id"]),
            "provider_message_refs": [
                {"alias_type": "order_id", "alias_value": order_id, "canonical": True},
            ],
            "provider_native_stage": "FulfilledOrder",
            "provider_extension": {"taker": taker, "take_amount": order["take_amount"]},
        }

    def _decode_claimed_order(self, raw_log: dict[str, Any]) -> dict[str, Any]:
        data = _strip0x(raw_log["data"])
        order_id = "0x" + data[0:32].hex()
        beneficiary = "0x" + data[32:64][-20:].hex()
        give_amount = str(int.from_bytes(data[64:96], "big"))
        return {
            **self._base(raw_log, "dln_source"),
            "phase": "settled",
            "protocol_product": "intent",
            "correlation_key": f"dbr:order:{order_id}",
            "provider_message_refs": [
                {"alias_type": "order_id", "alias_value": order_id, "canonical": True},
            ],
            "provider_native_stage": "ClaimedOrder",
            "provider_extension": {"beneficiary": beneficiary, "unlocked_give_amount": give_amount},
        }

    def _decode_sent(self, raw_log: dict[str, Any]) -> dict[str, Any]:
        topics = raw_log.get("topics") or []
        data = _strip0x(raw_log["data"])
        submission_id = "0x" + data[0:32].hex()
        amount = str(int.from_bytes(data[32:64], "big"))
        chain_to = _topic_uint(topics, 2)
        return {
            **self._base(raw_log, "gate"),
            "phase": "sent",
            "protocol_product": "messaging",
            "correlation_key": f"dbr:sub:{submission_id}",
            "destination_network_id": self._network(chain_to) if chain_to is not None else "unknown",
            "source_network_id": self._base(raw_log, "gate")["endpoint_ref"]["network_id"],
            "provider_message_refs": [
                {"alias_type": "submission_id", "alias_value": submission_id, "canonical": True},
                {"alias_type": "debridge_id", "alias_value": _topic_bytes32(topics, 1) or "", "canonical": False},
            ],
            "provider_native_stage": "Sent",
            "provider_extension": {"amount": amount},
        }

    def _decode_claimed(self, raw_log: dict[str, Any]) -> dict[str, Any]:
        topics = raw_log.get("topics") or []
        data = _strip0x(raw_log["data"])
        submission_id = "0x" + data[0:32].hex()
        amount = str(int.from_bytes(data[32:64], "big"))
        chain_from = _topic_uint(topics, 2)
        return {
            **self._base(raw_log, "gate"),
            "phase": "delivered",
            "protocol_product": "messaging",
            "correlation_key": f"dbr:sub:{submission_id}",
            "destination_network_id": self._base(raw_log, "gate")["endpoint_ref"]["network_id"],
            "source_network_id": self._network(chain_from) if chain_from is not None else None,
            "provider_message_refs": [
                {"alias_type": "submission_id", "alias_value": submission_id, "canonical": True},
            ],
            "provider_native_stage": "Claimed",
            "provider_extension": {"amount": amount},
        }

    # ── scanning ────────────────────────────────────────────────────────────

    async def _scan_cycle(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Windowed multi-chain scan with reorg detection, cursor-drift rewind,
        and rate-limit-safe resume (see the docstring on HyperlaneAdapter._scan_cycle
        for the identical resilience contract)."""
        if self.rpc is None:
            raise NotImplementedError(
                "debridge: live scanning requires an RPC client "
                "(credential-gated — configure per-chain RPC endpoints)"
            )
        checkpoint = dict(checkpoint or {})
        networks: dict[str, dict] = checkpoint.setdefault("networks", {})
        observations: list[dict[str, Any]] = []

        for chain_id, meta in self.chain_networks.items():
            network_id = meta["network_id"]
            state = networks.setdefault(
                network_id, {"last_scanned_block": 0, "recent_hashes": {}},
            )
            head = await self.rpc.get_head(network_id)
            head_number = int(head["number"])
            state["head_number"] = head_number
            safe_head = head_number - self.confirmations
            last = int(state["last_scanned_block"])

            if last > head_number:
                observations.append(self._reorg_observation(network_id, max(0, safe_head)))
                state["last_scanned_block"] = max(0, safe_head - 1)
                state["recent_hashes"] = {}
                continue

            recent = state.get("recent_hashes", {})
            if last and str(last) in recent:
                current_hash = await self.rpc.get_block_hash(network_id, last)
                if current_hash != recent[str(last)]:
                    fork_point = min(
                        (int(number) for number, block_hash in recent.items()
                         if block_hash != current_hash),
                        default=last,
                    )
                    observations.append(self._reorg_observation(network_id, fork_point))
                    state["last_scanned_block"] = max(0, fork_point - 1)
                    state["recent_hashes"] = {}
                    continue

            if safe_head <= last:
                continue

            window_start = last + 1
            try:
                while window_start <= safe_head:
                    window_end = min(window_start + self.max_block_span - 1, safe_head)
                    raw_logs = await self.rpc.get_logs(network_id, window_start, window_end)
                    for raw_log in raw_logs:
                        raw_log.setdefault("network_id", network_id)
                        raw_log.setdefault("native_chain_id", meta["native_chain_id"])
                        decoded = self._decode_safely(raw_log)
                        if decoded:
                            observations.append(decoded)
                    state["last_scanned_block"] = window_end
                    block_hash = await self.rpc.get_block_hash(network_id, window_end)
                    recent[str(window_end)] = block_hash
                    _prune_recent(recent)
                    window_start = window_end + 1
            except RpcRateLimited:
                pass
            state["recent_hashes"] = recent

        return observations, checkpoint

    def _reorg_observation(self, network_id: str, from_block: int) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "phase": "reorged",
            "network_id": network_id,
            "from_block": from_block,
            "observed_at": utc_now_iso(),
        }

    # ── health, security, certification ──────────────────────────────────────

    def health(self, checkpoint: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        networks = (checkpoint or {}).get("networks", {})
        return {
            "provider_id": self.provider_id,
            "rpc_configured": self.rpc is not None,
            "implementation_status": self.implementation_status.value,
            "networks": {
                network_id: {
                    "last_scanned_block": int(state.get("last_scanned_block", 0)),
                    "tracked_hashes": len(state.get("recent_hashes", {})),
                }
                for network_id, state in networks.items()
            },
            "observed_at": utc_now_iso(),
        }

    def security_model(self) -> dict[str, Any]:
        """Off-chain validator-set attestation — NOT a light client (IBC) and NOT
        a recipient-configured ISM (Hyperlane). DLN adds a solver-fulfillment
        settlement leg on top of the validator attestation."""
        return {
            "verification_model": "external_validator_set",
            "attestation_kind": "off_chain_validator_signatures",
            "attestation_on_chain": False,
            "attestation_source": "debridge_api",
            "has_independent_verification_event": False,
            "settlement_model": "dln_solver_fulfillment_then_unlock",
            "delivery_actor": "permissionless_solver",
            "trust_source": "debridge_validator_quorum",
        }

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        raise NotImplementedError(
            "debridge: live security-policy snapshots need the deBridge API "
            "(validator set / quorum) — credential-gated. The structural model "
            "is available offline via security_model()."
        )

    def certification_descriptor(self) -> Any:
        from shared.certification.descriptor import AdapterCertificationDescriptor
        from shared.certification.readiness import CredentialReadiness

        return AdapterCertificationDescriptor(
            provider=self.provider_id,
            domain="interop",
            adapter=type(self).__name__,
            adapter_version=self.adapter_version,
            supported_operations=[
                "message_observation", "intent_observation",
                "delivery_observation", "settlement_observation",
                "historical_backfill", "reorg_recovery",
            ],
            unsupported_operations=["solve", "fulfil", "claim", "signing", "recovery"],
            required_credentials=list(self.cert_required_credentials),
            required_endpoints=list(self.cert_required_endpoints),
            secret_ref_names=list(self.cert_secret_ref_names),
            pagination_model="page",
            streaming_model="none",
            rate_limit_behavior=(
                "provider 429 -> RateLimited; scan checkpoints the last completed "
                "block window and resumes next poll"
            ),
            retry_policy="poll-loop resume from persisted per-chain block cursor",
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=False,
        )


# ── small EVM helpers ────────────────────────────────────────────────────────

def _as_int(value: Any) -> int:
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    return int(value)


def _as_block_number(value: Any) -> str:
    return str(_as_int(value))


def _prune_recent(recent: dict[str, str]) -> None:
    if len(recent) > _RECENT_HASHES_KEPT:
        for stale_key in sorted(recent, key=int)[:-_RECENT_HASHES_KEPT]:
            recent.pop(stale_key, None)


def _topic_bytes32(topics: list, index: int) -> Optional[str]:
    if len(topics) <= index:
        return None
    value = topics[index]
    return value.lower() if value.startswith("0x") else "0x" + value.lower()


def _topic_uint(topics: list, index: int) -> Optional[int]:
    if len(topics) <= index:
        return None
    return _as_int(topics[index])
