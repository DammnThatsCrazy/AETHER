"""Wormhole observation adapter — real Core-Bridge / VAA / Token-Bridge decode.

Implementation status: CREDENTIAL_GATED. The decode/correlation/reorg logic is
complete and fixture-proven; LIVE scanning requires per-network RPC endpoints
and (for the guardian-VAA attestation leg) guardian / Wormholescan API access,
which this environment does not hold. Every seam that would touch a live
network is injected so tests and future live wiring share ONE code path. This
adapter OBSERVES only — it never relays, re-signs, re-submits, or recovers a
message (``execution_by_aether=False``).

Security & finality semantics (NOT interchangeable with other providers)
------------------------------------------------------------------------
Wormhole's verification is a **19-guardian multisig**: a message is "verified"
once >= 13/19 guardians (a super-majority quorum) co-sign the message body,
producing a VAA (Verified Action Approval). This is a fixed, permissioned
guardian set — materially different from LayerZero's per-OApp configurable DVN
set, Axelar's proof-of-stake validator set, and CCIP's DON + Risk-Management-
Network blessing. Source finality is governed by the emitter-supplied
``consistencyLevel`` (e.g. 1 = published, 200/201 = "safe"/"finalized" on chains
that expose those tags); guardians wait for that level before signing. The VAA
carries a ``guardianSetIndex`` — a rotated guardian set means a *different*
signing quorum, which the security-policy snapshot records.

Mapping (provider-native -> canonical)
--------------------------------------
    Integrator contract          -> InteropApplication
    Core Bridge / Token Bridge   -> InteropGateway
    (emitterChain, emitterAddr,
     sequence)                   -> canonical message id ("wh:<chain>/<addr>/<seq>")
    LogMessagePublished          -> phase "sent"      (source core bridge)
    Signed VAA (guardian quorum) -> phase "verified"  (attestation, API-gated)
    TransferRedeemed             -> phase "delivered" (destination token bridge)
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

# ── Event signatures (Core Bridge + Token Bridge) ────────────────────────────
SIG_LOG_MESSAGE_PUBLISHED = "LogMessagePublished(address,uint64,uint32,bytes,uint8)"
SIG_TRANSFER_REDEEMED = "TransferRedeemed(uint16,bytes32,uint64)"

TOPIC_LOG_MESSAGE_PUBLISHED = "0x" + keccak(text=SIG_LOG_MESSAGE_PUBLISHED).hex()
TOPIC_TRANSFER_REDEEMED = "0x" + keccak(text=SIG_TRANSFER_REDEEMED).hex()

# Wormhole chain-id -> network metadata (seeded mainnets; extended via config).
# NOTE: Wormhole chain ids are the protocol's own enumeration, NOT EVM chain ids.
DEFAULT_WORMHOLE_CHAINS: dict[int, dict[str, str]] = {
    2: {"network_id": "ethereum-mainnet", "native_chain_id": "1"},
    23: {"network_id": "arbitrum-mainnet", "native_chain_id": "42161"},
    30: {"network_id": "base-mainnet", "native_chain_id": "8453"},
}

DEFAULT_CONFIRMATIONS = 15
DEFAULT_MAX_BLOCK_SPAN = 2_000
_RECENT_HASHES_KEPT = 32
_GUARDIAN_QUORUM = 13
_GUARDIAN_SET_SIZE = 19


class WormholeRateLimitError(RpcRateLimited):
    """Raised by an RPC/API client when a provider rate limit is hit. Carries an
    optional ``retry_after`` (seconds, int) the adapter surfaces via health."""

    def __init__(self, message: str = "rate limited", retry_after: Optional[int] = None) -> None:
        super().__init__(message, retry_after=retry_after)


class RpcClient(Protocol):
    """Injected JSON-RPC access — a fixture client in tests, HTTP in prod."""

    async def get_head(self, network_id: str) -> dict[str, Any]: ...
    async def get_logs(
        self, network_id: str, from_block: int, to_block: int,
    ) -> list[dict[str, Any]]: ...
    async def get_block_hash(self, network_id: str, block_number: int) -> str: ...


class GuardianApiClient(Protocol):
    """Injected guardian / Wormholescan access for the VAA attestation leg.

    Returns the raw signed-VAA bytes for a (chain, emitter, sequence) triple, or
    None when the guardians have not yet reached quorum. Credential-gated: absent
    this client the adapter honestly emits no ``verified`` observations."""

    async def get_signed_vaa(
        self, emitter_chain: int, emitter_address: str, sequence: int,
    ) -> Optional[bytes]: ...


# ── pure ABI helpers (byte-slicing, no web3) ─────────────────────────────────

def _strip0x(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def _word(value: int) -> bytes:
    return value.to_bytes(32, "big")


def encode_log_message_published_data(
    sequence: int, nonce: int, payload: bytes, consistency_level: int,
) -> str:
    """ABI-encode LogMessagePublished non-indexed data:
    (uint64 sequence, uint32 nonce, bytes payload, uint8 consistencyLevel).
    Head = 4 words (payload is the sole dynamic member -> holds an offset)."""
    head = 4 * 32
    padded_payload = payload.ljust((len(payload) + 31) // 32 * 32, b"\x00")
    data = (
        _word(sequence)
        + _word(nonce)
        + _word(head)
        + _word(consistency_level)
        + _word(len(payload))
        + padded_payload
    )
    return "0x" + data.hex()


def decode_log_message_published_data(data_hex: str) -> dict[str, Any]:
    """Decode LogMessagePublished data. sequence/nonce/consistencyLevel are
    static head words; payload is a dynamic-bytes tail addressed by word 2."""
    data = _strip0x(data_hex)
    if len(data) < 128:
        raise ValueError("LogMessagePublished data too short")
    sequence = int.from_bytes(data[0:32], "big")
    nonce = int.from_bytes(data[32:64], "big")
    payload_offset = int.from_bytes(data[64:96], "big")
    consistency_level = int.from_bytes(data[96:128], "big")
    payload_len = int.from_bytes(data[payload_offset:payload_offset + 32], "big")
    payload = data[payload_offset + 32: payload_offset + 32 + payload_len]
    return {
        "sequence": sequence,
        "nonce": nonce,
        "consistency_level": consistency_level,
        "payload": "0x" + payload.hex(),
        "payload_hash": "0x" + keccak(payload).hex(),
        "payload_length": payload_len,
    }


def encode_vaa(
    guardian_set_index: int,
    signatures: list[tuple[int, bytes]],
    timestamp: int,
    nonce: int,
    emitter_chain: int,
    emitter_address: bytes,
    sequence: int,
    consistency_level: int,
    payload: bytes,
    version: int = 1,
) -> bytes:
    """Assemble a signed VAA exactly as the wire format defines it, so the
    fixture generator and ``decode_vaa`` can never drift. ``signatures`` is a
    list of (guardianIndex, 65-byte signature)."""
    if len(emitter_address) != 32:
        raise ValueError("emitter_address must be a 32-byte value")
    body = (
        timestamp.to_bytes(4, "big")
        + nonce.to_bytes(4, "big")
        + emitter_chain.to_bytes(2, "big")
        + emitter_address
        + sequence.to_bytes(8, "big")
        + consistency_level.to_bytes(1, "big")
        + payload
    )
    header = version.to_bytes(1, "big") + guardian_set_index.to_bytes(4, "big")
    header += len(signatures).to_bytes(1, "big")
    for index, sig in signatures:
        if len(sig) != 65:
            raise ValueError("each guardian signature must be 65 bytes")
        header += index.to_bytes(1, "big") + sig
    return header + body


def decode_vaa(vaa_bytes: bytes) -> dict[str, Any]:
    """Decode a signed VAA into its identity + guardian-quorum evidence.

    The VAA hash used by on-chain consumers is keccak(keccak(body)) — a double
    hash of the signed body (everything after the signature block)."""
    if len(vaa_bytes) < 6:
        raise ValueError("VAA too short for a header")
    offset = 0
    version = vaa_bytes[offset]
    offset += 1
    guardian_set_index = int.from_bytes(vaa_bytes[offset:offset + 4], "big")
    offset += 4
    signature_count = vaa_bytes[offset]
    offset += 1
    signature_indices: list[int] = []
    for _ in range(signature_count):
        if offset + 66 > len(vaa_bytes):
            raise ValueError("VAA signature block truncated")
        signature_indices.append(vaa_bytes[offset])
        offset += 66  # guardianIndex(1) + signature(65)
    body = vaa_bytes[offset:]
    if len(body) < 51:
        raise ValueError("VAA body too short")
    timestamp = int.from_bytes(body[0:4], "big")
    nonce = int.from_bytes(body[4:8], "big")
    emitter_chain = int.from_bytes(body[8:10], "big")
    emitter_address = body[10:42]
    sequence = int.from_bytes(body[42:50], "big")
    consistency_level = body[50]
    payload = body[51:]
    return {
        "version": version,
        "guardian_set_index": guardian_set_index,
        "signature_count": signature_count,
        "signature_indices": signature_indices,
        "timestamp": timestamp,
        "nonce": nonce,
        "emitter_chain": emitter_chain,
        "emitter_address": "0x" + emitter_address.hex(),
        "sequence": sequence,
        "consistency_level": consistency_level,
        "payload_hash": "0x" + keccak(payload).hex(),
        "vaa_hash": "0x" + keccak(keccak(body)).hex(),
        "quorum_reached": signature_count >= _GUARDIAN_QUORUM,
    }


def vaa_correlation_key(emitter_chain: int, emitter_address: str, sequence: int) -> str:
    """Canonical Wormhole message id: chain / 32-byte emitter / sequence."""
    addr = emitter_address.lower()
    if not addr.startswith("0x"):
        addr = "0x" + addr
    return f"wh:{emitter_chain}/{addr}/{sequence}"


class WormholeAdapter(OperationalFieldsMixin, InteropProviderAdapter):
    provider_id = "wormhole"
    provider_kind = "wormhole"
    display_name = "Wormhole (guardian-VAA observation adapter)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("core-v1",)
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = (
        "message_observation", "historical_backfill", "direct_rpc_observation",
        "payload_decoding", "attestation_observation", "delivery_observation",
        "asset_transfer",
    )
    known_limitations = (
        "Core-bridge LogMessagePublished decode, VAA (guardian-quorum) decode, "
        "TransferRedeemed delivery decode, GUID correlation and reorg handling "
        "are complete and fixture-proven. Live scanning requires per-network RPC "
        "endpoints; the VAA attestation leg additionally requires guardian / "
        "Wormholescan API access (both credential-gated)."
    )

    def __init__(
        self,
        rpc_client: Optional[RpcClient] = None,
        guardian_client: Optional[GuardianApiClient] = None,
        wormhole_chains: Optional[dict[int, dict[str, str]]] = None,
        confirmations: int = DEFAULT_CONFIRMATIONS,
        max_block_span: int = DEFAULT_MAX_BLOCK_SPAN,
        endpoint_refs: Optional[dict[str, str]] = None,
        secret_refs: Optional[dict[str, str]] = None,
    ) -> None:
        self.rpc = rpc_client
        self.guardian = guardian_client
        self.chains = wormhole_chains or dict(DEFAULT_WORMHOLE_CHAINS)
        self.confirmations = confirmations
        self.max_block_span = max_block_span
        # Tenant-scoped *references* only — never raw secrets/URLs.
        self.endpoint_refs = dict(endpoint_refs or {})
        self.secret_refs = dict(secret_refs or {})

    # ── decoding ─────────────────────────────────────────────────────────────

    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        topics = raw_log.get("topics") or []
        if not topics:
            return None
        topic0 = topics[0].lower()
        base = self._endpoint_base(raw_log)

        if topic0 == TOPIC_LOG_MESSAGE_PUBLISHED:
            emitter_chain = raw_log.get("wormhole_chain_id")
            if emitter_chain is None:
                emitter_chain = self._chain_id_for(raw_log.get("network_id", ""))
            if emitter_chain is None:
                return None
            # sender is the indexed emitter contract (topic1), already 32 bytes.
            emitter_address32 = self._topic_bytes32(topics[1]) if len(topics) > 1 else "0x" + "00" * 32
            decoded = decode_log_message_published_data(raw_log["data"])
            sequence = decoded["sequence"]
            key = vaa_correlation_key(emitter_chain, emitter_address32, sequence)
            return {
                **base,
                "phase": "sent",
                "correlation_key": key,
                "sequence": str(sequence),
                "payload_hash": decoded["payload_hash"],
                "source_network_id": self._network(emitter_chain),
                "destination_network_id": "unknown",  # dest lives in the app payload
                "provider_message_refs": [
                    {"alias_type": "vaa_id", "alias_value": key, "canonical": True},
                    {"alias_type": "emitter_chain", "alias_value": str(emitter_chain), "canonical": False},
                    {"alias_type": "emitter_address", "alias_value": emitter_address32, "canonical": False},
                    {"alias_type": "sequence", "alias_value": str(sequence), "canonical": False},
                    {"alias_type": "nonce", "alias_value": str(decoded["nonce"]), "canonical": False},
                ],
                "provider_native_stage": "LogMessagePublished",
                "provider_extension": {
                    "consistency_level": decoded["consistency_level"],
                    "emitter_address": emitter_address32,
                    "payload_length": decoded["payload_length"],
                },
            }

        if topic0 == TOPIC_TRANSFER_REDEEMED:
            if len(topics) < 4:
                return None
            emitter_chain = int(topics[1], 16)
            emitter_address32 = self._topic_bytes32(topics[2])
            sequence = int(topics[3], 16)
            key = vaa_correlation_key(emitter_chain, emitter_address32, sequence)
            self_chain = raw_log.get("wormhole_chain_id") or self._chain_id_for(
                raw_log.get("network_id", "")
            )
            return {
                **base,
                "phase": "delivered",
                "correlation_key": key,
                "sequence": str(sequence),
                "source_network_id": self._network(emitter_chain),
                "destination_network_id": self._network(self_chain) if self_chain else "unknown",
                "provider_message_refs": [
                    {"alias_type": "vaa_id", "alias_value": key, "canonical": True},
                    {"alias_type": "sequence", "alias_value": str(sequence), "canonical": False},
                ],
                "provider_native_stage": "TransferRedeemed",
                "provider_extension": {"asset_leg": "redeem"},
            }

        return None

    def decode_attestation(
        self, vaa_bytes: bytes, observed_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Decode a signed VAA into a canonical ``verified`` observation.

        Pure given the VAA bytes — the guardian API supplies the bytes; quorum
        (>= 13/19) is asserted from the signature count, never assumed."""
        vaa = decode_vaa(vaa_bytes)
        key = vaa_correlation_key(vaa["emitter_chain"], vaa["emitter_address"], vaa["sequence"])
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "observed_at": observed_at or utc_now_iso(),
            "phase": "verified",
            "correlation_key": key,
            "sequence": str(vaa["sequence"]),
            "payload_hash": vaa["payload_hash"],
            "source_network_id": self._network(vaa["emitter_chain"]),
            "provider_message_refs": [
                {"alias_type": "vaa_id", "alias_value": key, "canonical": True},
                {"alias_type": "vaa_hash", "alias_value": vaa["vaa_hash"], "canonical": False},
            ],
            "provider_native_stage": "SignedVAA",
            "provider_extension": {
                "guardian_set_index": vaa["guardian_set_index"],
                "signature_count": vaa["signature_count"],
                "quorum_required": _GUARDIAN_QUORUM,
                "quorum_reached": vaa["quorum_reached"],
                "consistency_level": vaa["consistency_level"],
                "vaa_hash": vaa["vaa_hash"],
            },
        }

    # ── scanning ─────────────────────────────────────────────────────────────

    async def _scan_cycle(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Scan every configured chain from its checkpoint to head-minus-
        confirmations, paginating by ``max_block_span`` and surviving rate
        limits, reorgs (block-hash mismatch), and cursor drift (checkpoint ahead
        of head). Then, if a guardian client is wired, fetch + decode the VAA for
        each newly-seen source message (the ``verified`` leg)."""
        if self.rpc is None:
            raise NotImplementedError(
                "wormhole: live scanning requires an RPC client "
                "(credential-gated — configure per-network RPC endpoints)"
            )
        checkpoint = dict(checkpoint or {})
        networks: dict[str, dict] = checkpoint.setdefault("networks", {})
        health: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        pending_vaa: list[dict[str, Any]] = []

        for chain_id, meta in self.chains.items():
            network_id = meta["network_id"]
            state = networks.setdefault(
                network_id, {"last_scanned_block": 0, "recent_hashes": {}},
            )
            discontinuity = await self._scan_one_network(
                chain_id, meta, state, observations, pending_vaa, health,
            )
            if discontinuity:
                continue

        # Attestation leg: credential-gated on the guardian client.
        if self.guardian is not None:
            for src in pending_vaa:
                await self._maybe_attest(src, observations, health)
        elif pending_vaa:
            health.append({
                "provider_id": self.provider_id,
                "state": "attestation_unconfigured",
                "detail": "guardian/Wormholescan client not wired — VAA leg skipped",
                "pending": len(pending_vaa),
            })

        checkpoint["health"] = health
        return observations, checkpoint

    async def _scan_one_network(
        self, chain_id, meta, state, observations, pending_vaa, health,
    ) -> bool:
        network_id = meta["network_id"]
        head = await self.rpc.get_head(network_id)
        head_number = int(head["number"])
        state["head_number"] = head_number
        safe_head = head_number - self.confirmations
        last = int(state["last_scanned_block"])
        recent = state.setdefault("recent_hashes", {})

        # Restart / cursor-drift: our cursor sits beyond the chain head — the
        # chain rolled back under us (or an endpoint swap). Safe-rewind + rescan.
        if last > head_number:
            observations.append(self._discontinuity("cursor_drift", network_id, safe_head, last))
            state["last_scanned_block"] = max(0, safe_head)
            state["recent_hashes"] = {}
            health.append({"provider_id": self.provider_id, "network_id": network_id,
                           "state": "cursor_drift", "rewound_to": max(0, safe_head)})
            return True

        # Reorg: the block hash we recorded for the last scanned block changed.
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

        # Parent-hash continuity (optional get_block): block(last+1).parentHash
        # must chain back to our recorded hash for `last`.
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
                break  # persist progress; the next scan resumes from `cursor`
            for raw_log in raw_logs:
                raw_log.setdefault("network_id", network_id)
                raw_log.setdefault("native_chain_id", meta["native_chain_id"])
                raw_log.setdefault("wormhole_chain_id", chain_id)
                decoded = self._decode_safely(raw_log)
                if decoded is None:
                    continue
                observations.append(decoded)
                if decoded["phase"] == "sent":
                    pending_vaa.append(decoded)
            cursor = window_to
            state["last_scanned_block"] = cursor
            recent[str(cursor)] = await self.rpc.get_block_hash(network_id, cursor)
            self._trim(recent)
        state["recent_hashes"] = recent
        return False

    async def _maybe_attest(self, source_obs, observations, health) -> None:
        refs = {r["alias_type"]: r["alias_value"] for r in source_obs["provider_message_refs"]}
        emitter_chain = int(refs["emitter_chain"])
        emitter_address = refs["emitter_address"]
        sequence = int(refs["sequence"])
        try:
            vaa_bytes = await self.guardian.get_signed_vaa(
                emitter_chain, emitter_address, sequence,
            )
        except RpcRateLimited as exc:
            health.append({"provider_id": self.provider_id, "state": "attestation_rate_limited",
                           "retry_after": exc.retry_after})
            return
        if not vaa_bytes:
            return  # quorum not yet reached — honest: no verified observation
        observations.append(self.decode_attestation(vaa_bytes))

    # ── health / security / certification ────────────────────────────────────

    def health(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Configuration-truthful health: an adapter with no RPC client is not
        healthy; the guardian client governs whether the attestation leg runs."""
        context = context or {}
        configured = context.get("configured", self.rpc is not None)
        return {
            "provider_id": self.provider_id,
            "healthy": bool(configured),
            "state": "ok" if configured else "unconfigured",
            "rpc_wired": self.rpc is not None,
            "attestation_wired": self.guardian is not None,
        }

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        """Public, protocol-level security model for a Wormhole path. Live
        guardian public keys require the on-chain guardian set (credential/RPC
        gated); the quorum shape itself is public and recorded here."""
        return {
            "verification_model": "guardian_multisig_supermajority",
            "required_verifier_ids": [f"wormhole-guardian-set:{path_id}"],
            "optional_verifier_ids": [],
            "optional_threshold": _GUARDIAN_QUORUM,
            "confirmations_required": self.confirmations,
            "delivery_actor_ids": [],
            "module_addresses": {
                "core_bridge": self.endpoint_refs.get("core_bridge", ""),
                "token_bridge": self.endpoint_refs.get("token_bridge", ""),
            },
        }

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        return AdapterCertificationDescriptor(
            provider=self.provider_id,
            domain="interoperability",
            adapter="WormholeAdapter",
            adapter_version="1.0.0",
            supported_operations=[
                "observe_source_message", "observe_vaa_attestation",
                "observe_delivery", "reorg_detection", "checkpoint_persistence",
                "security_policy_snapshot",
            ],
            unsupported_operations=[
                "relay", "vaa_submission", "message_recovery", "signing",
            ],
            required_credentials=["guardian_api_token"],
            required_endpoints=["evm_rpc_url", "guardian_rpc_url"],
            secret_ref_names=sorted(self.secret_refs.keys()) or ["wormhole_guardian_api_key_ref"],
            pagination_model="time_window",
            streaming_model="polling",
            rate_limit_behavior="honor_retry_after_and_resume_from_checkpoint",
            retry_policy="resume_from_last_confirmed_block",
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=False,
        )

    # ── certification duck-hooks (probed by shared.certification.checks) ──────

    def build_request(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Tenant-scoped request construction — echoes tenant scope and injects
        an auth reference from ctx credential (no raw secret is ever stored)."""
        credential = ctx.get("credential") or {}
        tenant_id = ctx.get("tenant_id", "")
        return {
            "endpoint": self.endpoint_refs.get("guardian_rpc_url", "guardian_rpc_url_ref"),
            "headers": {"authorization": credential.get("api_key", "")},
            "params": {"tenant_id": tenant_id},
        }

    def sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _sanitize(payload)

    def dedupe_key(self, event: dict[str, Any]) -> str:
        return str(event.get("messageId") or event.get("correlation_key") or event.get("id"))

    def sequence_of(self, event: dict[str, Any]) -> int:
        return int(event.get("seq") or event.get("sequence") or event.get("blockNumber") or 0)

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
                "gateway_id": f"wormhole:core_bridge:{network_id}",
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

    def _network(self, chain_id: Optional[int]) -> str:
        if chain_id is None:
            return "unknown"
        return self.chains.get(chain_id, {}).get("network_id", f"wormhole-chain:{chain_id}")

    def _chain_id_for(self, network_id: str) -> Optional[int]:
        for chain_id, meta in self.chains.items():
            if meta["network_id"] == network_id:
                return chain_id
        return None

    @staticmethod
    def _topic_bytes32(topic: str) -> str:
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
    """Recursively redact secret-like keys/headers. Used by the certification
    secret-redaction probe and before any evidence is persisted."""
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in _SECRET_KEYS else _sanitize(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value
