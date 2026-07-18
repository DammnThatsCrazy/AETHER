"""Axelar adapter: real gateway decode, GMP-message-id correlation, validator-
confirmation attestation, commandId-bound execution, out-of-order join,
checkpoint restart, rate-limit resume, reorg/cursor rewind, credential-gating.
"""

from __future__ import annotations

import pytest

from repositories.interop_repos import InteropMessageEventRepo, InteropMessageRepo
from services.interop.correlation import CorrelationEngine
from services.interop.providers.axelar import AxelarAdapter
from shared.certification.checks import run_certification
from shared.certification.readiness import CredentialReadiness

from tests.unit.interop.ax_fixtures import (
    COMMAND_ID,
    KEY,
    MockAxelarConfirmations,
    MockAxelarRpc,
    confirmation_record,
    contract_call,
    contract_call_approved,
    contract_call_executed,
    contract_call_with_token,
)

TENANT = "t-ax"


def _adapter(rpc=None, confirmations=None) -> AxelarAdapter:
    return AxelarAdapter(rpc_client=rpc, confirmation_client=confirmations)


# ── decode ───────────────────────────────────────────────────────────────────

def test_contract_call_decodes_to_source_observation():
    obs = _adapter().decode_log(contract_call())
    assert obs["phase"] == "sent"
    assert obs["correlation_key"] == KEY
    assert obs["source_network_id"] == "ethereum-mainnet"
    assert obs["destination_network_id"] == "arbitrum-mainnet"
    aliases = {r["alias_type"]: r["alias_value"] for r in obs["provider_message_refs"]}
    assert aliases["message_id"] == KEY


def test_contract_call_with_token_carries_asset_leg():
    obs = _adapter().decode_log(contract_call_with_token(symbol="USDC", amount=2_500_000))
    assert obs["phase"] == "sent"
    leg = obs["provider_extension"]["asset_leg"]
    assert leg["symbol"] == "USDC" and leg["amount_atomic"] == "2500000"


def test_contract_call_approved_reconstructs_source_key():
    obs = _adapter().decode_log(contract_call_approved())
    assert obs["phase"] == "delivered"
    assert obs["correlation_key"] == KEY            # same GMP id as the source leg
    assert obs["provider_extension"]["command_id"] == COMMAND_ID


def test_executed_binds_command_id_to_message_id():
    log = contract_call_executed()
    log["command_bindings"] = {COMMAND_ID: KEY}
    obs = _adapter().decode_log(log)
    assert obs["phase"] == "executed"
    assert obs["correlation_key"] == KEY
    assert obs["provider_extension"]["unbound_execution"] is False


def test_executed_without_binding_is_flagged_unbound():
    obs = _adapter().decode_log(contract_call_executed())
    assert obs["phase"] == "executed"
    assert obs["correlation_key"] == f"axl:cmd/{COMMAND_ID}"
    assert obs["provider_extension"]["unbound_execution"] is True


def test_confirmation_only_verifies_when_confirmed():
    adapter = _adapter()
    assert adapter.decode_confirmation(confirmation_record(confirmed=False), KEY) is None
    verified = adapter.decode_confirmation(confirmation_record(True), KEY)
    assert verified["phase"] == "verified" and verified["correlation_key"] == KEY
    assert verified["provider_extension"]["participant_count"] == 3


# ── correlation ──────────────────────────────────────────────────────────────

async def test_full_lifecycle_in_order():
    engine = CorrelationEngine()
    adapter = _adapter()
    sent = await engine.ingest_observation(TENANT, adapter.decode_log(contract_call()))
    assert sent["status"] == "source_confirmed"

    verified = await engine.ingest_observation(
        TENANT, adapter.decode_confirmation(confirmation_record(), KEY,
                                            observed_at="2026-07-11T00:01:00+00:00"),
    )
    assert verified["status"] == "verified"

    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(contract_call_approved()))
    assert delivered["status"] == "delivered"

    exec_log = contract_call_executed()
    exec_log["command_bindings"] = {COMMAND_ID: KEY}
    executed = await engine.ingest_observation(TENANT, adapter.decode_log(exec_log))
    assert executed["status"] == "executed"

    transitions = await InteropMessageEventRepo().find_many(
        {"tenant_id": TENANT}, limit=10, order_by="observed_at", descending=False,
    )
    assert [t["to_status"] for t in transitions] == [
        "source_confirmed", "verified", "delivered", "executed",
    ]
    correlated = [e for e in delivered["emitted_events"] if e["event_name"] == "interop_message_correlated"]
    assert len(correlated) == 1


async def test_out_of_order_approved_before_source():
    engine = CorrelationEngine()
    adapter = _adapter()
    delivered = await engine.ingest_observation(TENANT, adapter.decode_log(contract_call_approved()))
    assert delivered["out_of_order"] is True

    sent = await engine.ingest_observation(TENANT, adapter.decode_log(contract_call()))
    assert sent["status"] == "delivered"
    assert sent["lifecycle_reason"] == "late_evidence_attached"
    message = await InteropMessageRepo().find_one({"tenant_id": TENANT, "correlation_key": KEY})
    assert message["source"]["network_id"] == "ethereum-mainnet"
    assert message["destination"]["network_id"] == "arbitrum-mainnet"


# ── scan / checkpoint / rate limit / reorg ────────────────────────────────────

def _lane_adapter(rpc, confirmations=None) -> AxelarAdapter:
    return AxelarAdapter(
        rpc_client=rpc, confirmation_client=confirmations,
        axelar_chains={
            "ethereum-mainnet": {"axelar_chain": "Ethereum", "native_chain_id": "1"},
            "arbitrum-mainnet": {"axelar_chain": "arbitrum", "native_chain_id": "42161"},
        },
    )


async def test_scan_binds_command_and_fetches_confirmation():
    rpc = MockAxelarRpc()
    confirmations = MockAxelarConfirmations()
    confirmations.publish(KEY, confirmation_record())
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 90}
    rpc.logs["ethereum-mainnet"] = [contract_call(block_number=100)]
    rpc.logs["arbitrum-mainnet"] = [
        contract_call_approved(block_number=60),
        contract_call_executed(block_number=61),
    ]
    adapter = _lane_adapter(rpc, confirmations)
    observations, checkpoint = await adapter.scan(None)

    by_phase = {o["phase"] for o in observations}
    assert {"sent", "verified", "delivered", "executed"} <= by_phase
    executed = [o for o in observations if o["phase"] == "executed"][0]
    assert executed["correlation_key"] == KEY            # commandId bound during scan
    assert checkpoint["command_bindings"][COMMAND_ID] == KEY


async def test_scan_rate_limit_resumes():
    rpc = MockAxelarRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    rpc.logs["ethereum-mainnet"] = [contract_call(block_number=100)]
    rpc.fail_get_logs_once.add("ethereum-mainnet")
    adapter = _lane_adapter(rpc)

    observations, checkpoint = await adapter.scan(None)
    assert observations == []
    assert any(h["state"] == "rate_limited" for h in checkpoint["health"])

    observations2, checkpoint2 = await adapter.scan(checkpoint)
    assert any(o["phase"] == "sent" for o in observations2)
    assert checkpoint2["networks"]["ethereum-mainnet"]["last_scanned_block"] == 105


async def test_scan_reorg_rewind():
    rpc = MockAxelarRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 120}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    rpc.logs["ethereum-mainnet"] = [contract_call(block_number=100)]
    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xorig"
    adapter = _lane_adapter(rpc)
    _, checkpoint = await adapter.scan(None)

    rpc.block_hashes[("ethereum-mainnet", 105)] = "0xforked"
    observations, checkpoint = await adapter.scan(checkpoint)
    reorged = [o for o in observations if o["phase"] == "reorged"]
    assert reorged and reorged[0]["discontinuity_kind"] == "block_hash"
    assert checkpoint["networks"]["ethereum-mainnet"]["last_scanned_block"] < 105


async def test_scan_cursor_drift_rewind():
    rpc = MockAxelarRpc()
    rpc.heads["ethereum-mainnet"] = {"number": 30}
    rpc.heads["arbitrum-mainnet"] = {"number": 0}
    adapter = _lane_adapter(rpc)
    checkpoint = {"networks": {"ethereum-mainnet": {"last_scanned_block": 105, "recent_hashes": {}}}}
    observations, checkpoint = await adapter.scan(checkpoint)
    drift = [o for o in observations if o.get("discontinuity_kind") == "cursor_drift"]
    assert drift and drift[0]["phase"] == "reorged"


async def test_scan_without_rpc_is_credential_gated():
    with pytest.raises(NotImplementedError):
        await AxelarAdapter(rpc_client=None).scan(None)


# ── certification / health ────────────────────────────────────────────────────

def test_certification_descriptor_is_honest_and_passes_checks():
    adapter = _adapter()
    descriptor = adapter.certification_descriptor()
    assert descriptor.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
    assert "relay" in descriptor.unsupported_operations
    results = run_certification(adapter, ctx={"sample_request": {}})
    failures = [r for r in results if not r.passed]
    assert failures == [], [(r.name, r.detail) for r in failures]


def test_security_policy_is_pos_validator_set():
    policy = _adapter().snapshot_security_policy("axelar:ethereum-mainnet->arbitrum-mainnet")
    assert policy["verification_model"] == "pos_validator_set_quadratic_bft"


def test_health_reflects_configuration():
    assert _adapter().health({"configured": False})["healthy"] is False
    assert _adapter(rpc=MockAxelarRpc()).health()["healthy"] is True
