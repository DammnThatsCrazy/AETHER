"""Credentialless tests for the deBridge DLN + Gate observation adapter.

Runs against an in-memory ``MockEvmRpcServer`` (same injectable seam as
LayerZero V2) — NO live network. Proves: real CreatedOrder/FulfilledOrder/
ClaimedOrder (DLN) and Sent/Claimed (Gate) decode with order/submission ids, the
end-to-end source->delivered->settled DLN lifecycle through the real
CorrelationEngine, out-of-order join, restart-safe resume, reorg + cursor-drift
rewind, rate-limit-safe resume, honest CREDENTIAL_GATED status, the unwired-client
guard, and the CREDENTIAL_WAITING certification descriptor with an
external-validator-set security model distinct from IBC's light client.
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
from services.interop.providers.debridge import (
    TOPIC_CLAIMED,
    TOPIC_CLAIMED_ORDER,
    TOPIC_CREATED_ORDER,
    TOPIC_FULFILLED_ORDER,
    TOPIC_SENT,
    DebridgeAdapter,
    RateLimited,
    encode_claimed_data,
    encode_claimed_order_data,
    encode_created_order_data,
    encode_dln_order,
    encode_fulfilled_order_data,
    encode_sent_data,
)
from shared.certification.readiness import CredentialReadiness

ETH = "ethereum-mainnet"
ARB = "arbitrum-mainnet"
CHAINS = {
    1: {"network_id": ETH, "native_chain_id": "1"},
    42161: {"network_id": ARB, "native_chain_id": "42161"},
}


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    yield


class MockEvmRpcServer:
    def __init__(self):
        self.heads: dict[str, int] = {}
        self.logs: dict[str, list[tuple[int, dict]]] = {}
        self.hashes: dict[tuple[str, int], str] = {}
        self._rl_after: dict[str, int] = {}
        self._get_logs_calls: dict[str, int] = {}

    def set_head(self, network_id, number):
        self.heads[network_id] = number

    def add_log(self, network_id, block_number, log):
        log = {**log, "blockNumber": block_number}
        self.logs.setdefault(network_id, []).append((block_number, log))
        self.hashes.setdefault((network_id, block_number), f"0xhash-{network_id}-{block_number}")

    def set_block_hash(self, network_id, block, value):
        self.hashes[(network_id, block)] = value

    def rate_limit_after(self, network_id, n_calls):
        self._rl_after[network_id] = n_calls

    async def get_head(self, network_id):
        return {"number": self.heads.get(network_id, 0)}

    async def get_logs(self, network_id, from_block, to_block):
        self._get_logs_calls[network_id] = self._get_logs_calls.get(network_id, 0) + 1
        limit = self._rl_after.get(network_id)
        if limit is not None and self._get_logs_calls[network_id] > limit:
            raise RateLimited(f"{network_id}: throttled")
        return [dict(log) for block, log in self.logs.get(network_id, []) if from_block <= block <= to_block]

    async def get_block_hash(self, network_id, block):
        return self.hashes.get((network_id, block), f"0xhash-{network_id}-{block}")


def _order_id(byte: int) -> bytes:
    return bytes([byte]) * 32


def _maker32(byte: int) -> bytes:
    return b"\x00" * 12 + bytes([byte]) * 20


def _tail() -> bytes:
    return encode_dln_order(maker_nonce=3, give_chain_id=1, give_amount=1_000_000,
                            take_chain_id=42161, take_amount=990_000, maker32=_maker32(0xBB))


def _created_log(order_id: bytes, tx: str) -> dict:
    return {"topics": [TOPIC_CREATED_ORDER],
            "data": encode_created_order_data(order_id, _tail(), native_fix_fee=1, percent_fee=2),
            "transactionHash": tx, "blockHash": "0xb", "logIndex": 0}


def _fulfilled_log(order_id: bytes, tx: str) -> dict:
    return {"topics": [TOPIC_FULFILLED_ORDER],
            "data": encode_fulfilled_order_data(order_id, _tail(), taker="0x" + "cc" * 20),
            "transactionHash": tx, "blockHash": "0xb", "logIndex": 0}


def _claimed_order_log(order_id: bytes, tx: str) -> dict:
    return {"topics": [TOPIC_CLAIMED_ORDER],
            "data": encode_claimed_order_data(order_id, beneficiary="0x" + "dd" * 20, give_amount=1_000_000),
            "transactionHash": tx, "blockHash": "0xb", "logIndex": 0}


# ── decode ───────────────────────────────────────────────────────────────────

def test_created_order_decodes_order_id_and_chain_route():
    adapter = DebridgeAdapter(chain_networks=CHAINS)
    oid = _order_id(0x33)
    obs = adapter.decode_log({**_created_log(oid, "0xo"), "network_id": ETH})
    assert obs["phase"] == "sent"
    assert obs["protocol_product"] == "intent"
    assert obs["correlation_key"] == "dbr:order:0x" + oid.hex()
    assert obs["source_network_id"] == ETH and obs["destination_network_id"] == ARB
    assert obs["provider_extension"]["give_amount"] == "1000000"


def test_fulfilled_and_claimed_order_map_to_delivered_and_settled():
    adapter = DebridgeAdapter(chain_networks=CHAINS)
    oid = _order_id(0x44)
    fulfilled = adapter.decode_log({**_fulfilled_log(oid, "0xf"), "network_id": ARB})
    claimed = adapter.decode_log({**_claimed_order_log(oid, "0xc"), "network_id": ETH})
    assert fulfilled["phase"] == "delivered"
    assert claimed["phase"] == "settled"
    assert fulfilled["correlation_key"] == claimed["correlation_key"] == "dbr:order:0x" + oid.hex()


def test_gate_sent_and_claimed_use_submission_id_key():
    adapter = DebridgeAdapter(chain_networks=CHAINS)
    sub = _order_id(0x55)
    sent = adapter.decode_log({
        "topics": [TOPIC_SENT, "0x" + (b"\x66" * 32).hex(), "0x" + (42161).to_bytes(32, "big").hex()],
        "data": encode_sent_data(sub, amount=500, nonce=1),
        "network_id": ETH, "transactionHash": "0xg", "blockHash": "0xb", "logIndex": 0})
    claimed = adapter.decode_log({
        "topics": [TOPIC_CLAIMED, "0x" + (b"\x66" * 32).hex(), "0x" + (1).to_bytes(32, "big").hex()],
        "data": encode_claimed_data(sub, amount=500, nonce=1),
        "network_id": ARB, "transactionHash": "0xg2", "blockHash": "0xb", "logIndex": 0})
    assert sent["phase"] == "sent" and sent["protocol_product"] == "messaging"
    assert sent["correlation_key"] == "dbr:sub:0x" + sub.hex()
    assert sent["destination_network_id"] == ARB
    assert claimed["phase"] == "delivered"
    assert claimed["correlation_key"] == "dbr:sub:0x" + sub.hex()


# ── lifecycle / correlation ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dln_full_lifecycle_created_fulfilled_claimed_settles():
    server = MockEvmRpcServer()
    oid = _order_id(0x77)
    server.set_head(ETH, 200)
    server.set_head(ARB, 200)
    server.add_log(ETH, 50, _created_log(oid, "0xc1"))
    server.add_log(ARB, 60, _fulfilled_log(oid, "0xf1"))
    server.add_log(ETH, 70, _claimed_order_log(oid, "0xk1"))

    adapter = DebridgeAdapter(rpc_client=server, chain_networks=CHAINS, confirmations=0)
    observations, _ = await adapter.scan()
    engine = CorrelationEngine()
    for obs in sorted(observations, key=lambda o: {"sent": 0, "delivered": 1, "settled": 2}[o["phase"]]):
        await engine.ingest_observation(PUBLIC_TENANT, obs)

    message = await engine.messages.find_one(
        {"tenant_id": PUBLIC_TENANT, "provider_kind": "debridge", "correlation_key": "dbr:order:0x" + oid.hex()})
    assert message["status"] == "settled"
    assert message["technical_outcome"] == "success"
    assert message["source"]["network_id"] == ETH
    assert message["destination"]["network_id"] == ARB


@pytest.mark.asyncio
async def test_out_of_order_fulfilled_before_created_correlates():
    adapter = DebridgeAdapter(chain_networks=CHAINS)
    oid = _order_id(0x88)
    fulfilled = adapter.decode_log({**_fulfilled_log(oid, "0xf"), "network_id": ARB})
    created = adapter.decode_log({**_created_log(oid, "0xc"), "network_id": ETH})
    engine = CorrelationEngine()
    first = await engine.ingest_observation(PUBLIC_TENANT, fulfilled)
    assert first["out_of_order"] is True
    second = await engine.ingest_observation(PUBLIC_TENANT, created)
    assert "interop_message_correlated" in [e["event_name"] for e in second["emitted_events"]]


# ── resilience ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restart_resume_idempotent():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 40, _created_log(_order_id(0x01), "0xa"))
    adapter = DebridgeAdapter(rpc_client=server, chain_networks=CHAINS, confirmations=0)
    first, checkpoint = await adapter.scan()
    assert len(first) == 1
    second, checkpoint = await adapter.scan(checkpoint)
    assert second == []


@pytest.mark.asyncio
async def test_reorg_rewinds_on_hash_mismatch():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 90, _created_log(_order_id(0x02), "0xa"))
    adapter = DebridgeAdapter(rpc_client=server, chain_networks=CHAINS, confirmations=0)
    _, checkpoint = await adapter.scan()
    last = checkpoint["networks"][ETH]["last_scanned_block"]
    server.set_block_hash(ETH, last, "0xREORG")
    server.set_head(ETH, 130)
    observations, checkpoint = await adapter.scan(checkpoint)
    assert any(o["phase"] == "reorged" and o["network_id"] == ETH for o in observations)
    assert checkpoint["networks"][ETH]["last_scanned_block"] < last


@pytest.mark.asyncio
async def test_rate_limit_partial_then_resume():
    server = MockEvmRpcServer()
    server.set_head(ETH, 40)
    server.set_head(ARB, 0)
    for block in range(1, 31):
        server.add_log(ETH, block, _created_log(_order_id(block), f"0x{block:x}"))
    adapter = DebridgeAdapter(rpc_client=server, chain_networks=CHAINS, confirmations=0, max_block_span=5)
    server.rate_limit_after(ETH, 1)
    partial, checkpoint = await adapter.scan()
    assert 0 < checkpoint["networks"][ETH]["last_scanned_block"] < 40
    server._rl_after.pop(ETH, None)
    rest, checkpoint = await adapter.scan(checkpoint)
    assert checkpoint["networks"][ETH]["last_scanned_block"] == 40
    assert len(partial) + len(rest) == 30


# ── status / guard / certification / security ────────────────────────────────

def test_status_is_credential_gated():
    assert DebridgeAdapter().implementation_status == ImplementationStatus.CREDENTIAL_GATED


@pytest.mark.asyncio
async def test_unwired_client_raises():
    with pytest.raises(NotImplementedError):
        await DebridgeAdapter(rpc_client=None).scan()


def test_certification_descriptor_credential_waiting():
    descriptor = DebridgeAdapter().certification_descriptor()
    assert descriptor.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
    assert descriptor.provider == "debridge"
    assert DebridgeAdapter().descriptor()["execution_by_aether"] is False


def test_security_model_is_external_validator_set_not_light_client():
    model = DebridgeAdapter().security_model()
    assert model["verification_model"] == "external_validator_set"
    assert model["attestation_on_chain"] is False
    assert model["verification_model"] != "light_client"
