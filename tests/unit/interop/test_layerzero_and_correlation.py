"""LayerZero decode + GUID correlation + out-of-order assembly + reorg
rollback + scan checkpointing against the injectable fixture RPC."""

from __future__ import annotations

from repositories.interop_repos import InteropMessageEventRepo, InteropMessageRepo
from services.interop.correlation import CorrelationEngine
from services.interop.providers.layerzero_v2 import LayerZeroV2Adapter

from tests.unit.interop.lz_fixtures import (
    DST_EID,
    FixtureRpcClient,
    GUID,
    MESSAGE_HASH,
    NONCE,
    SEND_LIBRARY,
    packet_delivered_log,
    packet_sent_log,
    packet_verified_log,
)

TENANT = "t-interop"


def _adapter(rpc=None) -> LayerZeroV2Adapter:
    return LayerZeroV2Adapter(rpc_client=rpc)


# ── Decode ───────────────────────────────────────────────────────────────────

def test_packet_sent_decodes_to_canonical_observation():
    observation = _adapter().decode_log(packet_sent_log())
    assert observation is not None
    assert observation["phase"] == "sent"
    assert observation["correlation_key"] == f"lz2:{GUID}"
    assert observation["sequence"] == str(NONCE)
    assert observation["payload_hash"] == MESSAGE_HASH
    assert observation["source_network_id"] == "ethereum-mainnet"
    assert observation["destination_network_id"] == "arbitrum-mainnet"
    assert observation["provider_extension"]["send_library"] == SEND_LIBRARY
    aliases = {r["alias_type"]: r["alias_value"] for r in observation["provider_message_refs"]}
    assert aliases["guid"] == GUID


def test_verified_and_delivered_recompute_the_same_guid():
    verified = _adapter().decode_log(packet_verified_log())
    delivered = _adapter().decode_log(packet_delivered_log())
    assert verified["correlation_key"] == f"lz2:{GUID}"
    assert delivered["correlation_key"] == f"lz2:{GUID}"
    assert verified["phase"] == "verified"
    assert verified["payload_hash"] == MESSAGE_HASH
    assert delivered["phase"] == "delivered"
    assert delivered["endpoint_ref"]["network_id"] == "arbitrum-mainnet"


def test_unknown_topics_are_ignored():
    log = packet_sent_log()
    log["topics"] = ["0x" + "00" * 32]
    assert _adapter().decode_log(log) is None


# ── Correlation ──────────────────────────────────────────────────────────────

async def test_in_order_correlation_full_lifecycle():
    engine = CorrelationEngine()
    adapter = _adapter()
    sent = await engine.ingest_observation(TENANT, adapter.decode_log(packet_sent_log()))
    assert sent["accepted"] and sent["status"] == "source_confirmed"

    verified = await engine.ingest_observation(TENANT, adapter.decode_log(packet_verified_log()))
    assert verified["status"] == "verified"

    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(packet_delivered_log()))
    assert delivered["status"] == "delivered"
    correlated = [
        e for e in delivered["emitted_events"]
        if e["event_name"] == "interop_message_correlated"
    ]
    assert len(correlated) == 1  # exactly once, when both legs first present

    message = await InteropMessageRepo().find_one({
        "tenant_id": TENANT, "correlation_key": f"lz2:{GUID}",
    })
    assert message["source"]["network_id"] == "ethereum-mainnet"
    assert message["destination"]["network_id"] == "arbitrum-mainnet"

    transitions = await InteropMessageEventRepo().find_many(
        {"tenant_id": TENANT}, limit=10, order_by="observed_at", descending=False,
    )
    assert [t["to_status"] for t in transitions] == [
        "source_confirmed", "verified", "delivered",
    ]


async def test_out_of_order_delivery_first_then_source():
    engine = CorrelationEngine()
    adapter = _adapter()

    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(packet_delivered_log()))
    assert delivered["accepted"]
    assert delivered["out_of_order"] is True

    message = await InteropMessageRepo().find_one({
        "tenant_id": TENANT, "correlation_key": f"lz2:{GUID}",
    })
    assert message["status"] == "delivered"
    assert message["provider_extension"]["discovered_out_of_order"] is True
    assert not message.get("source")

    # Source leg arrives late: fills the source ref, does NOT regress status,
    # and fires interop_message_correlated exactly once.
    sent = await engine.ingest_observation(TENANT, adapter.decode_log(packet_sent_log()))
    assert sent["status"] == "delivered"  # no regression
    assert sent["lifecycle_reason"] == "late_evidence_attached"
    correlated = [
        e for e in sent["emitted_events"]
        if e["event_name"] == "interop_message_correlated"
    ]
    assert len(correlated) == 1

    message = await InteropMessageRepo().find_one({
        "tenant_id": TENANT, "correlation_key": f"lz2:{GUID}",
    })
    assert message["source"]["network_id"] == "ethereum-mainnet"


async def test_replayed_observation_is_idempotent():
    engine = CorrelationEngine()
    adapter = _adapter()
    await engine.ingest_observation(TENANT, adapter.decode_log(packet_sent_log()))
    replay = await engine.ingest_observation(TENANT, adapter.decode_log(packet_sent_log()))
    assert replay["accepted"]
    assert replay["lifecycle_reason"] == "duplicate_evidence"
    assert await InteropMessageRepo().count({"tenant_id": TENANT}) == 1


# ── Reorg ────────────────────────────────────────────────────────────────────

async def test_reorg_demotes_non_terminal_messages_only():
    engine = CorrelationEngine()
    adapter = _adapter()
    await engine.ingest_observation(TENANT, adapter.decode_log(packet_sent_log(block_number=120)))

    # Settle a second message on the same network, below the fork block.
    other = adapter.decode_log(packet_sent_log(block_number=50, log_index=9))
    other["correlation_key"] = "lz2:0xother"
    await engine.ingest_observation(TENANT, other)
    await engine.ingest_observation(TENANT, {
        **other, "phase": "delivered",
        "endpoint_ref": {"network_id": "arbitrum-mainnet", "block_number": "60"},
    })
    await engine.ingest_observation(TENANT, {**other, "phase": "settled"})

    result = await engine.ingest_observation(TENANT, {
        "phase": "reorged", "network_id": "ethereum-mainnet", "from_block": 100,
    })
    assert result["reorg_affected"] == 1

    reorged = await InteropMessageRepo().find_one({
        "tenant_id": TENANT, "correlation_key": f"lz2:{GUID}",
    })
    assert reorged["status"] == "reorged"
    settled = await InteropMessageRepo().find_one({
        "tenant_id": TENANT, "correlation_key": "lz2:0xother",
    })
    assert settled["status"] == "settled"  # terminal messages untouched


# ── Scan / checkpoint ────────────────────────────────────────────────────────

async def test_scan_respects_confirmation_horizon_and_checkpoints():
    rpc = FixtureRpcClient()
    rpc.heads["ethereum-mainnet"] = 140   # safe head = 125 with 15 confirmations
    rpc.logs["ethereum-mainnet"] = [packet_sent_log(block_number=120)]
    adapter = LayerZeroV2Adapter(
        rpc_client=rpc,
        eid_networks={30101: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    observations, checkpoint = await adapter.scan(None)
    assert len(observations) == 1
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] == 125

    # Idempotent: nothing new below the safe head on re-scan.
    again, checkpoint2 = await adapter.scan(checkpoint)
    assert again == []
    assert checkpoint2["networks"]["ethereum-mainnet"]["last_scanned_block"] == 125


async def test_scan_detects_reorg_by_block_hash_mismatch():
    rpc = FixtureRpcClient()
    rpc.heads["ethereum-mainnet"] = 140
    rpc.logs["ethereum-mainnet"] = [packet_sent_log(block_number=120)]
    rpc.block_hashes[("ethereum-mainnet", 125)] = "0xoriginal"
    adapter = LayerZeroV2Adapter(
        rpc_client=rpc,
        eid_networks={30101: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    _, checkpoint = await adapter.scan(None)

    # Chain rewrites block 125.
    rpc.block_hashes[("ethereum-mainnet", 125)] = "0xforked"
    observations, checkpoint = await adapter.scan(checkpoint)
    assert any(o.get("phase") == "reorged" for o in observations)
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] < 125


async def test_scan_without_rpc_is_honestly_credential_gated():
    import pytest

    with pytest.raises(NotImplementedError):
        await LayerZeroV2Adapter(rpc_client=None).scan(None)
