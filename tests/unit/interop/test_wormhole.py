"""Wormhole adapter: real decode, guardian-VAA attestation, GUID correlation,
out-of-order join, checkpoint restart, rate-limit resume, reorg/cursor rewind,
and honest credential-gating — all against in-process mock RPC/guardian servers.
"""

from __future__ import annotations

import pytest

from repositories.interop_repos import InteropMessageEventRepo, InteropMessageRepo
from services.interop.correlation import CorrelationEngine
from services.interop.providers.wormhole import (
    WormholeAdapter,
    decode_vaa,
    vaa_correlation_key,
)
from shared.certification.checks import run_certification
from shared.certification.readiness import CredentialReadiness

from tests.unit.interop.wh_fixtures import (
    DST_CHAIN,
    EMITTER_TOPIC,
    KEY,
    SEQUENCE,
    SRC_CHAIN,
    MockGuardianApi,
    MockWormholeRpc,
    log_message_published,
    signed_vaa,
    transfer_redeemed,
)

TENANT = "t-wh"


def _adapter(rpc=None, guardian=None) -> WormholeAdapter:
    return WormholeAdapter(rpc_client=rpc, guardian_client=guardian)


# ── decode ───────────────────────────────────────────────────────────────────

def test_log_message_published_decodes_to_source_observation():
    obs = _adapter().decode_log(log_message_published())
    assert obs is not None
    assert obs["phase"] == "sent"
    assert obs["correlation_key"] == KEY
    assert obs["sequence"] == str(SEQUENCE)
    assert obs["source_network_id"] == "ethereum-mainnet"
    aliases = {r["alias_type"]: r["alias_value"] for r in obs["provider_message_refs"]}
    assert aliases["vaa_id"] == KEY
    assert obs["provider_extension"]["consistency_level"] == 200


def test_vaa_and_transfer_redeemed_share_the_source_key():
    verified = _adapter().decode_attestation(signed_vaa(signature_count=13))
    delivered = _adapter().decode_log(transfer_redeemed())
    assert verified["correlation_key"] == KEY
    assert delivered["correlation_key"] == KEY
    assert verified["phase"] == "verified"
    assert verified["provider_extension"]["quorum_reached"] is True
    assert delivered["phase"] == "delivered"
    assert delivered["destination_network_id"] == "arbitrum-mainnet"


def test_vaa_below_quorum_is_reported_honestly():
    obs = _adapter().decode_attestation(signed_vaa(signature_count=12))
    assert obs["provider_extension"]["quorum_reached"] is False
    assert obs["provider_extension"]["quorum_required"] == 13


def test_vaa_hash_is_double_keccak_and_identity_matches():
    vaa = decode_vaa(signed_vaa())
    assert vaa["emitter_chain"] == SRC_CHAIN and vaa["sequence"] == SEQUENCE
    assert vaa_correlation_key(vaa["emitter_chain"], vaa["emitter_address"], vaa["sequence"]) == KEY


def test_unknown_topic_ignored():
    log = log_message_published()
    log["topics"] = ["0x" + "00" * 32]
    assert _adapter().decode_log(log) is None


# ── correlation (source -> verified -> delivered) ─────────────────────────────

async def test_full_lifecycle_correlation_in_order():
    engine = CorrelationEngine()
    adapter = _adapter()
    sent = await engine.ingest_observation(TENANT, adapter.decode_log(log_message_published()))
    assert sent["status"] == "source_confirmed"

    verified = await engine.ingest_observation(
        TENANT, adapter.decode_attestation(signed_vaa(), observed_at="2026-07-10T00:01:00+00:00"),
    )
    assert verified["status"] == "verified"

    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(transfer_redeemed()))
    assert delivered["status"] == "delivered"
    correlated = [e for e in delivered["emitted_events"] if e["event_name"] == "interop_message_correlated"]
    assert len(correlated) == 1

    message = await InteropMessageRepo().find_one({"tenant_id": TENANT, "correlation_key": KEY})
    assert message["source"]["network_id"] == "ethereum-mainnet"
    assert message["destination"]["network_id"] == "arbitrum-mainnet"
    transitions = await InteropMessageEventRepo().find_many(
        {"tenant_id": TENANT}, limit=10, order_by="observed_at", descending=False,
    )
    assert [t["to_status"] for t in transitions] == ["source_confirmed", "verified", "delivered"]


async def test_out_of_order_delivery_then_source():
    engine = CorrelationEngine()
    adapter = _adapter()
    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(transfer_redeemed()))
    assert delivered["out_of_order"] is True

    sent = await engine.ingest_observation(TENANT, adapter.decode_log(log_message_published()))
    assert sent["status"] == "delivered"  # no regression
    assert sent["lifecycle_reason"] == "late_evidence_attached"
    correlated = [e for e in sent["emitted_events"] if e["event_name"] == "interop_message_correlated"]
    assert len(correlated) == 1


# ── scan / checkpoint / rate limit / reorg ────────────────────────────────────

async def test_scan_checkpoints_and_fetches_vaa_via_guardian():
    rpc = MockWormholeRpc()
    guardian = MockGuardianApi()
    guardian.publish(SRC_CHAIN, EMITTER_TOPIC, SEQUENCE, signed_vaa())
    rpc.heads["ethereum-mainnet"] = {"number": 120, "hash": "0xhead"}
    rpc.logs["ethereum-mainnet"] = [log_message_published(block_number=100)]

    adapter = WormholeAdapter(
        rpc_client=rpc, guardian_client=guardian,
        wormhole_chains={SRC_CHAIN: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    observations, checkpoint = await adapter.scan(None)
    phases = sorted(o["phase"] for o in observations)
    assert phases == ["sent", "verified"]           # source + guardian attestation
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] == 105  # 120 - 15

    again, checkpoint2 = await adapter.scan(checkpoint)
    assert again == []                              # idempotent below the safe head


async def test_scan_without_guardian_client_skips_attestation_honestly():
    rpc = MockWormholeRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.logs["ethereum-mainnet"] = [log_message_published(block_number=100)]
    adapter = WormholeAdapter(
        rpc_client=rpc,
        wormhole_chains={SRC_CHAIN: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    observations, checkpoint = await adapter.scan(None)
    assert [o["phase"] for o in observations] == ["sent"]
    assert any(h["state"] == "attestation_unconfigured" for h in checkpoint["health"])


async def test_scan_rate_limit_resumes_from_checkpoint():
    rpc = MockWormholeRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.logs["ethereum-mainnet"] = [log_message_published(block_number=100)]
    rpc.fail_get_logs_once.add("ethereum-mainnet")
    adapter = WormholeAdapter(
        rpc_client=rpc,
        wormhole_chains={SRC_CHAIN: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    observations, checkpoint = await adapter.scan(None)
    assert observations == []                        # first window rate-limited
    assert any(h["state"] == "rate_limited" and h["retry_after"] == 2 for h in checkpoint["health"])
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] == 0

    observations2, checkpoint2 = await adapter.scan(checkpoint)   # resume
    assert [o["phase"] for o in observations2] == ["sent"]
    assert checkpoint2["networks"]["ethereum-mainnet"]["last_scanned_block"] == 105


async def test_scan_detects_block_hash_reorg_and_rewinds():
    rpc = MockWormholeRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.logs["ethereum-mainnet"] = [log_message_published(block_number=100)]
    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xoriginal"
    adapter = WormholeAdapter(
        rpc_client=rpc,
        wormhole_chains={SRC_CHAIN: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    _, checkpoint = await adapter.scan(None)
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] == 105

    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xforked"      # chain rewrote 105
    observations, checkpoint = await adapter.scan(checkpoint)
    reorged = [o for o in observations if o["phase"] == "reorged"]
    assert reorged and reorged[0]["discontinuity_kind"] == "block_hash"
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] < 105


async def test_scan_detects_cursor_drift_when_checkpoint_ahead_of_head():
    rpc = MockWormholeRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 40}     # chain rolled back under us
    adapter = WormholeAdapter(
        rpc_client=rpc,
        wormhole_chains={SRC_CHAIN: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    checkpoint = {"networks": {"ethereum-mainnet": {"last_scanned_block": 105, "recent_hashes": {}}}}
    observations, checkpoint = await adapter.scan(checkpoint)
    drift = [o for o in observations if o.get("discontinuity_kind") == "cursor_drift"]
    assert drift and drift[0]["phase"] == "reorged"
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] <= 25


async def test_scan_detects_parent_hash_discontinuity():
    rpc = MockWormholeRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 200}
    rpc.logs["ethereum-mainnet"] = [log_message_published(block_number=100)]
    adapter = WormholeAdapter(
        rpc_client=rpc, confirmations=15,
        wormhole_chains={SRC_CHAIN: {"network_id": "ethereum-mainnet", "native_chain_id": "1"}},
    )
    _, checkpoint = await adapter.scan(None)
    last = checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"]
    # Next block's parentHash does NOT chain back to our recorded hash for `last`.
    rpc.blocks[("ethereum-mainnet", last + 1)] = {"number": last + 1, "parentHash": "0xbroken"}
    observations, checkpoint = await adapter.scan(checkpoint)
    disc = [o for o in observations if o.get("discontinuity_kind") == "parent_hash"]
    assert disc and disc[0]["phase"] == "reorged"


async def test_scan_without_rpc_is_credential_gated():
    with pytest.raises(NotImplementedError):
        await WormholeAdapter(rpc_client=None).scan(None)


# ── certification / health ────────────────────────────────────────────────────

def test_certification_descriptor_is_honest_and_passes_checks():
    adapter = _adapter()
    descriptor = adapter.certification_descriptor()
    assert descriptor.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
    assert "relay" in descriptor.unsupported_operations
    results = run_certification(adapter, ctx={"sample_request": {}})
    failures = [r for r in results if not r.passed]
    assert failures == [], [(r.name, r.detail) for r in failures]


def test_health_reflects_configuration():
    assert _adapter().health({"configured": False})["healthy"] is False
    assert _adapter(rpc=MockWormholeRpc()).health()["healthy"] is True


def test_security_policy_snapshot_is_guardian_multisig():
    policy = _adapter().snapshot_security_policy("wormhole:ethereum-mainnet->arbitrum-mainnet")
    assert policy["verification_model"] == "guardian_multisig_supermajority"
    assert policy["optional_threshold"] == 13
