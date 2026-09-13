"""Axelar GMP observation adapter — real gateway ContractCall/Approved decode.

Implementation status: CREDENTIAL_GATED. Gateway decode, GMP-message-id
correlation, validator-confirmation attestation decode, and reorg handling are
complete and fixture-proven; LIVE scanning requires per-network RPC endpoints
and (for the validator-confirmation leg) Axelar network / Axelarscan API access.
Every live seam is injected. OBSERVE only — no relay, no command execution, no
approval submission, no recovery (``execution_by_aether=False``).

Security & finality semantics (NOT interchangeable with other providers)
------------------------------------------------------------------------
Axelar's verification is a **proof-of-stake validator/verifier set**: source
events are confirmed by the Axelar network's validators (Amplifier verifier sets
vote, weighted by stake with quadratic voting) reaching a >=2/3 BFT super-
majority on the Axelar (Cosmos-SDK) chain; the destination gateway then accepts
a validator-signed command batch and emits ``ContractCallApproved``. This is a
staked, rotating validator set finalizing on an independent PoS chain — NOT
Wormhole's fixed 19-guardian multisig, NOT LayerZero's per-app DVN set, and NOT
CCIP's DON + RMN blessing. Source finality is the source-chain confirmation
depth Axelar waits before its validators vote.

Canonical id & lifecycle
-------------------------
The canonical Axelar GMP message id is (sourceChain, sourceTxHash,
sourceEventIndex). ``ContractCall`` carries it implicitly (its own tx hash +
log index on the source gateway); ``ContractCallApproved`` carries it explicitly
in event data — so both legs correlate on the same key even out of order.

    ContractCall / ...WithToken  -> phase "sent"      (source gateway)
    validator confirmation       -> phase "verified"  (Axelar network, API-gated)
    ContractCallApproved         -> phase "delivered" (destination gateway approved)
    ContractCallExecuted         -> phase "executed"  (app ran; commandId-bound)
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from eth_utils import keccak

from services.integrations.connectors.base import ImplementationStatus
from services.interop.foundation import utc_now_iso
from services.interop.providers.base import InteropProviderAdapter
from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import CredentialReadiness

# ── Event signatures (Axelar EVM gateway) ────────────────────────────────────
SIG_CONTRACT_CALL = "ContractCall(address,string,string,bytes32,bytes)"
SIG_CONTRACT_CALL_WITH_TOKEN = (
    "ContractCallWithToken(address,string,string,bytes32,bytes,string,uint256)"
)
SIG_CONTRACT_CALL_APPROVED = (
    "ContractCallApproved(bytes32,string,string,address,bytes32,bytes32,uint256)"
)
SIG_CONTRACT_CALL_EXECUTED = "ContractCallExecuted(bytes32)"

TOPIC_CONTRACT_CALL = "0x" + keccak(text=SIG_CONTRACT_CALL).hex()
TOPIC_CONTRACT_CALL_WITH_TOKEN = "0x" + keccak(text=SIG_CONTRACT_CALL_WITH_TOKEN).hex()
TOPIC_CONTRACT_CALL_APPROVED = "0x" + keccak(text=SIG_CONTRACT_CALL_APPROVED).hex()
TOPIC_CONTRACT_CALL_EXECUTED = "0x" + keccak(text=SIG_CONTRACT_CALL_EXECUTED).hex()

# network_id -> Axelar chain name (case as Axelar registers it) + native chain id.
DEFAULT_AXELAR_CHAINS: dict[str, dict[str, str]] = {
    "ethereum-mainnet": {"axelar_chain": "Ethereum", "native_chain_id": "1"},
    "arbitrum-mainnet": {"axelar_chain": "arbitrum", "native_chain_id": "42161"},
    "base-mainnet": {"axelar_chain": "base", "native_chain_id": "8453"},
}

DEFAULT_CONFIRMATIONS = 15
DEFAULT_MAX_BLOCK_SPAN = 2_000
_RECENT_HASHES_KEPT = 32


class AxelarRateLimitError(Exception):
    def __init__(self, message: str = "rate limited", retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RpcClient(Protocol):
    async def get_head(self, network_id: str) -> dict[str, Any]: ...
    async def get_logs(
        self, network_id: str, from_block: int, to_block: int,
    ) -> list[dict[str, Any]]: ...
    async def get_block_hash(self, network_id: str, block_number: int) -> str: ...


class ConfirmationClient(Protocol):
    """Injected Axelar network / Axelarscan access for the validator-confirmation
    leg. Returns the confirmation record for a GMP message id, or None when the
    validators have not yet confirmed. Credential-gated."""

    async def get_confirmation(self, message_id: str) -> Optional[dict[str, Any]]: ...


# ── pure ABI helpers ─────────────────────────────────────────────────────────

def _strip0x(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def _word(value: int) -> bytes:
    return value.to_bytes(32, "big")


def _pad(value: bytes) -> bytes:
    return value.ljust((len(value) + 31) // 32 * 32, b"\x00")


def _dyn_string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return _word(len(raw)) + _pad(raw)


def _dyn_bytes(raw: bytes) -> bytes:
    return _word(len(raw)) + _pad(raw)


def _read_string(data: bytes, offset: int) -> str:
    length = int.from_bytes(data[offset:offset + 32], "big")
    return data[offset + 32: offset + 32 + length].decode("utf-8")


def _read_bytes(data: bytes, offset: int) -> bytes:
    length = int.from_bytes(data[offset:offset + 32], "big")
    return data[offset + 32: offset + 32 + length]


def encode_contract_call_data(
    destination_chain: str, destination_contract_address: str, payload: bytes,
) -> str:
    """ABI-encode ContractCall data: (string, string, bytes) — 3 dynamic heads."""
    head = 3 * 32
    dc, dca, pay = _dyn_string(destination_chain), _dyn_string(destination_contract_address), _dyn_bytes(payload)
    o_dc, o_dca, o_pay = head, head + len(dc), head + len(dc) + len(dca)
    return "0x" + (_word(o_dc) + _word(o_dca) + _word(o_pay) + dc + dca + pay).hex()


def encode_contract_call_with_token_data(
    destination_chain: str, destination_contract_address: str, payload: bytes,
    symbol: str, amount: int,
) -> str:
    """ABI-encode ContractCallWithToken data:
    (string, string, bytes, string, uint256) — head = 4 dynamic offsets + amount."""
    head = 5 * 32
    dc = _dyn_string(destination_chain)
    dca = _dyn_string(destination_contract_address)
    pay = _dyn_bytes(payload)
    sym = _dyn_string(symbol)
    o_dc = head
    o_dca = o_dc + len(dc)
    o_pay = o_dca + len(dca)
    o_sym = o_pay + len(pay)
    data = (
        _word(o_dc) + _word(o_dca) + _word(o_pay) + _word(o_sym) + _word(amount)
        + dc + dca + pay + sym
    )
    return "0x" + data.hex()


def encode_contract_call_approved_data(
    source_chain: str, source_address: str, source_tx_hash: str, source_event_index: int,
) -> str:
    """ABI-encode ContractCallApproved data:
    (string sourceChain, string sourceAddress, bytes32 sourceTxHash, uint256 sourceEventIndex)."""
    head = 4 * 32
    sc = _dyn_string(source_chain)
    sa = _dyn_string(source_address)
    o_sc = head
    o_sa = o_sc + len(sc)
    tx32 = _strip0x(source_tx_hash).rjust(32, b"\x00")
    data = _word(o_sc) + _word(o_sa) + tx32 + _word(source_event_index) + sc + sa
    return "0x" + data.hex()


def decode_contract_call_data(data_hex: str) -> dict[str, Any]:
    data = _strip0x(data_hex)
    if len(data) < 96:
        raise ValueError("ContractCall data too short")
    o_dc = int.from_bytes(data[0:32], "big")
    o_dca = int.from_bytes(data[32:64], "big")
    o_pay = int.from_bytes(data[64:96], "big")
    payload = _read_bytes(data, o_pay)
    return {
        "destination_chain": _read_string(data, o_dc),
        "destination_contract_address": _read_string(data, o_dca),
        "payload": "0x" + payload.hex(),
        "payload_hash": "0x" + keccak(payload).hex(),
    }


def decode_contract_call_with_token_data(data_hex: str) -> dict[str, Any]:
    data = _strip0x(data_hex)
    if len(data) < 160:
        raise ValueError("ContractCallWithToken data too short")
    o_dc = int.from_bytes(data[0:32], "big")
    o_dca = int.from_bytes(data[32:64], "big")
    o_pay = int.from_bytes(data[64:96], "big")
    o_sym = int.from_bytes(data[96:128], "big")
    amount = int.from_bytes(data[128:160], "big")
    payload = _read_bytes(data, o_pay)
    return {
        "destination_chain": _read_string(data, o_dc),
        "destination_contract_address": _read_string(data, o_dca),
        "payload": "0x" + payload.hex(),
        "payload_hash": "0x" + keccak(payload).hex(),
        "symbol": _read_string(data, o_sym),
        "amount": str(amount),
    }


def decode_contract_call_approved_data(data_hex: str) -> dict[str, Any]:
    data = _strip0x(data_hex)
    if len(data) < 128:
        raise ValueError("ContractCallApproved data too short")
    o_sc = int.from_bytes(data[0:32], "big")
    o_sa = int.from_bytes(data[32:64], "big")
    source_tx_hash = "0x" + data[64:96].hex()
    source_event_index = int.from_bytes(data[96:128], "big")
    return {
        "source_chain": _read_string(data, o_sc),
        "source_address": _read_string(data, o_sa),
        "source_tx_hash": source_tx_hash,
        "source_event_index": source_event_index,
    }


def gmp_correlation_key(source_chain: str, source_tx_hash: str, source_event_index: int) -> str:
    """Canonical Axelar GMP message id (chain-name lower-cased for stability)."""
    tx = source_tx_hash.lower()
    if not tx.startswith("0x"):
        tx = "0x" + tx
    return f"axl:{source_chain.lower()}/{tx}/{source_event_index}"


class AxelarAdapter(InteropProviderAdapter):
    provider_id = "axelar"
    provider_kind = "axelar"
    display_name = "Axelar (GMP observation adapter)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("gateway-v1",)
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = (
        "message_observation", "historical_backfill", "direct_rpc_observation",
        "payload_decoding", "attestation_observation", "delivery_observation",
        "execution_observation", "asset_transfer",
    )
    known_limitations = (
        "Gateway ContractCall/ContractCallWithToken/ContractCallApproved/"
        "ContractCallExecuted decode, GMP-message-id correlation, commandId "
        "binding, and reorg handling are complete and fixture-proven. Live "
        "scanning requires per-network RPC endpoints; the validator-confirmation "
        "leg additionally requires Axelar network / Axelarscan API access "
        "(both credential-gated)."
    )

    def __init__(
        self,
        rpc_client: Optional[RpcClient] = None,
        confirmation_client: Optional[ConfirmationClient] = None,
        axelar_chains: Optional[dict[str, dict[str, str]]] = None,
        confirmations: int = DEFAULT_CONFIRMATIONS,
        max_block_span: int = DEFAULT_MAX_BLOCK_SPAN,
        endpoint_refs: Optional[dict[str, str]] = None,
        secret_refs: Optional[dict[str, str]] = None,
    ) -> None:
        self.rpc = rpc_client
        self.confirmations_client = confirmation_client
        self.chains = axelar_chains or dict(DEFAULT_AXELAR_CHAINS)
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

        if topic0 in (TOPIC_CONTRACT_CALL, TOPIC_CONTRACT_CALL_WITH_TOKEN):
            with_token = topic0 == TOPIC_CONTRACT_CALL_WITH_TOKEN
            source_chain = raw_log.get("axelar_chain") or self._chain_name(
                raw_log.get("network_id", "")
            )
            if source_chain is None:
                return None
            tx_hash = raw_log.get("transactionHash") or ""
            event_index = _log_index(raw_log)
            key = gmp_correlation_key(source_chain, tx_hash, event_index)
            decoded = (
                decode_contract_call_with_token_data(raw_log["data"]) if with_token
                else decode_contract_call_data(raw_log["data"])
            )
            payload_hash = topics[2] if len(topics) > 2 else decoded["payload_hash"]
            extension: dict[str, Any] = {
                "destination_contract_address": decoded["destination_contract_address"],
                "sender": self._addr(topics[1]) if len(topics) > 1 else "",
            }
            if with_token:
                extension["asset_leg"] = {
                    "symbol": decoded["symbol"], "amount_atomic": decoded["amount"], "leg_type": "send",
                }
            return {
                **base,
                "phase": "sent",
                "correlation_key": key,
                "payload_hash": payload_hash,
                "source_network_id": raw_log.get("network_id", "unknown"),
                "destination_network_id": self._network_for_chain(decoded["destination_chain"]),
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": key, "canonical": True},
                    {"alias_type": "payload_hash", "alias_value": payload_hash, "canonical": False},
                    {"alias_type": "source_tx_hash", "alias_value": (tx_hash or "").lower(), "canonical": False},
                    {"alias_type": "source_event_index", "alias_value": str(event_index), "canonical": False},
                ],
                "provider_native_stage": "ContractCallWithToken" if with_token else "ContractCall",
                "provider_extension": extension,
            }

        if topic0 == TOPIC_CONTRACT_CALL_APPROVED:
            if len(topics) < 4:
                return None
            command_id = self._bytes32(topics[1])
            payload_hash = self._bytes32(topics[3])
            decoded = decode_contract_call_approved_data(raw_log["data"])
            key = gmp_correlation_key(
                decoded["source_chain"], decoded["source_tx_hash"], decoded["source_event_index"],
            )
            return {
                **base,
                "phase": "delivered",
                "correlation_key": key,
                "source_network_id": self._network_for_chain(decoded["source_chain"]),
                "destination_network_id": raw_log.get("network_id", "unknown"),
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": key, "canonical": True},
                    {"alias_type": "command_id", "alias_value": command_id, "canonical": False},
                    {"alias_type": "payload_hash", "alias_value": payload_hash, "canonical": False},
                ],
                "provider_native_stage": "ContractCallApproved",
                "provider_extension": {
                    "command_id": command_id,
                    "destination_contract_address": self._addr(topics[2]),
                    "source_address": decoded["source_address"],
                },
            }

        if topic0 == TOPIC_CONTRACT_CALL_EXECUTED:
            if len(topics) < 2:
                return None
            command_id = self._bytes32(topics[1])
            bindings = raw_log.get("command_bindings") or {}
            bound_key = bindings.get(command_id)
            unbound = bound_key is None
            key = bound_key or f"axl:cmd/{command_id}"
            return {
                **base,
                "phase": "executed",
                "correlation_key": key,
                "destination_network_id": raw_log.get("network_id", "unknown"),
                "provider_message_refs": [
                    {"alias_type": "command_id", "alias_value": command_id, "canonical": unbound},
                    *([{"alias_type": "message_id", "alias_value": key, "canonical": True}]
                      if not unbound else []),
                ],
                "provider_native_stage": "ContractCallExecuted",
                "provider_extension": {"command_id": command_id, "unbound_execution": unbound},
            }

        return None

    def decode_confirmation(
        self, record: dict[str, Any], message_id: str, observed_at: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Decode an Axelar validator-confirmation record into a ``verified``
        observation. Returns None when the record reports it is not confirmed —
        honest: no attestation, no verified stage."""
        if not record or not record.get("confirmed"):
            return None
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "observed_at": observed_at or utc_now_iso(),
            "phase": "verified",
            "correlation_key": message_id,
            "provider_message_refs": [
                {"alias_type": "message_id", "alias_value": message_id, "canonical": True},
            ],
            "provider_native_stage": "ValidatorConfirmed",
            "provider_extension": {
                "poll_id": record.get("poll_id"),
                "confirmation_height": record.get("confirmation_height"),
                "verifier_set_id": record.get("verifier_set_id"),
                "participant_count": len(record.get("participants", [])),
            },
        }

    # ── scanning ─────────────────────────────────────────────────────────────

    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if self.rpc is None:
            raise NotImplementedError(
                "axelar: live scanning requires an RPC client "
                "(credential-gated — configure per-network RPC endpoints)"
            )
        checkpoint = dict(checkpoint or {})
        networks: dict[str, dict] = checkpoint.setdefault("networks", {})
        bindings: dict[str, str] = checkpoint.setdefault("command_bindings", {})
        health: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        pending_confirm: list[dict[str, Any]] = []

        for network_id, meta in self.chains.items():
            state = networks.setdefault(
                network_id, {"last_scanned_block": 0, "recent_hashes": {}},
            )
            if await self._scan_one_network(
                network_id, meta, state, bindings, observations, pending_confirm, health,
            ):
                continue

        if self.confirmations_client is not None:
            for src in pending_confirm:
                await self._maybe_confirm(src, observations, health)
        elif pending_confirm:
            health.append({
                "provider_id": self.provider_id, "state": "attestation_unconfigured",
                "detail": "Axelar confirmation client not wired — verified leg skipped",
                "pending": len(pending_confirm),
            })

        checkpoint["health"] = health
        return observations, checkpoint

    async def _scan_one_network(
        self, network_id, meta, state, bindings, observations, pending_confirm, health,
    ) -> bool:
        head = await self.rpc.get_head(network_id)
        head_number = int(head["number"])
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
            except AxelarRateLimitError as exc:
                health.append({"provider_id": self.provider_id, "network_id": network_id,
                               "state": "rate_limited", "retry_after": exc.retry_after,
                               "resumed_from_block": cursor})
                break
            for raw_log in raw_logs:
                raw_log.setdefault("network_id", network_id)
                raw_log.setdefault("native_chain_id", meta["native_chain_id"])
                raw_log.setdefault("axelar_chain", meta["axelar_chain"])
                raw_log["command_bindings"] = bindings
                decoded = self.decode_log(raw_log)
                if decoded is None:
                    continue
                observations.append(decoded)
                if decoded["phase"] == "sent":
                    pending_confirm.append(decoded)
                elif decoded["phase"] == "delivered":
                    cmd = decoded["provider_extension"].get("command_id")
                    if cmd:
                        bindings[cmd] = decoded["correlation_key"]
            cursor = window_to
            state["last_scanned_block"] = cursor
            recent[str(cursor)] = await self.rpc.get_block_hash(network_id, cursor)
            self._trim(recent)
        state["recent_hashes"] = recent
        return False

    async def _maybe_confirm(self, source_obs, observations, health) -> None:
        message_id = source_obs["correlation_key"]
        try:
            record = await self.confirmations_client.get_confirmation(message_id)
        except AxelarRateLimitError as exc:
            health.append({"provider_id": self.provider_id, "state": "attestation_rate_limited",
                           "retry_after": exc.retry_after})
            return
        verified = self.decode_confirmation(record or {}, message_id)
        if verified:
            observations.append(verified)

    # ── health / security / certification ────────────────────────────────────

    def health(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        context = context or {}
        configured = context.get("configured", self.rpc is not None)
        return {
            "provider_id": self.provider_id,
            "healthy": bool(configured),
            "state": "ok" if configured else "unconfigured",
            "rpc_wired": self.rpc is not None,
            "attestation_wired": self.confirmations_client is not None,
        }

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        return {
            "verification_model": "pos_validator_set_quadratic_bft",
            "required_verifier_ids": [f"axelar-verifier-set:{path_id}"],
            "optional_verifier_ids": [],
            "optional_threshold": None,  # >=2/3 stake-weighted BFT super-majority
            "confirmations_required": self.confirmations,
            "delivery_actor_ids": ["axelar-relayer"],
            "module_addresses": {
                "gateway": self.endpoint_refs.get("gateway", ""),
                "gas_service": self.endpoint_refs.get("gas_service", ""),
            },
        }

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        return AdapterCertificationDescriptor(
            provider=self.provider_id,
            domain="interoperability",
            adapter="AxelarAdapter",
            adapter_version="1.0.0",
            supported_operations=[
                "observe_source_message", "observe_validator_confirmation",
                "observe_approval", "observe_execution", "reorg_detection",
                "checkpoint_persistence", "security_policy_snapshot",
            ],
            unsupported_operations=[
                "relay", "command_approval_submission", "execution", "recovery",
            ],
            required_credentials=["axelarscan_api_token"],
            required_endpoints=["evm_rpc_url", "axelar_lcd_url"],
            secret_ref_names=sorted(self.secret_refs.keys()) or ["axelar_api_key_ref"],
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
            "endpoint": self.endpoint_refs.get("axelar_lcd_url", "axelar_lcd_url_ref"),
            "headers": {"authorization": credential.get("api_key", "")},
            "params": {"tenant_id": ctx.get("tenant_id", "")},
        }

    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _sanitize(payload)

    def dedupe_key(self, event: dict[str, Any]) -> str:
        return str(event.get("messageId") or event.get("correlation_key") or event.get("id"))

    def sequence_of(self, event: dict[str, Any]) -> int:
        return int(event.get("seq") or event.get("blockNumber") or event.get("source_event_index") or 0)

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
                "gateway_id": f"axelar:gateway:{network_id}",
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

    def _chain_name(self, network_id: str) -> Optional[str]:
        meta = self.chains.get(network_id)
        return meta["axelar_chain"] if meta else None

    def _network_for_chain(self, axelar_chain: str) -> str:
        target = axelar_chain.lower()
        for network_id, meta in self.chains.items():
            if meta["axelar_chain"].lower() == target:
                return network_id
        return f"axelar-chain:{axelar_chain}"

    @staticmethod
    def _bytes32(topic: str) -> str:
        raw = topic[2:] if topic.startswith("0x") else topic
        return "0x" + raw.rjust(64, "0").lower()

    @staticmethod
    def _addr(topic: str) -> str:
        raw = topic[2:] if topic.startswith("0x") else topic
        return "0x" + raw.rjust(64, "0")[-40:].lower()

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
