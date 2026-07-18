"""Credentialless tests for the Hyperlane Mailbox observation adapter.

Everything runs against an in-memory ``MockEvmRpcServer`` implementing the same
injectable RPC seam LayerZero V2 uses — NO live network. The suite proves:
real Dispatch/DispatchId + Process/ProcessId decode, message-id correlation, the
end-to-end source->delivered lifecycle through the real CorrelationEngine,
out-of-order (delivery seen first) join, restart-safe cursor resume, reorg and
cursor-drift rewind, rate-limit-safe partial resume + resume, the Dispatch/
DispatchId dedup and Process->ProcessId enrichment join, the honest
CREDENTIAL_GATED status, the unwired-client guard, and the CREDENTIAL_WAITING
certification descriptor with a light-client-distinct security model.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.repos import reset_in_memory_stores
from repositories.typed_repo import reset_typed_in_memory_stores
from services.integrations.connectors.base import ImplementationStatus
from services.interop.correlation import CorrelationEngine
from services.interop.foundation import PUBLIC_TENANT
from services.interop.providers.hyperlane import (
    TOPIC_DISPATCH,
    TOPIC_DISPATCH_ID,
    TOPIC_PROCESS,
    TOPIC_PROCESS_ID,
    HyperlaneAdapter,
    RateLimited,
    encode_dispatch_data,
    encode_hyperlane_message,
    hyperlane_message_id,
)
from shared.certification.readiness import CredentialReadiness

ETH = "ethereum-mainnet"
ARB = "arbitrum-mainnet"
DOMAINS = {
    1: {"network_id": ETH, "native_chain_id": "1"},
    42161: {"network_id": ARB, "native_chain_id": "42161"},
}


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    yield


class MockEvmRpcServer:
    """In-memory EVM JSON-RPC double: heads, logs by block, block hashes, plus
    injectable rate-limit + reorg for resilience tests."""

    def __init__(self):
        self.heads: dict[str, int] = {}
        self.logs: dict[str, list[tuple[int, dict]]] = {}
        self.hashes: dict[tuple[str, int], str] = {}
        self._rl_after: dict[str, int] = {}
        self._get_logs_calls: dict[str, int] = {}

    def set_head(self, network_id: str, number: int):
        self.heads[network_id] = number

    def add_log(self, network_id: str, block_number: int, log: dict):
        log = {**log, "blockNumber": block_number}
        self.logs.setdefault(network_id, []).append((block_number, log))
        self.hashes.setdefault((network_id, block_number), f"0xhash-{network_id}-{block_number}")

    def set_block_hash(self, network_id: str, block: int, value: str):
        self.hashes[(network_id, block)] = value

    def rate_limit_after(self, network_id: str, n_calls: int):
        self._rl_after[network_id] = n_calls

    async def get_head(self, network_id: str):
        return {"number": self.heads.get(network_id, 0)}

    async def get_logs(self, network_id: str, from_block: int, to_block: int):
        self._get_logs_calls[network_id] = self._get_logs_calls.get(network_id, 0) + 1
        limit = self._rl_after.get(network_id)
        if limit is not None and self._get_logs_calls[network_id] > limit:
            raise RateLimited(f"{network_id}: throttled")
        return [dict(log) for block, log in self.logs.get(network_id, []) if from_block <= block <= to_block]

    async def get_block_hash(self, network_id: str, block: int):
        return self.hashes.get((network_id, block), f"0xhash-{network_id}-{block}")


def _sender32(byte: int) -> bytes:
    return b"\x00" * 12 + bytes([byte]) * 20


def _bytes32(byte: int) -> bytes:
    return bytes([byte]) * 32


def _dispatch_log(msg: bytes, tx: str, log_index: int) -> dict:
    decoded_recipient = msg[45:77]
    return {
        "topics": [
            TOPIC_DISPATCH,
            "0x" + (b"\x00" * 12 + b"\xaa" * 20).hex(),
            "0x" + (42161).to_bytes(32, "big").hex(),
            "0x" + decoded_recipient.hex(),
        ],
        "data": encode_dispatch_data(msg),
        "transactionHash": tx,
        "blockHash": "0xblk",
        "logIndex": log_index,
    }


def _dispatch_id_log(message_id: str, tx: str, log_index: int) -> dict:
    return {"topics": [TOPIC_DISPATCH_ID, message_id], "data": "0x",
            "transactionHash": tx, "blockHash": "0xblk", "logIndex": log_index}


def _process_log(origin_domain: int, tx: str, log_index: int) -> dict:
    return {"topics": [TOPIC_PROCESS, "0x" + origin_domain.to_bytes(32, "big").hex(),
                       "0x" + _sender32(0xAA).hex(), "0x" + (b"\x00" * 12 + b"\xbb" * 20).hex()],
            "data": "0x", "transactionHash": tx, "blockHash": "0xblk", "logIndex": log_index}


def _process_id_log(message_id: str, tx: str, log_index: int) -> dict:
    return {"topics": [TOPIC_PROCESS_ID, message_id], "data": "0x",
            "transactionHash": tx, "blockHash": "0xblk", "logIndex": log_index}


def _message(nonce: int) -> bytes:
    return encode_hyperlane_message(
        nonce=nonce, origin=1, sender32=_sender32(0xAA),
        destination=42161, recipient32=_bytes32(0x22), body=b"payload-%d" % nonce,
    )


# ── decode ───────────────────────────────────────────────────────────────────

def test_decode_dispatch_is_real_and_self_correlating():
    adapter = HyperlaneAdapter(domain_networks=DOMAINS)
    msg = _message(7)
    obs = adapter.decode_log({**_dispatch_log(msg, "0xtx", 0), "network_id": ETH})
    assert obs["phase"] == "sent"
    assert obs["correlation_key"] == f"hyp:{hyperlane_message_id(msg)}"
    assert obs["source_network_id"] == ETH
    assert obs["destination_network_id"] == ARB
    assert obs["provider_native_stage"] == "Dispatch"
    assert any(r["alias_type"] == "message_id" and r["canonical"] for r in obs["provider_message_refs"])


def test_decode_process_id_is_delivered_phase():
    adapter = HyperlaneAdapter(domain_networks=DOMAINS)
    mid = hyperlane_message_id(_message(7))
    obs = adapter.decode_log({**_process_id_log(mid, "0xtx", 0), "network_id": ARB})
    assert obs["phase"] == "delivered"
    assert obs["correlation_key"] == f"hyp:{mid}"
    assert obs["destination_network_id"] == ARB


def test_process_alone_has_no_message_id_returns_none():
    adapter = HyperlaneAdapter(domain_networks=DOMAINS)
    assert adapter.decode_log({**_process_log(1, "0xtx", 0), "network_id": ARB}) is None


# ── scan + correlation lifecycle ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_drives_full_source_to_delivered_lifecycle():
    server = MockEvmRpcServer()
    msg = _message(11)
    mid = hyperlane_message_id(msg)
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 50, _dispatch_log(msg, "0xsrc", 0))
    server.add_log(ARB, 60, _process_log(1, "0xdst", 0))
    server.add_log(ARB, 60, _process_id_log(mid, "0xdst", 1))

    adapter = HyperlaneAdapter(rpc_client=server, domain_networks=DOMAINS, confirmations=0)
    observations, checkpoint = await adapter.scan()

    phases = sorted(o["phase"] for o in observations)
    assert phases == ["delivered", "sent"], phases

    engine = CorrelationEngine()
    events = []
    for obs in observations:
        result = await engine.ingest_observation(PUBLIC_TENANT, obs)
        events.extend(e["event_name"] for e in result["emitted_events"])
    assert "interop_message_correlated" in events

    message = await engine.messages.find_one(
        {"tenant_id": PUBLIC_TENANT, "provider_kind": "hyperlane", "correlation_key": f"hyp:{mid}"})
    assert message["status"] == "delivered"
    assert message["source"]["network_id"] == ETH
    assert message["destination"]["network_id"] == ARB


@pytest.mark.asyncio
async def test_out_of_order_delivery_before_source_still_correlates():
    msg = _message(12)
    mid = hyperlane_message_id(msg)
    adapter = HyperlaneAdapter(domain_networks=DOMAINS)
    delivered = adapter.decode_log({**_process_id_log(mid, "0xd", 0), "network_id": ARB})
    sent = adapter.decode_log({**_dispatch_log(msg, "0xs", 0), "network_id": ETH})

    engine = CorrelationEngine()
    first = await engine.ingest_observation(PUBLIC_TENANT, delivered)  # destination first
    assert first["out_of_order"] is True
    second = await engine.ingest_observation(PUBLIC_TENANT, sent)
    names = [e["event_name"] for e in second["emitted_events"]]
    assert "interop_message_correlated" in names
    message = await engine.messages.find_one(
        {"tenant_id": PUBLIC_TENANT, "provider_kind": "hyperlane", "correlation_key": f"hyp:{mid}"})
    assert message["source"] and message["destination"]


@pytest.mark.asyncio
async def test_dispatch_supersedes_dispatch_id_and_process_enriches_process_id():
    server = MockEvmRpcServer()
    msg = _message(13)
    mid = hyperlane_message_id(msg)
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 40, _dispatch_log(msg, "0xsrc", 0))
    server.add_log(ETH, 40, _dispatch_id_log(mid, "0xsrc", 1))   # same tx -> deduped
    server.add_log(ARB, 41, _process_log(1, "0xdst", 0))
    server.add_log(ARB, 41, _process_id_log(mid, "0xdst", 1))

    adapter = HyperlaneAdapter(rpc_client=server, domain_networks=DOMAINS, confirmations=0)
    observations, _ = await adapter.scan()

    sent = [o for o in observations if o["phase"] == "sent"]
    assert len(sent) == 1 and sent[0]["provider_native_stage"] == "Dispatch"
    delivered = [o for o in observations if o["phase"] == "delivered"][0]
    # Process (origin domain 1) enriched the ProcessId delivered observation.
    assert delivered["source_network_id"] == ETH
    assert delivered["provider_extension"]["origin_domain"] == 1


# ── restart / reorg / cursor-drift / rate-limit ──────────────────────────────

@pytest.mark.asyncio
async def test_restart_resume_is_idempotent_from_checkpoint():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 50, _dispatch_log(_message(1), "0xa", 0))
    adapter = HyperlaneAdapter(rpc_client=server, domain_networks=DOMAINS, confirmations=0)

    first, checkpoint = await adapter.scan()
    assert len(first) == 1
    # Re-scan from the persisted checkpoint yields nothing new (idempotent).
    second, checkpoint = await adapter.scan(checkpoint)
    assert second == []
    # A new event after the cursor is picked up on the next poll.
    server.set_head(ETH, 140)
    server.add_log(ETH, 120, _dispatch_log(_message(2), "0xb", 0))
    third, _ = await adapter.scan(checkpoint)
    assert len(third) == 1 and third[0]["phase"] == "sent"


@pytest.mark.asyncio
async def test_reorg_emits_reorged_observation_and_rewinds():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 90, _dispatch_log(_message(1), "0xa", 0))
    adapter = HyperlaneAdapter(rpc_client=server, domain_networks=DOMAINS, confirmations=0)
    _, checkpoint = await adapter.scan()
    last = checkpoint["networks"][ETH]["last_scanned_block"]
    assert last == 100

    # Chain reorged: the recorded hash of the last scanned block no longer matches.
    server.set_block_hash(ETH, last, "0xREORGED")
    server.set_head(ETH, 130)
    observations, checkpoint = await adapter.scan(checkpoint)
    reorgs = [o for o in observations if o["phase"] == "reorged" and o["network_id"] == ETH]
    assert reorgs, observations
    assert checkpoint["networks"][ETH]["last_scanned_block"] < last


@pytest.mark.asyncio
async def test_cursor_drift_beyond_head_triggers_safe_rewind():
    server = MockEvmRpcServer()
    server.set_head(ETH, 80)
    server.set_head(ARB, 80)
    adapter = HyperlaneAdapter(rpc_client=server, domain_networks=DOMAINS, confirmations=0)
    drifted = {"networks": {ETH: {"last_scanned_block": 5000, "recent_hashes": {}},
                            ARB: {"last_scanned_block": 0, "recent_hashes": {}}}}
    observations, checkpoint = await adapter.scan(drifted)
    reorgs = [o for o in observations if o["phase"] == "reorged" and o["network_id"] == ETH]
    assert reorgs, observations
    assert checkpoint["networks"][ETH]["last_scanned_block"] <= 80


@pytest.mark.asyncio
async def test_rate_limit_checkpoints_partial_then_resumes():
    server = MockEvmRpcServer()
    server.set_head(ETH, 40)
    server.set_head(ARB, 0)
    for block in range(1, 31):
        server.add_log(ETH, block, _dispatch_log(_message(block), f"0x{block:x}", 0))
    # Small windows so several get_logs calls are needed; throttle after the 1st.
    adapter = HyperlaneAdapter(rpc_client=server, domain_networks=DOMAINS,
                               confirmations=0, max_block_span=5)
    server.rate_limit_after(ETH, 1)
    partial, checkpoint = await adapter.scan()
    resumed_at = checkpoint["networks"][ETH]["last_scanned_block"]
    assert 0 < resumed_at < 40, resumed_at
    assert len(partial) >= 1

    # Lift the throttle; the next poll resumes from the checkpoint and finishes.
    server._rl_after.pop(ETH, None)
    rest, checkpoint = await adapter.scan(checkpoint)
    assert checkpoint["networks"][ETH]["last_scanned_block"] == 40
    assert len(partial) + len(rest) == 30


# ── status / guard / certification / security ────────────────────────────────

def test_implementation_status_is_credential_gated():
    assert HyperlaneAdapter().implementation_status == ImplementationStatus.CREDENTIAL_GATED


@pytest.mark.asyncio
async def test_unwired_live_client_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        await HyperlaneAdapter(rpc_client=None).scan()


def test_certification_descriptor_is_credential_waiting_and_observation_only():
    descriptor = HyperlaneAdapter().certification_descriptor()
    assert descriptor.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
    assert descriptor.provider == "hyperlane"
    assert "relay" in descriptor.unsupported_operations
    assert HyperlaneAdapter().descriptor()["execution_by_aether"] is False


def test_security_model_is_ism_not_flattened():
    model = HyperlaneAdapter().security_model()
    assert model["verification_model"] == "modular_ism"
    assert model["has_independent_verification_event"] is False
    # Not a light client, not an external validator set.
    assert model["verification_model"] != "light_client"
