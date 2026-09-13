"""Credentialless tests for the IBC (CometBFT) packet-lifecycle adapter.

Runs against an in-memory ``MockCometBftRpcServer`` implementing the injectable
Tendermint RPC seam (status / block_results / block_hash) — NO live network.
Because IBC is attribute-based (not EVM logs), the mock emits CometBFT events with
key/value attributes, in both plain and base64 encodings. Proves: real
send/recv/ack packet decode, packet-tuple correlation, the source->delivered->
settled lifecycle through the real CorrelationEngine, out-of-order join, timeout
-> failed, restart-safe height resume, chain-discontinuity + cursor-drift rewind,
rate-limit-safe resume, honest CREDENTIAL_GATED status, the unwired-client guard,
and a light-client security model distinct from message-passing bridges.
"""
from __future__ import annotations

import base64
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
from services.interop.providers.ibc import IbcAdapter, RateLimited
from shared.certification.readiness import CredentialReadiness

HUB = "cosmoshub-4"
OSMO = "osmosis-1"
CHAINS = {HUB: {"network_id": HUB}, OSMO: {"network_id": OSMO}}
CHANNEL_NETWORKS = {"channel-141": HUB, "channel-0": OSMO}

# Canonical packet tuple: transfer/channel-141 (hub) -> transfer/channel-0 (osmo)
SRC_PORT, SRC_CH, DST_PORT, DST_CH = "transfer", "channel-141", "transfer", "channel-0"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    yield


def _packet_attrs(sequence: int, extra: dict | None = None) -> list[dict]:
    attrs = {
        "packet_sequence": str(sequence),
        "packet_src_port": SRC_PORT, "packet_src_channel": SRC_CH,
        "packet_dst_port": DST_PORT, "packet_dst_channel": DST_CH,
        "packet_data_hex": "7b22616d6f756e74223a2231227d",
        "connection_id": "connection-0",
    }
    if extra:
        attrs.update(extra)
    return [{"key": key, "value": value} for key, value in attrs.items()]


def _event(event_type: str, sequence: int, base64_encoded: bool = False) -> dict:
    attributes = _packet_attrs(sequence)
    if base64_encoded:
        attributes = [
            {"key": base64.b64encode(a["key"].encode()).decode(),
             "value": base64.b64encode(a["value"].encode()).decode()}
            for a in attributes
        ]
        return {"type": event_type, "attributes": attributes, "attributes_encoding": "base64"}
    return {"type": event_type, "attributes": attributes}


class MockCometBftRpcServer:
    """In-memory Tendermint RPC double: status, block_results per height, block
    hashes, with injectable rate-limit + rollback for resilience tests."""

    def __init__(self):
        self.height: dict[str, int] = {}
        self.blocks: dict[tuple[str, int], dict] = {}
        self.hashes: dict[tuple[str, int], str] = {}
        self._rl_after: dict[str, int] = {}
        self._block_calls: dict[str, int] = {}

    def set_height(self, chain_id, height):
        self.height[chain_id] = height

    def add_tx_events(self, chain_id, height, events, tx_hash="0xTX"):
        block = self.blocks.setdefault(
            (chain_id, height), {"height": height, "block_hash": f"0xbh-{chain_id}-{height}",
                                 "txs_results": [], "begin_block_events": [], "end_block_events": []})
        block["txs_results"].append({"hash": tx_hash, "events": events})
        self.hashes.setdefault((chain_id, height), block["block_hash"])

    def set_block_hash(self, chain_id, height, value):
        self.hashes[(chain_id, height)] = value
        if (chain_id, height) in self.blocks:
            self.blocks[(chain_id, height)]["block_hash"] = value

    def rate_limit_after(self, chain_id, n_calls):
        self._rl_after[chain_id] = n_calls

    async def get_status(self, chain_id):
        return {"latest_block_height": self.height.get(chain_id, 0),
                "latest_block_hash": self.hashes.get((chain_id, self.height.get(chain_id, 0)), "0x")}

    async def get_block_results(self, chain_id, height):
        self._block_calls[chain_id] = self._block_calls.get(chain_id, 0) + 1
        limit = self._rl_after.get(chain_id)
        if limit is not None and self._block_calls[chain_id] > limit:
            raise RateLimited(f"{chain_id}: throttled")
        return self.blocks.get(
            (chain_id, height),
            {"height": height, "block_hash": self.hashes.get((chain_id, height), f"0xbh-{chain_id}-{height}"),
             "txs_results": [], "begin_block_events": [], "end_block_events": []})

    async def get_block_hash(self, chain_id, height):
        return self.hashes.get((chain_id, height), f"0xbh-{chain_id}-{height}")


def _adapter(server=None):
    return IbcAdapter(rpc_client=server, chains=CHAINS, channel_networks=CHANNEL_NETWORKS,
                      finality_depth=0)


# ── decode (attribute-based, not EVM logs) ───────────────────────────────────

def test_send_packet_decodes_packet_tuple_key_and_route():
    obs = IbcAdapter(channel_networks=CHANNEL_NETWORKS).decode_log(
        {**_event("send_packet", 42), "network_id": HUB, "chain_id": HUB,
         "tx_hash": "0xTX", "height": 1000, "block_hash": "0xBH", "event_index": 0})
    assert obs["phase"] == "sent"
    assert obs["correlation_key"] == "ibc:transfer/channel-141/transfer/channel-0/42"
    assert obs["source_network_id"] == HUB and obs["destination_network_id"] == OSMO
    assert obs["sequence"] == "42"
    assert obs["payload_hash"].startswith("sha256:")
    assert obs["endpoint_ref"]["block_number"] == "1000"


def test_recv_packet_base64_attributes_are_decoded():
    obs = IbcAdapter(channel_networks=CHANNEL_NETWORKS).decode_log(
        {**_event("recv_packet", 42, base64_encoded=True), "network_id": OSMO, "chain_id": OSMO,
         "tx_hash": "0xTX2", "height": 2000, "block_hash": "0xBH2", "event_index": 0})
    assert obs["phase"] == "delivered"
    assert obs["correlation_key"] == "ibc:transfer/channel-141/transfer/channel-0/42"


def test_non_ibc_and_incomplete_events_return_none():
    adapter = IbcAdapter(channel_networks=CHANNEL_NETWORKS)
    assert adapter.decode_log({"type": "coin_received", "attributes": []}) is None
    assert adapter.decode_log({"type": "send_packet", "attributes": [
        {"key": "packet_sequence", "value": "1"}]}) is None  # missing channels


# ── lifecycle across two chains via block_results scan ───────────────────────

@pytest.mark.asyncio
async def test_scan_two_chains_drives_sent_delivered_settled():
    server = MockCometBftRpcServer()
    server.set_height(HUB, 100)
    server.set_height(OSMO, 100)
    server.add_tx_events(HUB, 10, [_event("send_packet", 7)])
    server.add_tx_events(OSMO, 20, [_event("recv_packet", 7), _event("write_acknowledgement", 7)])
    server.add_tx_events(HUB, 30, [_event("acknowledge_packet", 7)])

    observations, _ = await _adapter(server).scan()
    phases = {o["phase"] for o in observations}
    assert {"sent", "delivered", "executed", "settled"} <= phases, phases

    engine = CorrelationEngine()
    order = {"sent": 0, "delivered": 1, "executed": 2, "settled": 3}
    for obs in sorted(observations, key=lambda o: order[o["phase"]]):
        await engine.ingest_observation(PUBLIC_TENANT, obs)
    message = await engine.messages.find_one(
        {"tenant_id": PUBLIC_TENANT, "provider_kind": "ibc",
         "correlation_key": "ibc:transfer/channel-141/transfer/channel-0/7"})
    assert message["status"] == "settled"
    assert message["source"]["network_id"] == HUB
    assert message["destination"]["network_id"] == OSMO


@pytest.mark.asyncio
async def test_out_of_order_recv_before_send_correlates():
    adapter = IbcAdapter(channel_networks=CHANNEL_NETWORKS)
    recv = adapter.decode_log({**_event("recv_packet", 9), "network_id": OSMO, "chain_id": OSMO,
                               "tx_hash": "0xr", "height": 5, "block_hash": "0xh", "event_index": 0})
    send = adapter.decode_log({**_event("send_packet", 9), "network_id": HUB, "chain_id": HUB,
                               "tx_hash": "0xs", "height": 4, "block_hash": "0xh", "event_index": 0})
    engine = CorrelationEngine()
    first = await engine.ingest_observation(PUBLIC_TENANT, recv)
    assert first["out_of_order"] is True
    second = await engine.ingest_observation(PUBLIC_TENANT, send)
    assert "interop_message_correlated" in [e["event_name"] for e in second["emitted_events"]]


@pytest.mark.asyncio
async def test_timeout_packet_maps_to_failed():
    server = MockCometBftRpcServer()
    server.set_height(HUB, 50)
    server.set_height(OSMO, 0)
    server.add_tx_events(HUB, 5, [_event("send_packet", 3)])
    server.add_tx_events(HUB, 8, [_event("timeout_packet", 3)])
    observations, _ = await _adapter(server).scan()
    assert any(o["phase"] == "failed" for o in observations)


# ── resilience ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restart_resume_by_height_is_idempotent():
    server = MockCometBftRpcServer()
    server.set_height(HUB, 100)
    server.set_height(OSMO, 0)
    server.add_tx_events(HUB, 10, [_event("send_packet", 1)])
    adapter = _adapter(server)
    first, checkpoint = await adapter.scan()
    assert len(first) == 1
    second, checkpoint = await adapter.scan(checkpoint)
    assert second == []
    assert checkpoint["networks"][HUB]["last_scanned_height"] == 100


@pytest.mark.asyncio
async def test_chain_discontinuity_rewinds_on_hash_mismatch():
    server = MockCometBftRpcServer()
    server.set_height(HUB, 30)
    server.set_height(OSMO, 0)
    server.add_tx_events(HUB, 10, [_event("send_packet", 1)])
    adapter = _adapter(server)
    _, checkpoint = await adapter.scan()
    last = checkpoint["networks"][HUB]["last_scanned_height"]
    assert last == 30
    # Simulate a rollback/upgrade: the stored height's block hash changed.
    server.set_block_hash(HUB, last, "0xROLLBACK")
    server.set_height(HUB, 45)
    observations, checkpoint = await adapter.scan(checkpoint)
    assert any(o["phase"] == "reorged" and o["network_id"] == HUB for o in observations)
    assert checkpoint["networks"][HUB]["last_scanned_height"] < last


@pytest.mark.asyncio
async def test_cursor_drift_beyond_head_rewinds():
    server = MockCometBftRpcServer()
    server.set_height(HUB, 20)
    server.set_height(OSMO, 20)
    drifted = {"networks": {HUB: {"last_scanned_height": 9999, "recent_hashes": {}},
                            OSMO: {"last_scanned_height": 0, "recent_hashes": {}}}}
    observations, checkpoint = await _adapter(server).scan(drifted)
    assert any(o["phase"] == "reorged" and o["network_id"] == HUB for o in observations)
    assert checkpoint["networks"][HUB]["last_scanned_height"] <= 20


@pytest.mark.asyncio
async def test_rate_limit_partial_then_resume_by_height():
    server = MockCometBftRpcServer()
    server.set_height(HUB, 20)
    server.set_height(OSMO, 0)
    for height in range(1, 16):
        server.add_tx_events(HUB, height, [_event("send_packet", height)])
    adapter = IbcAdapter(rpc_client=server, chains=CHAINS, channel_networks=CHANNEL_NETWORKS,
                         finality_depth=0, max_heights_per_scan=100)
    server.rate_limit_after(HUB, 5)   # throttle after 5 block_results calls
    partial, checkpoint = await adapter.scan()
    resumed = checkpoint["networks"][HUB]["last_scanned_height"]
    assert 0 < resumed < 20
    server._rl_after.pop(HUB, None)
    rest, checkpoint = await adapter.scan(checkpoint)
    assert checkpoint["networks"][HUB]["last_scanned_height"] == 20
    assert len(partial) + len(rest) == 15


@pytest.mark.asyncio
async def test_pagination_caps_heights_per_scan():
    server = MockCometBftRpcServer()
    server.set_height(HUB, 1000)
    server.set_height(OSMO, 0)
    for height in range(1, 12):
        server.add_tx_events(HUB, height, [_event("send_packet", height)])
    adapter = IbcAdapter(rpc_client=server, chains=CHAINS, channel_networks=CHANNEL_NETWORKS,
                         finality_depth=0, max_heights_per_scan=5)
    first, checkpoint = await adapter.scan()
    assert checkpoint["networks"][HUB]["last_scanned_height"] == 5
    # subsequent polls advance one page at a time until the head is reached.
    await adapter.scan(checkpoint)
    third, checkpoint = await adapter.scan(checkpoint)
    assert checkpoint["networks"][HUB]["last_scanned_height"] == 15


# ── status / guard / certification / security ────────────────────────────────

def test_status_is_credential_gated():
    assert IbcAdapter().implementation_status == ImplementationStatus.CREDENTIAL_GATED


@pytest.mark.asyncio
async def test_unwired_client_raises():
    with pytest.raises(NotImplementedError):
        await IbcAdapter(rpc_client=None, chains=CHAINS).scan()


def test_certification_descriptor_credential_waiting():
    descriptor = IbcAdapter().certification_descriptor()
    assert descriptor.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
    assert descriptor.provider == "ibc"
    assert IbcAdapter().descriptor()["execution_by_aether"] is False


def test_security_model_is_light_client_not_bridge_attestation():
    model = IbcAdapter().security_model()
    assert model["verification_model"] == "light_client"
    assert model["external_validator_set"] is False
    assert model["attestation_on_chain"] is True
    # Distinct from Hyperlane (ISM) and deBridge (external validators).
    assert model["verification_model"] not in ("modular_ism", "external_validator_set")
