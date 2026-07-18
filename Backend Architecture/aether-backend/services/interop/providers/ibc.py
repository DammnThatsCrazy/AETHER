"""IBC adapter — Tendermint/CometBFT packet-lifecycle observation (fixture-proven).

Implementation status: CREDENTIAL_GATED. Decode/correlation/continuity logic is
complete and proven against fixtures; LIVE scanning requires configured Cosmos
(CometBFT) RPC endpoints per chain, which this environment does not hold. The RPC
client is injected so tests and future live wiring share one code path — the same
injectable seam the LayerZero V2 reference adapter uses.

Observation-only. Aether never relays, submits ``MsgRecvPacket``/``MsgAcknowledgement``,
signs, or recovers IBC packets (``execution_by_aether=False``).

WHY THIS ADAPTER IS NOT AN EVM LOG SCANNER
------------------------------------------
IBC is a Cosmos/CometBFT protocol. There are NO EVM logs and NO topic hashes.
Events are **attribute-based**: each transaction result (and begin/end-block)
carries typed events (``send_packet``, ``recv_packet``, ``write_acknowledgement``,
``acknowledge_packet``, ``timeout_packet``) whose payload is a list of
key/value attribute pairs (``packet_sequence``, ``packet_src_channel`` …). We
observe them through the Tendermint RPC model: walk ``block_results`` per height
(``/block_results``) — the deterministic, order-stable analogue of an EVM
``get_logs`` range — or, live, ``/tx_search`` by attribute query. Attribute
values may be base64-encoded (older CometBFT) or plain strings (0.37+); the
decoder tolerates both.

SECURITY / FINALITY SEMANTICS (do not flatten against other providers)
----------------------------------------------------------------------
IBC's trust model is a **light client**, not an external attestation. Each chain
runs an on-chain ICS-07 Tendermint light client of its counterparty. A
``MsgRecvPacket`` (and ``MsgAcknowledgement``) carries a Merkle proof that is
verified **on-chain** against the stored counterparty consensus state — so packet
verification is *intrinsic* to receipt/acknowledgement, gated by counterparty
consensus (2/3+ validator set), with NO separate attestation event and NO
external oracle/validator-of-the-bridge. This is fundamentally different from:
  * Hyperlane — recipient-configured ISM (may be a validator multisig).
  * LayerZero V2 — off/at-chain DVN attestation emitted as ``PacketVerified``.
  * deBridge — off-chain deBridge validator-set signatures.
CometBFT provides **instant finality** (a committed block does not reorg under
BFT), so EVM-style reorgs are near-impossible; the adapter still verifies
block-hash continuity to catch node inconsistency / chain rollback (upgrade
halts) and rewinds safely.

Packet identity (canonical correlation key): the ICS-04 tuple
``(src_port, src_channel, dst_port, dst_channel, sequence)`` — shared verbatim by
every stage on both chains, which is what lets out-of-order legs correlate.

Mapping (provider-native -> canonical):
    channel/port                 -> InteropGateway (per chain endpoint)
    packet tuple                 -> correlation key ("ibc:<sp>/<sc>/<dp>/<dc>/<seq>")
    send_packet          (source)      -> phase "sent"      (side=source)
    recv_packet          (destination) -> phase "delivered" (side=destination)
    write_acknowledgement(destination) -> phase "executed"  (side=destination)
    acknowledge_packet   (source)      -> phase "settled"   (round-trip complete)
    timeout_packet       (source)      -> phase "failed"
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any, Optional, Protocol

from services.integrations.connectors.base import ImplementationStatus
from services.interop.foundation import utc_now_iso
from services.interop.providers.base import InteropProviderAdapter

# CometBFT/IBC event types.
EVT_SEND_PACKET = "send_packet"
EVT_RECV_PACKET = "recv_packet"
EVT_WRITE_ACK = "write_acknowledgement"
EVT_ACK_PACKET = "acknowledge_packet"
EVT_TIMEOUT_PACKET = "timeout_packet"

# event type -> canonical phase
_EVENT_PHASE: dict[str, str] = {
    EVT_SEND_PACKET: "sent",
    EVT_RECV_PACKET: "delivered",
    EVT_WRITE_ACK: "executed",
    EVT_ACK_PACKET: "settled",
    EVT_TIMEOUT_PACKET: "failed",
}

# CometBFT is instant-final; a shallow depth only guards node lag / mempool race.
DEFAULT_FINALITY_DEPTH = 1
DEFAULT_MAX_HEIGHTS_PER_SCAN = 500
_RECENT_HASHES_KEPT = 64


class RateLimited(Exception):
    """Raised by the injected RPC client on RPC throttling; scan resumes."""


class IbcRpcClient(Protocol):
    """Injected Tendermint/CometBFT RPC access — a mock in tests, HTTP in prod.

    Deliberately NOT an EVM ``get_logs`` shape: IBC is observed by walking
    ``block_results`` per height (or ``tx_search`` by attribute query, live).
    """

    async def get_status(self, chain_id: str) -> dict[str, Any]: ...
    async def get_block_results(self, chain_id: str, height: int) -> dict[str, Any]: ...
    async def get_block_hash(self, chain_id: str, height: int) -> str: ...


def _decode_attr_value(value: Any, base64_encoded: bool) -> str:
    if value is None:
        return ""
    if not base64_encoded:
        return str(value)
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return str(value)


def parse_attributes(event: dict[str, Any]) -> dict[str, str]:
    """Flatten a CometBFT event's attribute list to a dict, tolerating base64
    (older CometBFT) and plain (0.37+) attribute encodings."""
    base64_encoded = str(event.get("attributes_encoding", "plain")).lower() == "base64"
    attributes: dict[str, str] = {}
    for attribute in event.get("attributes", []) or []:
        key = _decode_attr_value(attribute.get("key"), base64_encoded)
        attributes[key] = _decode_attr_value(attribute.get("value"), base64_encoded)
    return attributes


class IbcAdapter(InteropProviderAdapter):
    provider_id = "ibc"
    provider_kind = "ibc"
    display_name = "IBC (CometBFT packet-lifecycle observation adapter)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("ics20-1", "ibc-v1")
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    adapter_version = "0.1.0"
    capabilities = (
        "message_observation", "asset_transfer", "delivery_observation",
        "settlement_observation", "historical_backfill",
        "attribute_event_observation", "continuity_recovery",
    )
    known_limitations = (
        "send_packet/recv_packet/write_acknowledgement/acknowledge_packet/"
        "timeout_packet decode over CometBFT block_results, packet-tuple "
        "correlation, out-of-order join, and continuity/rewind are complete and "
        "fixture-proven. Live scanning requires per-chain CometBFT RPC endpoints "
        "(credential-gated). IBC verification is an on-chain light-client (ICS-07) "
        "proof intrinsic to recv/ack — there is no separate attestation event and "
        "no external validator-of-the-bridge; do not equate it with message-"
        "passing bridges. Live client/connection trust snapshots need abci_query "
        "access to the on-chain light client (credential-gated)."
    )
    cert_required_credentials = ("chain_rpc_url",)
    cert_required_endpoints = ("cometbft_rpc",)
    cert_secret_ref_names = ("ibc_rpc_url",)

    def __init__(
        self,
        rpc_client: Optional[IbcRpcClient] = None,
        chains: Optional[dict[str, dict[str, str]]] = None,
        channel_networks: Optional[dict[str, str]] = None,
        finality_depth: int = DEFAULT_FINALITY_DEPTH,
        max_heights_per_scan: int = DEFAULT_MAX_HEIGHTS_PER_SCAN,
    ) -> None:
        self.rpc = rpc_client
        # chains to observe: {chain_id: {"network_id": ...}}
        self.chains = chains or {}
        # channel id -> network it resides on (for source/destination mapping).
        self.channel_networks = channel_networks or {}
        self.finality_depth = finality_depth
        self.max_heights_per_scan = max_heights_per_scan

    # ── decoding ────────────────────────────────────────────────────────────

    def _channel_network(self, channel: str, fallback: str) -> str:
        return self.channel_networks.get(channel, f"ibc-channel:{channel}" if channel else fallback)

    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Decode ONE CometBFT event (not an EVM log). ``raw_log`` is a normalized
        event dict: {type, attributes:[{key,value}], attributes_encoding?,
        network_id, chain_id, tx_hash, height, block_hash, event_index}."""
        event_type = raw_log.get("type", "")
        phase = _EVENT_PHASE.get(event_type)
        if phase is None:
            return None

        attrs = parse_attributes(raw_log)
        src_port = attrs.get("packet_src_port", "")
        src_channel = attrs.get("packet_src_channel", "")
        dst_port = attrs.get("packet_dst_port", "")
        dst_channel = attrs.get("packet_dst_channel", "")
        sequence = attrs.get("packet_sequence", "")
        if not (src_channel and dst_channel and sequence):
            return None

        correlation_key = f"ibc:{src_port}/{src_channel}/{dst_port}/{dst_channel}/{sequence}"
        observing_network = raw_log.get("network_id", "unknown")
        source_network = self._channel_network(src_channel, observing_network)
        destination_network = self._channel_network(dst_channel, observing_network)

        endpoint_ref = {
            "network_id": observing_network,
            "chain_id": raw_log.get("chain_id"),
            "transaction_hash": raw_log.get("tx_hash"),
            # block_number carries the CometBFT height so the reorg/continuity
            # matcher in the correlation engine works uniformly across families.
            "block_number": str(raw_log.get("height", 0)),
            "block_hash": raw_log.get("block_hash"),
            "log_index": _as_int(raw_log.get("event_index", 0)),
            "gateway_id": f"ibc:channel:{observing_network}:{_stage_channel(event_type, src_channel, dst_channel)}",
        }

        observation: dict[str, Any] = {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "observed_at": raw_log.get("observed_at") or utc_now_iso(),
            "phase": phase,
            "protocol_product": "messaging",
            "correlation_key": correlation_key,
            "sequence": sequence,
            "source_network_id": source_network,
            "destination_network_id": destination_network,
            "endpoint_ref": endpoint_ref,
            "provider_message_refs": [
                {"alias_type": "packet_tuple", "alias_value": correlation_key[4:], "canonical": True},
                {"alias_type": "sequence", "alias_value": sequence, "canonical": False},
                {"alias_type": "src_channel", "alias_value": src_channel, "canonical": False},
                {"alias_type": "dst_channel", "alias_value": dst_channel, "canonical": False},
            ],
            "provider_native_stage": event_type,
            "provider_extension": {
                "src_port": src_port,
                "dst_port": dst_port,
                "connection": attrs.get("packet_connection") or attrs.get("connection_id"),
                "ordering": attrs.get("packet_channel_ordering"),
                "timeout_height": attrs.get("packet_timeout_height"),
                "timeout_timestamp": attrs.get("packet_timeout_timestamp"),
            },
        }

        data_hex = attrs.get("packet_data_hex")
        if data_hex:
            try:
                observation["payload_hash"] = "sha256:" + hashlib.sha256(
                    bytes.fromhex(data_hex)
                ).hexdigest()
            except ValueError:
                pass
        elif attrs.get("packet_data"):
            observation["payload_hash"] = "sha256:" + hashlib.sha256(
                attrs["packet_data"].encode("utf-8")
            ).hexdigest()

        if event_type == EVT_WRITE_ACK and attrs.get("packet_ack_hex"):
            observation["provider_extension"]["ack_present"] = True
        return observation

    # ── scanning ────────────────────────────────────────────────────────────

    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Walk CometBFT block_results per height from the checkpoint to the
        finalized head, in bounded height windows (pagination).

        Resilience:
          * continuity: the recorded hash of the last scanned height must still
            match; a mismatch (rollback / node inconsistency) yields a "reorged"
            observation and rewinds to the discontinuity — rare under BFT
            instant finality, but handled safely.
          * cursor drift: a stored height beyond the chain head triggers a rewind.
          * rate limits: a RateLimited from the client stops the chain's scan at
            the last fully-scanned height; the checkpoint resumes it next poll.
        """
        if self.rpc is None:
            raise NotImplementedError(
                "ibc: live scanning requires a CometBFT RPC client "
                "(credential-gated — configure per-chain Tendermint RPC endpoints)"
            )
        checkpoint = dict(checkpoint or {})
        networks: dict[str, dict] = checkpoint.setdefault("networks", {})
        observations: list[dict[str, Any]] = []

        for chain_id, meta in self.chains.items():
            network_id = meta["network_id"]
            state = networks.setdefault(
                network_id, {"last_scanned_height": 0, "recent_hashes": {}},
            )
            status = await self.rpc.get_status(chain_id)
            latest_height = int(status["latest_block_height"])
            safe_head = latest_height - self.finality_depth
            last = int(state["last_scanned_height"])

            if last > latest_height:
                observations.append(self._reorg_observation(network_id, max(0, safe_head)))
                state["last_scanned_height"] = max(0, safe_head - 1)
                state["recent_hashes"] = {}
                continue

            recent = state.get("recent_hashes", {})
            if last and str(last) in recent:
                current_hash = await self.rpc.get_block_hash(chain_id, last)
                if current_hash != recent[str(last)]:
                    fork_point = min(
                        (int(height) for height, block_hash in recent.items()
                         if block_hash != current_hash),
                        default=last,
                    )
                    observations.append(self._reorg_observation(network_id, fork_point))
                    state["last_scanned_height"] = max(0, fork_point - 1)
                    state["recent_hashes"] = {}
                    continue

            if safe_head <= last:
                continue

            ceiling = min(safe_head, last + self.max_heights_per_scan)
            height = last + 1
            try:
                while height <= ceiling:
                    block = await self.rpc.get_block_results(chain_id, height)
                    observations.extend(self._decode_block(block, network_id, chain_id, height))
                    state["last_scanned_height"] = height
                    recent[str(height)] = block.get("block_hash", "")
                    _prune_recent(recent)
                    height += 1
            except RateLimited:
                pass
            state["recent_hashes"] = recent

        return observations, checkpoint

    def _decode_block(
        self, block: dict[str, Any], network_id: str, chain_id: str, height: int,
    ) -> list[dict[str, Any]]:
        block_hash = block.get("block_hash", "")
        observations: list[dict[str, Any]] = []
        event_index = 0

        def emit(events: list, tx_hash: Optional[str]) -> None:
            nonlocal event_index
            for event in events or []:
                raw = {
                    **event,
                    "network_id": network_id,
                    "chain_id": chain_id,
                    "tx_hash": tx_hash,
                    "height": height,
                    "block_hash": block_hash,
                    "event_index": event_index,
                }
                event_index += 1
                decoded = self.decode_log(raw)
                if decoded:
                    observations.append(decoded)

        for tx in block.get("txs_results", []) or []:
            emit(tx.get("events", []), tx.get("hash"))
        emit(block.get("begin_block_events", []), None)
        emit(block.get("end_block_events", []), None)
        return observations

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
                    "last_scanned_height": int(state.get("last_scanned_height", 0)),
                    "tracked_hashes": len(state.get("recent_hashes", {})),
                }
                for network_id, state in networks.items()
            },
            "observed_at": utc_now_iso(),
        }

    def security_model(self) -> dict[str, Any]:
        """On-chain light-client (ICS-07) verification — NOT an external
        attestation. Trust is the counterparty's own consensus (2/3+ validators),
        verified by an on-chain Merkle proof intrinsic to recv/ack."""
        return {
            "verification_model": "light_client",
            "light_client_spec": "ics-07-tendermint",
            "attestation_kind": "on_chain_merkle_proof",
            "attestation_on_chain": True,
            "external_validator_set": False,
            "has_independent_verification_event": False,
            "trust_source": "counterparty_consensus",
            "delivery_actor": "permissionless_relayer",
            "notes": (
                "Verification is intrinsic to MsgRecvPacket/MsgAcknowledgement; "
                "proofs are checked against the on-chain light client's consensus "
                "state. Not equivalent to a bridge validator/oracle set."
            ),
        }

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        raise NotImplementedError(
            "ibc: live light-client / connection trust snapshots need abci_query "
            "access to the on-chain ICS-07 client (credential-gated). The "
            "structural model is available offline via security_model()."
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
                "message_observation", "asset_transfer",
                "delivery_observation", "settlement_observation",
                "historical_backfill", "continuity_recovery",
            ],
            unsupported_operations=["relay", "recv", "acknowledge", "signing", "recovery"],
            required_credentials=list(self.cert_required_credentials),
            required_endpoints=list(self.cert_required_endpoints),
            secret_ref_names=list(self.cert_secret_ref_names),
            pagination_model="page",
            streaming_model="none",
            rate_limit_behavior=(
                "RPC 429 -> RateLimited; scan checkpoints the last fully-scanned "
                "height and resumes next poll"
            ),
            retry_policy="poll-loop resume from persisted per-chain height cursor",
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=False,
        )


# ── helpers ──────────────────────────────────────────────────────────────────

def _as_int(value: Any) -> int:
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value or 0)
    return int(value or 0)


def _prune_recent(recent: dict[str, str]) -> None:
    if len(recent) > _RECENT_HASHES_KEPT:
        for stale_key in sorted(recent, key=int)[:-_RECENT_HASHES_KEPT]:
            recent.pop(stale_key, None)


def _stage_channel(event_type: str, src_channel: str, dst_channel: str) -> str:
    """The channel that lives on the chain emitting this event."""
    if event_type in (EVT_RECV_PACKET, EVT_WRITE_ACK):
        return dst_channel
    return src_channel
