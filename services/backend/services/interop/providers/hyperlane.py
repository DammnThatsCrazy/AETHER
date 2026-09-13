"""Hyperlane adapter — Mailbox Dispatch/Process observation (fixture-proven decode).

Implementation status: CREDENTIAL_GATED. The decode/correlation/reorg logic is
complete and proven against fixtures; LIVE scanning requires configured per-chain
RPC endpoints, which this environment does not hold. The RPC client is injected
so tests (and future live wiring) share one code path — identical seam to the
LayerZero V2 reference adapter.

Observation-only. Aether never relays, processes, signs, or recovers Hyperlane
messages (``execution_by_aether=False``).

SECURITY / FINALITY SEMANTICS (do not flatten against other providers)
----------------------------------------------------------------------
Hyperlane is a *modular message-passing* protocol. Security is delegated to a
recipient-chosen **Interchain Security Module (ISM)** — e.g. a multisig of
validators attesting a Merkle root, an aggregation ISM, an Optimistic ISM, or a
routing ISM. Crucially there is **no independent on-chain "verified" event**:
proof verification happens *inside* ``Mailbox.process()`` when the destination
ISM validates the metadata, then the message is delivered atomically. The two
observable on-chain phases are therefore:

    Dispatch (origin Mailbox)  -> source_confirmed
    Process  (dest   Mailbox)  -> delivered   (ISM verification is intrinsic)

This differs materially from:
  * LayerZero V2, which emits a distinct ``PacketVerified`` DVN attestation event.
  * IBC, whose verification is an on-chain *light-client* proof (counterparty
    consensus), not a validator/oracle attestation.
  * deBridge, whose attestation is an *off-chain validator-set* signature.

Message id (canonical correlation key): ``keccak256(message)`` — identical to the
value emitted in ``DispatchId``/``ProcessId``. We compute it from the dispatched
message body so the source leg is self-correlating, and read it directly from the
``*Id`` events for the destination leg.

Mapping (provider-native -> canonical):
    Mailbox         -> InteropGateway
    message id       -> correlation key alias ("hyp:<id>") + provider ref
    Dispatch/DispatchId -> phase "sent"       (origin mailbox ref, side=source)
    Process/ProcessId   -> phase "delivered"  (dest mailbox ref,   side=destination)
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from eth_utils import keccak

from services.integrations.connectors.base import ImplementationStatus
from services.interop.foundation import utc_now_iso
from services.interop.providers.base import InteropProviderAdapter

# ── event signatures (Hyperlane V3 Mailbox) ─────────────────────────────────
SIG_DISPATCH = "Dispatch(address,uint32,bytes32,bytes)"
SIG_DISPATCH_ID = "DispatchId(bytes32)"
SIG_PROCESS = "Process(uint32,bytes32,address)"
SIG_PROCESS_ID = "ProcessId(bytes32)"

TOPIC_DISPATCH = "0x" + keccak(text=SIG_DISPATCH).hex()
TOPIC_DISPATCH_ID = "0x" + keccak(text=SIG_DISPATCH_ID).hex()
TOPIC_PROCESS = "0x" + keccak(text=SIG_PROCESS).hex()
TOPIC_PROCESS_ID = "0x" + keccak(text=SIG_PROCESS_ID).hex()

# Hyperlane domain id -> network metadata. For EVM chains Hyperlane domain ids
# equal the native chain id; extended via configuration.
DEFAULT_DOMAIN_NETWORKS: dict[int, dict[str, str]] = {
    1: {"network_id": "ethereum-mainnet", "native_chain_id": "1"},
    42161: {"network_id": "arbitrum-mainnet", "native_chain_id": "42161"},
    10: {"network_id": "optimism-mainnet", "native_chain_id": "10"},
    8453: {"network_id": "base-mainnet", "native_chain_id": "8453"},
    137: {"network_id": "polygon-mainnet", "native_chain_id": "137"},
}

DEFAULT_CONFIRMATIONS = 20
DEFAULT_MAX_BLOCK_SPAN = 2000
_RECENT_HASHES_KEPT = 32

# Hyperlane message header byte layout (formatted message).
_H_VERSION = 0
_H_NONCE = slice(1, 5)          # uint32
_H_ORIGIN = slice(5, 9)         # uint32
_H_SENDER = slice(9, 41)        # bytes32
_H_DEST = slice(41, 45)         # uint32
_H_RECIPIENT = slice(45, 77)    # bytes32
_H_BODY = 77
_HEADER_MIN = 77


class RateLimited(Exception):
    """Raised by the injected RPC client when the provider rate-limits us.

    ``scan`` catches this, keeps the checkpoint at the last fully-scanned block
    window, and returns partial progress so the next poll resumes cleanly.
    """


class RpcClient(Protocol):
    """Injected JSON-RPC access — a mock in tests, HTTP in prod."""

    async def get_head(self, network_id: str) -> dict[str, Any]: ...
    async def get_logs(
        self, network_id: str, from_block: int, to_block: int,
    ) -> list[dict[str, Any]]: ...
    async def get_block_hash(self, network_id: str, block_number: int) -> str: ...


def _strip0x(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def encode_hyperlane_message(
    nonce: int, origin: int, sender32: bytes, destination: int, recipient32: bytes,
    body: bytes, version: int = 3,
) -> bytes:
    """Build a formatted Hyperlane message (used by fixtures so the decoder and
    fixtures can never drift). id = keccak256(message)."""
    if len(sender32) != 32 or len(recipient32) != 32:
        raise ValueError("sender and recipient must be 32-byte values")
    return (
        version.to_bytes(1, "big")
        + nonce.to_bytes(4, "big")
        + origin.to_bytes(4, "big")
        + sender32
        + destination.to_bytes(4, "big")
        + recipient32
        + body
    )


def hyperlane_message_id(message: bytes) -> str:
    return "0x" + keccak(message).hex()


def decode_hyperlane_message(message: bytes) -> dict[str, Any]:
    """Decode a formatted Hyperlane message header. Raises ValueError if short."""
    if len(message) < _HEADER_MIN:
        raise ValueError(f"hyperlane message too short: {len(message)} bytes")
    body = message[_H_BODY:]
    return {
        "version": message[_H_VERSION],
        "nonce": int.from_bytes(message[_H_NONCE], "big"),
        "origin": int.from_bytes(message[_H_ORIGIN], "big"),
        "sender": "0x" + message[_H_SENDER].hex(),
        "destination": int.from_bytes(message[_H_DEST], "big"),
        "recipient": "0x" + message[_H_RECIPIENT].hex(),
        "message_id": hyperlane_message_id(message),
        "body_hash": "0x" + keccak(body).hex(),
        "body_length": len(body),
    }


def encode_dispatch_data(message: bytes) -> str:
    """ABI-encode Dispatch event data: a single dynamic ``bytes message``."""
    padded = (len(message) + 31) // 32 * 32
    data = (32).to_bytes(32, "big") + len(message).to_bytes(32, "big") + message.ljust(padded, b"\x00")
    return "0x" + data.hex()


def decode_dispatch_data(data_hex: str) -> bytes:
    """Decode the single dynamic ``bytes message`` from Dispatch data."""
    data = _strip0x(data_hex)
    if len(data) < 64:
        raise ValueError("Dispatch data too short")
    offset = int.from_bytes(data[0:32], "big")
    length = int.from_bytes(data[offset:offset + 32], "big")
    return data[offset + 32: offset + 32 + length]


class HyperlaneAdapter(InteropProviderAdapter):
    provider_id = "hyperlane"
    provider_kind = "hyperlane"
    display_name = "Hyperlane (Mailbox observation adapter)"
    protocol_products = ("messaging",)
    supported_versions = ("v3",)
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    adapter_version = "0.1.0"
    capabilities = (
        "message_observation", "delivery_observation", "historical_backfill",
        "direct_rpc_observation", "payload_decoding", "reorg_recovery",
    )
    known_limitations = (
        "Dispatch/Process decode, message-id correlation, out-of-order join, and "
        "reorg/rewind handling are complete and fixture-proven. Live scanning "
        "requires per-chain RPC endpoints (credential-gated). Hyperlane has no "
        "independent on-chain verification event: ISM proof verification is "
        "intrinsic to Mailbox.process(), so the observable phases are "
        "source(Dispatch) -> delivered(Process). Live ISM module addresses / "
        "validator sets for security-policy snapshots additionally require "
        "eth_call access to the recipient's configured ISM."
    )
    # Certification surface (offline, honest).
    cert_required_credentials = ("per_chain_rpc_url",)
    cert_required_endpoints = ("evm_json_rpc",)
    cert_secret_ref_names = ("hyperlane_rpc_url",)

    def __init__(
        self,
        rpc_client: Optional[RpcClient] = None,
        domain_networks: Optional[dict[int, dict[str, str]]] = None,
        confirmations: int = DEFAULT_CONFIRMATIONS,
        max_block_span: int = DEFAULT_MAX_BLOCK_SPAN,
    ) -> None:
        self.rpc = rpc_client
        self.domain_networks = domain_networks or dict(DEFAULT_DOMAIN_NETWORKS)
        self.confirmations = confirmations
        self.max_block_span = max_block_span

    # ── decoding ────────────────────────────────────────────────────────────

    def _network(self, domain: int) -> str:
        return self.domain_networks.get(domain, {}).get("network_id", f"hyp-domain:{domain}")

    def _endpoint_ref(self, raw_log: dict[str, Any]) -> dict[str, Any]:
        network_id = raw_log.get("network_id", "unknown")
        return {
            "network_id": network_id,
            "native_chain_id": raw_log.get("native_chain_id", ""),
            "transaction_hash": raw_log.get("transactionHash"),
            "block_number": _as_block_number(raw_log.get("blockNumber", 0)),
            "block_hash": raw_log.get("blockHash"),
            "log_index": _as_int(raw_log.get("logIndex", 0)),
            "gateway_id": f"hyperlane:mailbox:{network_id}",
        }

    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        topics = raw_log.get("topics") or []
        if not topics:
            return None
        topic0 = topics[0].lower()
        base = {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "observed_at": raw_log.get("observed_at") or utc_now_iso(),
            "endpoint_ref": self._endpoint_ref(raw_log),
        }

        if topic0 == TOPIC_DISPATCH:
            message = decode_dispatch_data(raw_log["data"])
            decoded = decode_hyperlane_message(message)
            message_id = decoded["message_id"]
            return {
                **base,
                "phase": "sent",
                "correlation_key": f"hyp:{message_id}",
                "sequence": str(decoded["nonce"]),
                "payload_hash": decoded["body_hash"],
                "source_network_id": self._network(decoded["origin"]),
                "destination_network_id": self._network(decoded["destination"]),
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": message_id, "canonical": True},
                    {"alias_type": "nonce", "alias_value": str(decoded["nonce"]), "canonical": False},
                    {"alias_type": "origin_domain", "alias_value": str(decoded["origin"]), "canonical": False},
                    {"alias_type": "destination_domain", "alias_value": str(decoded["destination"]), "canonical": False},
                ],
                "provider_native_stage": "Dispatch",
                "provider_extension": {
                    "sender": decoded["sender"],
                    "recipient": decoded["recipient"],
                    "version": decoded["version"],
                    "body_length": decoded["body_length"],
                },
            }

        if topic0 == TOPIC_DISPATCH_ID:
            message_id = _topic_bytes32(topics, 1)
            if message_id is None:
                return None
            return {
                **base,
                "phase": "sent",
                "correlation_key": f"hyp:{message_id}",
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": message_id, "canonical": True},
                ],
                "provider_native_stage": "DispatchId",
            }

        if topic0 == TOPIC_PROCESS_ID:
            message_id = _topic_bytes32(topics, 1)
            if message_id is None:
                return None
            return {
                **base,
                "phase": "delivered",
                "correlation_key": f"hyp:{message_id}",
                # The destination chain we observed on IS the delivery target.
                "destination_network_id": base["endpoint_ref"]["network_id"],
                "provider_message_refs": [
                    {"alias_type": "message_id", "alias_value": message_id, "canonical": True},
                ],
                "provider_native_stage": "ProcessId",
            }

        # Process carries (origin, sender, recipient) as indexed topics but NO
        # message id, so it cannot self-correlate. scan() joins it into the
        # paired ProcessId observation for richer metadata; alone it is None.
        return None

    def _decode_process(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        topics = raw_log.get("topics") or []
        if not topics or topics[0].lower() != TOPIC_PROCESS:
            return None
        origin = _topic_uint(topics, 1)
        return {
            "origin_domain": origin,
            "source_network_id": self._network(origin) if origin is not None else None,
            "sender": _topic_bytes32(topics, 2),
            "recipient": _topic_address(topics, 3),
        }

    # ── scanning ────────────────────────────────────────────────────────────

    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Scan every configured chain from the checkpoint to head minus the
        confirmation horizon, paginating in ``max_block_span`` windows.

        Resilience:
          * reorg: the recorded hash of the last scanned block must still match;
            a mismatch yields a "reorged" observation and rewinds to the fork.
          * cursor drift / chain discontinuity: a stored cursor beyond the
            current head (node rollback / wrong endpoint) triggers a safe rewind.
          * rate limits: a RateLimited from the client stops the network's scan
            at the last completed window; the checkpoint resumes it next poll.
        """
        if self.rpc is None:
            raise NotImplementedError(
                "hyperlane: live scanning requires an RPC client "
                "(credential-gated — configure per-chain RPC endpoints)"
            )
        checkpoint = dict(checkpoint or {})
        networks: dict[str, dict] = checkpoint.setdefault("networks", {})
        observations: list[dict[str, Any]] = []

        for domain, meta in self.domain_networks.items():
            network_id = meta["network_id"]
            state = networks.setdefault(
                network_id, {"last_scanned_block": 0, "recent_hashes": {}},
            )
            head = await self.rpc.get_head(network_id)
            head_number = int(head["number"])
            safe_head = head_number - self.confirmations
            last = int(state["last_scanned_block"])

            # Cursor drift: stored cursor is ahead of the chain head (rollback or
            # a different endpoint) — rewind to the safe head and re-observe.
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
                    observations.extend(self._decode_batch(raw_logs, meta))
                    state["last_scanned_block"] = window_end
                    block_hash = await self.rpc.get_block_hash(network_id, window_end)
                    recent[str(window_end)] = block_hash
                    _prune_recent(recent)
                    window_start = window_end + 1
            except RateLimited:
                # Keep progress up to the last completed window; resume next poll.
                pass
            state["recent_hashes"] = recent

        return observations, checkpoint

    def _decode_batch(
        self, raw_logs: list[dict[str, Any]], meta: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Decode a window of logs, joining paired events within a transaction:
        Dispatch supersedes the redundant DispatchId; Process enriches ProcessId
        with the origin domain it alone carries."""
        for raw_log in raw_logs:
            raw_log.setdefault("network_id", meta["network_id"])
            raw_log.setdefault("native_chain_id", meta["native_chain_id"])

        # Per-transaction join context.
        process_by_tx: dict[str, dict[str, Any]] = {}
        dispatch_ids_by_tx: dict[str, set] = {}
        for raw_log in raw_logs:
            topic0 = (raw_log.get("topics") or ["0x"])[0].lower()
            tx = raw_log.get("transactionHash", "")
            if topic0 == TOPIC_PROCESS:
                proc = self._decode_process(raw_log)
                if proc:
                    process_by_tx[tx] = proc
            elif topic0 == TOPIC_DISPATCH:
                message = decode_dispatch_data(raw_log["data"])
                dispatch_ids_by_tx.setdefault(tx, set()).add(
                    hyperlane_message_id(message)
                )

        out: list[dict[str, Any]] = []
        for raw_log in raw_logs:
            topic0 = (raw_log.get("topics") or ["0x"])[0].lower()
            tx = raw_log.get("transactionHash", "")
            decoded = self.decode_log(raw_log)
            if decoded is None:
                continue
            if decoded["provider_native_stage"] == "DispatchId":
                # Redundant with the same-tx Dispatch (same id) — drop it.
                mid = decoded["correlation_key"].split(":", 1)[1]
                if mid in dispatch_ids_by_tx.get(tx, set()):
                    continue
            if decoded["provider_native_stage"] == "ProcessId":
                proc = process_by_tx.get(tx)
                if proc:
                    if proc.get("source_network_id"):
                        decoded["source_network_id"] = proc["source_network_id"]
                    decoded.setdefault("provider_extension", {})
                    decoded["provider_extension"].update({
                        "process_sender": proc.get("sender"),
                        "process_recipient": proc.get("recipient"),
                        "origin_domain": proc.get("origin_domain"),
                    })
            out.append(decoded)
        return out

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
        """Offline, structural description of Hyperlane's security posture.

        Intentionally NOT equivalent to light-client (IBC) or external-validator
        (deBridge) models — Hyperlane's trust is a recipient-configured ISM and
        verification is intrinsic to delivery (no standalone attestation event).
        """
        return {
            "verification_model": "modular_ism",
            "attestation_kind": "recipient_configured_ism",
            "verification_is_intrinsic_to_delivery": True,
            "has_independent_verification_event": False,
            "delivery_actor": "permissionless_relayer",
            "trust_source": "recipient_selected_module",
            "notes": (
                "ISM may be multisig (validator-attested Merkle root), "
                "aggregation, routing, or optimistic; the recipient chooses it."
            ),
        }

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        raise NotImplementedError(
            "hyperlane: live security-policy snapshots need eth_call access to "
            "the recipient's configured ISM (credential-gated). The structural "
            "model is available offline via security_model()."
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
                "message_observation", "delivery_observation",
                "historical_backfill", "reorg_recovery",
            ],
            unsupported_operations=["relay", "process", "signing", "recovery"],
            required_credentials=list(self.cert_required_credentials),
            required_endpoints=list(self.cert_required_endpoints),
            secret_ref_names=list(self.cert_secret_ref_names),
            pagination_model="page",
            streaming_model="none",
            rate_limit_behavior=(
                "provider 429 -> RateLimited; scan checkpoints the last completed "
                "block window and resumes next poll (no data loss)"
            ),
            retry_policy="poll-loop resume from persisted per-chain block cursor",
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=False,
        )


# ── small EVM helpers (topic/hex parsing) ───────────────────────────────────

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


def _topic_address(topics: list, index: int) -> Optional[str]:
    if len(topics) <= index:
        return None
    raw = _strip0x(topics[index])
    return "0x" + raw[-20:].hex()
