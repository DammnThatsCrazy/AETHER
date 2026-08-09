"""Chainlink CCIP observation adapter — real OnRamp / CommitStore / OffRamp decode.

Implementation status: CREDENTIAL_GATED. OnRamp ``CCIPSendRequested`` decode,
CommitStore ``ReportAccepted`` interval decode, OffRamp ``ExecutionStateChanged``
decode, messageId correlation, interval-commit expansion, retry/failure
classification, and reorg handling are complete and fixture-proven; LIVE
scanning requires per-lane RPC endpoints and DON/RMN metadata. Live seams are
injected. OBSERVE only — no relay, manual execution, or recovery
(``execution_by_aether=False``).

Security & finality semantics (NOT interchangeable with other providers)
------------------------------------------------------------------------
CCIP verification is a **two-network, interval-based** model:
  1. The **Committing DON** (a decentralized oracle network) attests source
     finality and posts a Merkle root covering a *contiguous sequence-number
     interval* [min,max] for one lane (CommitStore ``ReportAccepted``).
  2. The **Risk Management Network (RMN)** independently "blesses" that root — a
     separate, minority-honest anti-fraud layer that must agree before any
     message under the root can be delivered.
  3. The **Executing DON** then executes each message on the destination OffRamp
     (``ExecutionStateChanged``).
Verification therefore covers a *range* of messages, not one messageId, and
requires TWO independent committees (DON + RMN). This is materially different
from Wormhole's single 19-guardian multisig, Axelar's PoS validator set, and
LayerZero's per-app DVN set. The commit interval must be expanded against the
source-side sequence index to attribute the ``verified`` stage to a messageId.

This decoder targets CCIP v1.2 (per-lane OnRamp/CommitStore/OffRamp). v1.5
relocates the commit into the OffRamp as ``CommitReportAccepted`` and folds the
lane selectors into the message; the interval/blessing semantics are unchanged.

Canonical id & lifecycle
-------------------------
    messageId (bytes32)          -> canonical message id ("ccip:<messageId>")
    CCIPSendRequested            -> phase "sent"      (source OnRamp)
    ReportAccepted (interval)    -> phase "verified"  (DON commit, expanded per seq)
    ExecutionStateChanged SUCCESS-> phase "delivered" (destination OffRamp)
    ExecutionStateChanged FAILURE-> phase "failed"
    ExecutionStateChanged IN_PROGRESS -> retry/attempt (tracked, not lifecycle)
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from eth_utils import keccak

from services.integrations.connectors.base import ImplementationStatus
from services.interop.foundation import utc_now_iso
from services.interop.providers.base import InteropProviderAdapter, OperationalFieldsMixin
from services.interop.providers.transport import RpcRateLimited
from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import CredentialReadiness

# ── Event signatures ─────────────────────────────────────────────────────────
# EVM2EVMOnRamp.CCIPSendRequested(EVM2EVMMessage) — tuple expanded to its canonical form.
SIG_CCIP_SEND_REQUESTED = (
    "CCIPSendRequested((uint64,address,address,uint64,uint256,bool,uint64,address,"
    "uint256,bytes,(address,uint256)[],bytes[],bytes32))"
)
# EVM2EVMOffRamp.ExecutionStateChanged(uint64 seq, bytes32 messageId, uint8 state, bytes returnData)
SIG_EXECUTION_STATE_CHANGED = "ExecutionStateChanged(uint64,bytes32,uint8,bytes)"
# CommitStore.ReportAccepted(CommitReport) — PriceUpdates, Interval(min,max), merkleRoot.
SIG_REPORT_ACCEPTED = (
    "ReportAccepted((((address,uint224)[],(uint64,uint224)[]),(uint64,uint64),bytes32))"
)

TOPIC_CCIP_SEND_REQUESTED = "0x" + keccak(text=SIG_CCIP_SEND_REQUESTED).hex()
TOPIC_EXECUTION_STATE_CHANGED = "0x" + keccak(text=SIG_EXECUTION_STATE_CHANGED).hex()
TOPIC_REPORT_ACCEPTED = "0x" + keccak(text=SIG_REPORT_ACCEPTED).hex()

# OffRamp MessageExecutionState enum.
EXEC_STATE = {0: "UNTOUCHED", 1: "IN_PROGRESS", 2: "SUCCESS", 3: "FAILURE"}

# chain selector -> network metadata (seeded mainnets; extended via config).
DEFAULT_CCIP_SELECTORS: dict[int, dict[str, str]] = {
    5009297550715157269: {"network_id": "ethereum-mainnet", "native_chain_id": "1"},
    4949039107694359620: {"network_id": "arbitrum-mainnet", "native_chain_id": "42161"},
    15971525489660198786: {"network_id": "base-mainnet", "native_chain_id": "8453"},
}

DEFAULT_CONFIRMATIONS = 15
DEFAULT_MAX_BLOCK_SPAN = 2_000
_RECENT_HASHES_KEPT = 32


class CcipRateLimitError(RpcRateLimited):
    def __init__(self, message: str = "rate limited", retry_after: Optional[int] = None) -> None:
        super().__init__(message, retry_after=retry_after)


class RpcClient(Protocol):
    async def get_head(self, network_id: str) -> dict[str, Any]: ...
    async def get_logs(
        self, network_id: str, from_block: int, to_block: int,
    ) -> list[dict[str, Any]]: ...
    async def get_block_hash(self, network_id: str, block_number: int) -> str: ...


# ── pure ABI helpers ─────────────────────────────────────────────────────────

def _strip0x(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def _word(value: int) -> bytes:
    return value.to_bytes(32, "big")


def _addr_word(address: str) -> bytes:
    return int(address, 16).to_bytes(32, "big")


def encode_ccip_send_requested_data(
    source_chain_selector: int, sender: str, receiver: str,
    sequence_number: int, message_id: str,
    gas_limit: int = 200_000, strict: bool = False, nonce: int = 1,
    fee_token: str = "0x" + "00" * 20, fee_token_amount: int = 0,
) -> str:
    """ABI-encode CCIPSendRequested(EVM2EVMMessage). The message is a dynamic
    tuple; its STATIC members (selector, sender, receiver, sequence, messageId)
    are stored inline in the tuple head at fixed word offsets, so we decode them
    without walking the dynamic tails. Dynamic members are encoded empty here."""
    head_words = 13
    head_len = head_words * 32
    o_data = head_len
    o_token_amounts = head_len + 32
    o_source_token_data = head_len + 64
    tuple_head = (
        _word(source_chain_selector)          # 0 sourceChainSelector
        + _addr_word(sender)                  # 1 sender
        + _addr_word(receiver)                # 2 receiver
        + _word(sequence_number)              # 3 sequenceNumber
        + _word(gas_limit)                    # 4 gasLimit
        + _word(1 if strict else 0)           # 5 strict
        + _word(nonce)                        # 6 nonce
        + _addr_word(fee_token)               # 7 feeToken
        + _word(fee_token_amount)             # 8 feeTokenAmount
        + _word(o_data)                       # 9 -> data bytes
        + _word(o_token_amounts)              # 10 -> tokenAmounts[]
        + _word(o_source_token_data)          # 11 -> sourceTokenData[]
        + _strip0x(message_id).rjust(32, b"\x00")  # 12 messageId
    )
    tails = _word(0) + _word(0) + _word(0)  # empty data, empty arrays
    return "0x" + (_word(0x20) + tuple_head + tails).hex()


def decode_ccip_send_requested_data(data_hex: str) -> dict[str, Any]:
    """Decode the inline static members of EVM2EVMMessage from the event tuple."""
    data = _strip0x(data_hex)
    if len(data) < 32:
        raise ValueError("CCIPSendRequested data too short")
    tuple_off = int.from_bytes(data[0:32], "big")
    if len(data) < tuple_off + 13 * 32:
        raise ValueError("CCIPSendRequested tuple truncated")

    def word(i: int) -> bytes:
        base = tuple_off + i * 32
        return data[base: base + 32]

    return {
        "source_chain_selector": int.from_bytes(word(0), "big"),
        "sender": "0x" + word(1)[-20:].hex(),
        "receiver": "0x" + word(2)[-20:].hex(),
        "sequence_number": int.from_bytes(word(3), "big"),
        "gas_limit": int.from_bytes(word(4), "big"),
        "nonce": int.from_bytes(word(6), "big"),
        "message_id": "0x" + word(12).hex(),
    }


def encode_execution_state_changed_data(state: int, return_data: bytes = b"") -> str:
    """ABI-encode ExecutionStateChanged data: (uint8 state, bytes returnData)."""
    head = 2 * 32
    padded = return_data.ljust((len(return_data) + 31) // 32 * 32, b"\x00") if return_data else b""
    data = _word(state) + _word(head) + _word(len(return_data)) + padded
    return "0x" + data.hex()


def decode_execution_state_changed_data(data_hex: str) -> dict[str, Any]:
    data = _strip0x(data_hex)
    if len(data) < 64:
        raise ValueError("ExecutionStateChanged data too short")
    state = int.from_bytes(data[0:32], "big")
    return_offset = int.from_bytes(data[32:64], "big")
    return_len = int.from_bytes(data[return_offset:return_offset + 32], "big") if len(data) >= return_offset + 32 else 0
    return_data = data[return_offset + 32: return_offset + 32 + return_len]
    return {"state": state, "return_data": "0x" + return_data.hex()}


def encode_commit_report_data(min_seq: int, max_seq: int, merkle_root: str) -> str:
    """ABI-encode CommitStore.ReportAccepted(CommitReport). interval.min /
    interval.max / merkleRoot are inline in the CommitReport tuple head after the
    (dynamic) priceUpdates offset; priceUpdates is encoded empty."""
    price_updates_off = 4 * 32  # after [priceUpdates_off, min, max, merkleRoot]
    tuple_head = (
        _word(price_updates_off)
        + _word(min_seq)
        + _word(max_seq)
        + _strip0x(merkle_root).rjust(32, b"\x00")
    )
    # PriceUpdates = ((address,uint224)[], (uint64,uint224)[]) — both empty.
    price_updates = _word(0x40) + _word(0x60) + _word(0) + _word(0)
    return "0x" + (_word(0x20) + tuple_head + price_updates).hex()


def decode_commit_report_data(data_hex: str) -> dict[str, Any]:
    data = _strip0x(data_hex)
    if len(data) < 32:
        raise ValueError("ReportAccepted data too short")
    tuple_off = int.from_bytes(data[0:32], "big")
    if len(data) < tuple_off + 128:
        raise ValueError("CommitReport tuple truncated")
    min_seq = int.from_bytes(data[tuple_off + 32: tuple_off + 64], "big")
    max_seq = int.from_bytes(data[tuple_off + 64: tuple_off + 96], "big")
    merkle_root = "0x" + data[tuple_off + 96: tuple_off + 128].hex()
    return {"min_seq": min_seq, "max_seq": max_seq, "merkle_root": merkle_root}


def ccip_correlation_key(message_id: str) -> str:
    mid = message_id.lower()
    if not mid.startswith("0x"):
        mid = "0x" + mid
    return f"ccip:{mid}"


def _seq_index_key(source_chain_selector: int, sequence_number: int) -> str:
    return f"{source_chain_selector}:{sequence_number}"


class ChainlinkCcipAdapter(OperationalFieldsMixin, InteropProviderAdapter):
    provider_id = "chainlink_ccip"
    provider_kind = "chainlink_ccip"
    display_name = "Chainlink CCIP (DON+RMN observation adapter)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("v1.2",)
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = (
        "message_observation", "historical_backfill", "direct_rpc_observation",
        "payload_decoding", "attestation_observation", "delivery_observation",
        "retry_tracking", "asset_transfer",
    )
    known_limitations = (
        "OnRamp CCIPSendRequested decode, CommitStore ReportAccepted interval "
        "decode + per-sequence expansion, OffRamp ExecutionStateChanged decode "
        "(success/failure/in-progress), messageId correlation, and reorg "
        "handling are complete and fixture-proven. Live scanning requires "
        "per-lane RPC endpoints and DON/RMN metadata (credential-gated)."
    )

    def __init__(
        self,
        rpc_client: Optional[RpcClient] = None,
        selectors: Optional[dict[int, dict[str, str]]] = None,
        confirmations: int = DEFAULT_CONFIRMATIONS,
        max_block_span: int = DEFAULT_MAX_BLOCK_SPAN,
        endpoint_refs: Optional[dict[str, str]] = None,
        secret_refs: Optional[dict[str, str]] = None,
    ) -> None:
        self.rpc = rpc_client
        self.selectors = selectors or dict(DEFAULT_CCIP_SELECTORS)
        self.confirmations = confirmations
        self.max_block_span = max_block_span
        self.endpoint_refs = dict(endpoint_refs or {})
        self.secret_refs = dict(secret_refs or {})

    # ── decoding ─────────────────────────────────────────────────────────────

    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        topics = raw_log.get("topics") or []
        if not topics:
            return None
        topic0 = topics[0].lower()
        base = self._endpoint_base(raw_log)

        if topic0 == TOPIC_CCIP_SEND_REQUESTED:
            decoded = decode_ccip_send_requested_data(raw_log["data"])
            key = ccip_correlation_key(decoded["message_id"])
            dest_selector = raw_log.get("dest_chain_selector")
            return {
                **base,
                "phase": "sent",
                "correlation_key": key,
                "sequence": str(decoded["sequence_number"]),
                "source_network_id": self._network(decoded["source_chain_selector"]),
                "destination_network_id": self._network(dest_selector) if dest_selector else "unknown",
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": key, "canonical": True},
                    {"alias_type": "sequence_number", "alias_value": str(decoded["sequence_number"]), "canonical": False},
                    {"alias_type": "source_chain_selector", "alias_value": str(decoded["source_chain_selector"]), "canonical": False},
                ],
                "provider_native_stage": "CCIPSendRequested",
                "provider_extension": {
                    "sender": decoded["sender"],
                    "receiver": decoded["receiver"],
                    "gas_limit": decoded["gas_limit"],
                    "nonce": decoded["nonce"],
                    "source_chain_selector": decoded["source_chain_selector"],
                    "sequence_number": decoded["sequence_number"],
                },
            }

        if topic0 == TOPIC_REPORT_ACCEPTED:
            report = decode_commit_report_data(raw_log["data"])
            source_selector = raw_log.get("source_chain_selector")
            return {
                **base,
                "phase": "verified_interval",  # expanded per-seq by the adapter
                "source_chain_selector": source_selector,
                "min_seq": report["min_seq"],
                "max_seq": report["max_seq"],
                "merkle_root": report["merkle_root"],
                "provider_native_stage": "ReportAccepted",
            }

        if topic0 == TOPIC_EXECUTION_STATE_CHANGED:
            if len(topics) < 3:
                return None
            sequence_number = int(topics[1], 16)
            message_id = self._bytes32(topics[2])
            decoded = decode_execution_state_changed_data(raw_log["data"])
            state = decoded["state"]
            key = ccip_correlation_key(message_id)
            source_selector = raw_log.get("source_chain_selector")
            common = {
                **base,
                "correlation_key": key,
                "sequence": str(sequence_number),
                "source_network_id": self._network(source_selector) if source_selector else "unknown",
                "destination_network_id": raw_log.get("network_id", "unknown"),
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": key, "canonical": True},
                    {"alias_type": "sequence_number", "alias_value": str(sequence_number), "canonical": False},
                ],
                "provider_native_stage": f"ExecutionStateChanged:{EXEC_STATE.get(state, state)}",
                "provider_extension": {
                    "execution_state": EXEC_STATE.get(state, str(state)),
                    "return_data": decoded["return_data"],
                },
            }
            if state == 2:  # SUCCESS
                return {**common, "phase": "delivered"}
            if state == 3:  # FAILURE
                return {**common, "phase": "failed"}
            # IN_PROGRESS / UNTOUCHED: a delivery attempt, tracked for retries but
            # not a canonical lifecycle transition.
            return {**common, "phase": "delivery_attempted", "lifecycle_phase": False}

        return None

    def expand_commit(
        self, interval_obs: dict[str, Any], seq_index: dict[str, str],
        observed_at: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Expand a commit interval into per-message ``verified`` observations by
        matching (source_chain_selector, seq) against the source-side index."""
        selector = interval_obs.get("source_chain_selector")
        if selector is None:
            return []
        out: list[dict[str, Any]] = []
        for seq in range(int(interval_obs["min_seq"]), int(interval_obs["max_seq"]) + 1):
            key = seq_index.get(_seq_index_key(int(selector), seq))
            if not key:
                continue
            out.append({
                "provider_id": self.provider_id,
                "provider_kind": self.provider_kind,
                "observed_at": observed_at or interval_obs.get("observed_at") or utc_now_iso(),
                "phase": "verified",
                "correlation_key": key,
                "sequence": str(seq),
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": key, "canonical": True},
                ],
                "provider_native_stage": "CommitReportBlessed",
                "provider_extension": {
                    "merkle_root": interval_obs.get("merkle_root"),
                    "commit_interval": [int(interval_obs["min_seq"]), int(interval_obs["max_seq"])],
                    "verification_model": "committing_don_plus_rmn_blessing",
                },
            })
        return out

    # ── scanning ─────────────────────────────────────────────────────────────

    async def _scan_cycle(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if self.rpc is None:
            raise NotImplementedError(
                "chainlink_ccip: live scanning requires an RPC client "
                "(credential-gated — configure per-lane RPC endpoints)"
            )
        checkpoint = dict(checkpoint or {})
        networks: dict[str, dict] = checkpoint.setdefault("networks", {})
        seq_index: dict[str, str] = checkpoint.setdefault("seq_index", {})
        health: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        intervals: list[dict[str, Any]] = []

        for selector, meta in self.selectors.items():
            network_id = meta["network_id"]
            state = networks.setdefault(
                network_id, {"last_scanned_block": 0, "recent_hashes": {}},
            )
            if await self._scan_one_network(
                selector, meta, state, seq_index, observations, intervals, health,
            ):
                continue

        # Expand every commit interval seen in this pass against the (now-updated)
        # source sequence index — attributes the verified stage to each messageId.
        for interval in intervals:
            observations.extend(self.expand_commit(interval, seq_index))

        checkpoint["health"] = health
        return observations, checkpoint

    async def _scan_one_network(
        self, selector, meta, state, seq_index, observations, intervals, health,
    ) -> bool:
        network_id = meta["network_id"]
        head = await self.rpc.get_head(network_id)
        head_number = int(head["number"])
        state["head_number"] = head_number
        safe_head = head_number - self.confirmations
        last = int(state["last_scanned_block"])
        recent = state.setdefault("recent_hashes", {})

        if last > head_number:
            observations.append(self._discontinuity("cursor_drift", network_id, safe_head, last))
            state["last_scanned_block"] = max(0, safe_head)
            state["recent_hashes"] = {}
            health.append({"provider_id": self.provider_id, "network_id": network_id,
                           "state": "cursor_drift", "rewound_to": max(0, safe_head)})
            return True

        if last and str(last) in recent:
            current_hash = await self.rpc.get_block_hash(network_id, last)
            if current_hash != recent[str(last)]:
                fork_point = min(
                    (int(n) for n, h in recent.items() if h != current_hash), default=last,
                )
                observations.append(self._discontinuity("block_hash", network_id, fork_point, last))
                state["last_scanned_block"] = max(0, fork_point - 1)
                state["recent_hashes"] = {}
                health.append({"provider_id": self.provider_id, "network_id": network_id,
                               "state": "reorged", "from_block": fork_point})
                return True

        get_block = getattr(self.rpc, "get_block", None)
        if last and get_block is not None and str(last) in recent:
            nxt = await get_block(network_id, last + 1)
            parent = (nxt or {}).get("parentHash")
            if parent and parent != recent[str(last)]:
                observations.append(self._discontinuity("parent_hash", network_id, last, last))
                state["last_scanned_block"] = max(0, last - 1)
                state["recent_hashes"] = {}
                health.append({"provider_id": self.provider_id, "network_id": network_id,
                               "state": "parent_hash_discontinuity", "from_block": last})
                return True

        if safe_head <= last:
            return False

        cursor = last
        while cursor < safe_head:
            window_to = min(cursor + self.max_block_span, safe_head)
            try:
                raw_logs = await self.rpc.get_logs(network_id, cursor + 1, window_to)
            except RpcRateLimited as exc:
                health.append({"provider_id": self.provider_id, "network_id": network_id,
                               "state": "rate_limited", "retry_after": exc.retry_after,
                               "resumed_from_block": cursor})
                break
            for raw_log in raw_logs:
                raw_log.setdefault("network_id", network_id)
                raw_log.setdefault("native_chain_id", meta["native_chain_id"])
                decoded = self._decode_safely(raw_log)
                if decoded is None:
                    continue
                if decoded["phase"] == "verified_interval":
                    intervals.append(decoded)
                    continue
                observations.append(decoded)
                if decoded["phase"] == "sent":
                    ext = decoded["provider_extension"]
                    seq_index[_seq_index_key(ext["source_chain_selector"], ext["sequence_number"])] = \
                        decoded["correlation_key"]
            cursor = window_to
            state["last_scanned_block"] = cursor
            recent[str(cursor)] = await self.rpc.get_block_hash(network_id, cursor)
            self._trim(recent)
        state["recent_hashes"] = recent
        return False

    # ── health / security / certification ────────────────────────────────────

    def health(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        context = context or {}
        configured = context.get("configured", self.rpc is not None)
        return {
            "provider_id": self.provider_id,
            "healthy": bool(configured),
            "state": "ok" if configured else "unconfigured",
            "rpc_wired": self.rpc is not None,
        }

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        return {
            "verification_model": "committing_don_plus_rmn_blessing",
            "required_verifier_ids": [f"ccip-committing-don:{path_id}"],
            "optional_verifier_ids": [f"ccip-rmn:{path_id}"],
            "optional_threshold": None,  # RMN minority-honest blessing quorum
            "confirmations_required": self.confirmations,
            "delivery_actor_ids": [f"ccip-executing-don:{path_id}"],
            "module_addresses": {
                "on_ramp": self.endpoint_refs.get("on_ramp", ""),
                "commit_store": self.endpoint_refs.get("commit_store", ""),
                "off_ramp": self.endpoint_refs.get("off_ramp", ""),
                "rmn": self.endpoint_refs.get("rmn", ""),
            },
        }

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        return AdapterCertificationDescriptor(
            provider=self.provider_id,
            domain="interoperability",
            adapter="ChainlinkCcipAdapter",
            adapter_version="1.0.0",
            supported_operations=[
                "observe_source_message", "observe_commit_attestation",
                "observe_delivery", "observe_failure", "retry_tracking",
                "reorg_detection", "checkpoint_persistence", "security_policy_snapshot",
            ],
            unsupported_operations=[
                "relay", "manual_execution", "message_recovery", "signing",
            ],
            required_credentials=["ccip_don_metadata"],
            required_endpoints=["source_evm_rpc_url", "dest_evm_rpc_url"],
            secret_ref_names=sorted(self.secret_refs.keys()) or ["ccip_rpc_api_key_ref"],
            pagination_model="time_window",
            streaming_model="polling",
            rate_limit_behavior="honor_retry_after_and_resume_from_checkpoint",
            retry_policy="resume_from_last_confirmed_block",
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=False,
        )

    # ── certification duck-hooks ─────────────────────────────────────────────

    def build_request(self, ctx: dict[str, Any]) -> dict[str, Any]:
        credential = ctx.get("credential") or {}
        return {
            "endpoint": self.endpoint_refs.get("dest_evm_rpc_url", "dest_evm_rpc_url_ref"),
            "headers": {"authorization": credential.get("api_key", "")},
            "params": {"tenant_id": ctx.get("tenant_id", "")},
        }

    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _sanitize(payload)

    def dedupe_key(self, event: dict[str, Any]) -> str:
        return str(event.get("messageId") or event.get("correlation_key") or event.get("id"))

    def sequence_of(self, event: dict[str, Any]) -> int:
        return int(event.get("seq") or event.get("sequence") or event.get("sequence_number") or 0)

    def normalize(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not isinstance(payload, dict) or not payload.get("topics"):
            return None
        return self.decode_log(payload)

    # ── internals ────────────────────────────────────────────────────────────

    def _endpoint_base(self, raw_log: dict[str, Any]) -> dict[str, Any]:
        network_id = raw_log.get("network_id", "unknown")
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "observed_at": raw_log.get("observed_at") or utc_now_iso(),
            "endpoint_ref": {
                "network_id": network_id,
                "native_chain_id": raw_log.get("native_chain_id", ""),
                "transaction_hash": raw_log.get("transactionHash"),
                "block_number": _block_number(raw_log),
                "block_hash": raw_log.get("blockHash"),
                "log_index": _log_index(raw_log),
                "gateway_id": f"chainlink_ccip:ramp:{network_id}",
            },
        }

    def _discontinuity(self, kind: str, network_id: str, from_block: int, cursor: int) -> dict:
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "phase": "reorged",
            "discontinuity_kind": kind,
            "network_id": network_id,
            "from_block": from_block,
            "previous_cursor": cursor,
            "observed_at": utc_now_iso(),
        }

    def _network(self, selector: Optional[int]) -> str:
        if selector is None:
            return "unknown"
        return self.selectors.get(int(selector), {}).get("network_id", f"ccip-selector:{selector}")

    @staticmethod
    def _bytes32(topic: str) -> str:
        raw = topic[2:] if topic.startswith("0x") else topic
        return "0x" + raw.rjust(64, "0").lower()

    @staticmethod
    def _trim(recent: dict[str, str]) -> None:
        if len(recent) > _RECENT_HASHES_KEPT:
            for stale in sorted(recent, key=int)[:-_RECENT_HASHES_KEPT]:
                recent.pop(stale, None)


def _block_number(raw_log: dict[str, Any]) -> str:
    value = raw_log.get("blockNumber", 0)
    if isinstance(value, str) and value.startswith("0x"):
        return str(int(value, 16))
    return str(value)


def _log_index(raw_log: dict[str, Any]) -> int:
    value = raw_log.get("logIndex", 0)
    if isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    return int(value)


_SECRET_KEYS = {"authorization", "api_key", "apikey", "password", "token", "secret", "private_key"}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in _SECRET_KEYS else _sanitize(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value
