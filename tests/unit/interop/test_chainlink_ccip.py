"""Chainlink CCIP adapter: real OnRamp/CommitStore/OffRamp decode, interval-
commit expansion (DON+RMN verification), messageId correlation, retry/failure
classification, out-of-order join, checkpoint restart, rate-limit resume,
reorg/cursor rewind, and credential-gating.
"""

from __future__ import annotations

import pytest

from repositories.interop_repos import InteropMessageEventRepo, InteropMessageRepo
from services.interop.correlation import CorrelationEngine
from services.interop.providers.chainlink_ccip import ChainlinkCcipAdapter
from shared.certification.checks import run_certification
from shared.certification.readiness import CredentialReadiness

from tests.unit.interop.ccip_fixtures import (
    KEY,
    MESSAGE_ID,
    SEQUENCE,
    SRC_SELECTOR,
    MockCcipRpc,
    ccip_send_requested,
    execution_state_changed,
    report_accepted,
)

TENANT = "t-ccip"


def _adapter(rpc=None) -> ChainlinkCcipAdapter:
    return ChainlinkCcipAdapter(rpc_client=rpc)


def _seq_index() -> dict[str, str]:
    return {f"{SRC_SELECTOR}:{SEQUENCE}": KEY}


# ── decode ───────────────────────────────────────────────────────────────────

def test_ccip_send_requested_decodes_message_id_and_sequence():
    obs = _adapter().decode_log(ccip_send_requested())
    assert obs["phase"] == "sent"
    assert obs["correlation_key"] == KEY
    assert obs["sequence"] == str(SEQUENCE)
    assert obs["source_network_id"] == "ethereum-mainnet"
    assert obs["destination_network_id"] == "arbitrum-mainnet"
    ext = obs["provider_extension"]
    assert ext["source_chain_selector"] == SRC_SELECTOR


def test_commit_interval_expands_to_verified_for_covered_sequence():
    interval = _adapter().decode_log(report_accepted(min_seq=90, max_seq=110))
    assert interval["phase"] == "verified_interval"
    verified = _adapter().expand_commit(interval, _seq_index())
    assert len(verified) == 1
    assert verified[0]["phase"] == "verified"
    assert verified[0]["correlation_key"] == KEY
    assert verified[0]["provider_extension"]["verification_model"] == "committing_don_plus_rmn_blessing"


def test_commit_interval_not_covering_sequence_yields_nothing():
    interval = _adapter().decode_log(report_accepted(min_seq=200, max_seq=210))
    assert _adapter().expand_commit(interval, _seq_index()) == []


def test_execution_state_success_failure_and_in_progress():
    delivered = _adapter().decode_log(execution_state_changed(state=2))
    assert delivered["phase"] == "delivered" and delivered["correlation_key"] == KEY

    failed = _adapter().decode_log(execution_state_changed(state=3, return_data=b"revert"))
    assert failed["phase"] == "failed"
    assert failed["provider_extension"]["execution_state"] == "FAILURE"

    attempt = _adapter().decode_log(execution_state_changed(state=1))
    assert attempt["phase"] == "delivery_attempted"
    assert attempt["lifecycle_phase"] is False


def test_retries_are_counted_before_success():
    adapter = _adapter()
    logs = [
        execution_state_changed(state=1, block_number=56, log_index=0),
        execution_state_changed(state=1, block_number=57, log_index=0),
        execution_state_changed(state=2, block_number=58, log_index=0),
    ]
    decoded = [adapter.decode_log(x) for x in logs]
    attempts = [d for d in decoded if d["phase"] == "delivery_attempted"]
    delivered = [d for d in decoded if d["phase"] == "delivered"]
    assert len(attempts) == 2 and len(delivered) == 1


def test_unknown_topic_ignored():
    log = ccip_send_requested()
    log["topics"] = ["0x" + "00" * 32]
    assert _adapter().decode_log(log) is None


# ── correlation ──────────────────────────────────────────────────────────────

async def test_full_lifecycle_in_order():
    engine = CorrelationEngine()
    adapter = _adapter()
    sent = await engine.ingest_observation(TENANT, adapter.decode_log(ccip_send_requested()))
    assert sent["status"] == "source_confirmed"

    interval = adapter.decode_log(report_accepted())
    verified_obs = adapter.expand_commit(interval, _seq_index())[0]
    verified = await engine.ingest_observation(TENANT, verified_obs)
    assert verified["status"] == "verified"

    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(execution_state_changed(state=2)))
    assert delivered["status"] == "delivered"
    correlated = [e for e in delivered["emitted_events"] if e["event_name"] == "interop_message_correlated"]
    assert len(correlated) == 1

    transitions = await InteropMessageEventRepo().find_many(
        {"tenant_id": TENANT}, limit=10, order_by="observed_at", descending=False,
    )
    assert [t["to_status"] for t in transitions] == ["source_confirmed", "verified", "delivered"]


async def test_out_of_order_delivery_before_source():
    engine = CorrelationEngine()
    adapter = _adapter()
    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(execution_state_changed(state=2)))
    assert delivered["out_of_order"] is True

    sent = await engine.ingest_observation(TENANT, adapter.decode_log(ccip_send_requested()))
    assert sent["status"] == "delivered"
    assert sent["lifecycle_reason"] == "late_evidence_attached"
    message = await InteropMessageRepo().find_one({"tenant_id": TENANT, "correlation_key": KEY})
    assert message["source"] and message["destination"]


# ── scan / checkpoint / rate limit / reorg ────────────────────────────────────

def _lane_adapter(rpc) -> ChainlinkCcipAdapter:
    return ChainlinkCcipAdapter(
        rpc_client=rpc,
        selectors={
            SRC_SELECTOR: {"network_id": "ethereum-mainnet", "native_chain_id": "1"},
            4949039107694359620: {"network_id": "arbitrum-mainnet", "native_chain_id": "42161"},
        },
    )


async def test_scan_expands_commit_against_source_sequence_index():
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 90}
    rpc.logs["ethereum-mainnet"] = [ccip_send_requested(block_number=100)]
    rpc.logs["arbitrum-mainnet"] = [
        report_accepted(block_number=55),
        execution_state_changed(state=2, block_number=56),
    ]
    adapter = _lane_adapter(rpc)
    observations, checkpoint = await adapter.scan(None)

    phases = {o["phase"] for o in observations}
    assert {"sent", "verified", "delivered"} <= phases
    verified = [o for o in observations if o["phase"] == "verified"]
    assert verified and verified[0]["correlation_key"] == KEY
    assert checkpoint["seq_index"][f"{SRC_SELECTOR}:{SEQUENCE}"] == KEY


async def test_scan_rate_limit_resumes():
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    rpc.logs["ethereum-mainnet"] = [ccip_send_requested(block_number=100)]
    rpc.fail_get_logs_once.add("ethereum-mainnet")
    adapter = _lane_adapter(rpc)

    observations, checkpoint = await adapter.scan(None)
    assert observations == []
    assert any(h["state"] == "rate_limited" and h["retry_after"] == 5 for h in checkpoint["health"])

    observations2, checkpoint2 = await adapter.scan(checkpoint)
    assert any(o["phase"] == "sent" for o in observations2)
    assert checkpoint2["networks"]["ethereum-mainnet"]["last_scanned_block"] == 105


async def test_scan_reorg_rewind():
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    rpc.logs["ethereum-mainnet"] = [ccip_send_requested(block_number=100)]
    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xorig"
    adapter = _lane_adapter(rpc)
    _, checkpoint = await adapter.scan(None)

    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xforked"
    observations, checkpoint = await adapter.scan(checkpoint)
    reorged = [o for o in observations if o["phase"] == "reorged"]
    assert reorged and reorged[0]["discontinuity_kind"] == "block_hash"
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] < 105


async def test_scan_cursor_drift_rewind():
    rpc = MockCcipRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 30}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    adapter = _lane_adapter(rpc)
    checkpoint = {"networks": {"ethereum-mainnet": {"last_scanned_block": 105, "recent_hashes": {}}}}
    observations, checkpoint = await adapter.scan(checkpoint)
    drift = [o for o in observations if o.get("discontinuity_kind") == "cursor_drift"]
    assert drift and drift[0]["phase"] == "reorged"


async def test_scan_without_rpc_is_credential_gated():
    with pytest.raises(NotImplementedError):
        await ChainlinkCcipAdapter(rpc_client=None).scan(None)


# ── certification / health ────────────────────────────────────────────────────

def test_certification_descriptor_is_honest_and_passes_checks():
    adapter = _adapter()
    descriptor = adapter.certification_descriptor()
    assert descriptor.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
    assert "manual_execution" in descriptor.unsupported_operations
    results = run_certification(adapter, ctx={"sample_request": {}})
    failures = [r for r in results if not r.passed]
    assert failures == [], [(r.name, r.detail) for r in failures]


def test_security_policy_is_don_plus_rmn():
    policy = _adapter().snapshot_security_policy("ccip:ethereum-mainnet->arbitrum-mainnet")
    assert policy["verification_model"] == "committing_don_plus_rmn_blessing"
    assert policy["optional_verifier_ids"]  # RMN blessing layer present


def test_health_reflects_configuration():
    assert _adapter().health({"configured": False})["healthy"] is False
    assert _adapter(rpc=MockCcipRpc()).health()["healthy"] is True
