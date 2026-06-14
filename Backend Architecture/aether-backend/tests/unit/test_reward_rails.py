"""
Unit tests for RewardRailAdapters (A6).

Tests: payload building, delivery, HMAC signing, beta stub behavior,
config validation, and onchain_claim proof generation.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_lib
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from services.rewards.policy_engine import IdentityInput, PolicyDecision
from services.rewards.rails import (
    CouponAdapter,
    DeliveryResult,
    InternalCreditAdapter,
    LoyaltyPointsAdapter,
    ManualApprovalAdapter,
    ManualExportAdapter,
    OnchainClaimAdapter,
    RecommendOnlyAdapter,
    RailUnavailableError,
    StripeCreditAdapter,
    TenantWebhookAdapter,
    X402CreditAdapter,
    get_rail_adapter,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_decision(
    *,
    eligible=True,
    decision="eligible",
    campaign_id="camp-001",
    rule_id="rule-001",
    execution_mode="recommend_only",
    rail="recommend_only",
    reward=None,
) -> PolicyDecision:
    return PolicyDecision(
        eligible=eligible,
        decision=decision,
        campaign_id=campaign_id,
        rule_id=rule_id,
        execution_mode=execution_mode,
        rail=rail,
        reward=reward or {"amount": "10.0", "unit": "USD", "currency": "USD"},
        identity={"user_id": "user_001", "wallet_address": "0xdeadbeef"},
    )


_RULE = {
    "id": "rule-001",
    "name": "Test Rule",
    "reward_amount": 10.0,
    "reward_unit": "USD",
    "reward_currency": "USD",
    "reward_metadata": {},
}

_CAMPAIGN = {
    "id": "camp-001",
    "name": "Test Campaign",
    "attribution_model": "last_touch",
}

TENANT = "tenant_test_001"
IDEMPOTENCY_KEY = "test_idem_key_001"


# ═══════════════════════════════════════════════════════════════════════════
# get_rail_adapter factory
# ═══════════════════════════════════════════════════════════════════════════

def test_get_rail_adapter_returns_correct_type():
    assert isinstance(get_rail_adapter("recommend_only"), RecommendOnlyAdapter)
    assert isinstance(get_rail_adapter("manual_approval"), ManualApprovalAdapter)
    assert isinstance(get_rail_adapter("manual_export"), ManualExportAdapter)
    assert isinstance(get_rail_adapter("tenant_webhook"), TenantWebhookAdapter)
    assert isinstance(get_rail_adapter("onchain_claim"), OnchainClaimAdapter)
    assert isinstance(get_rail_adapter("stripe_credit"), StripeCreditAdapter)
    assert isinstance(get_rail_adapter("loyalty_points"), LoyaltyPointsAdapter)


def test_get_rail_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown rail"):
        get_rail_adapter("not_a_real_rail")


# ═══════════════════════════════════════════════════════════════════════════
# RecommendOnlyAdapter
# ═══════════════════════════════════════════════════════════════════════════

def test_recommend_only_builds_payload():
    decision = _make_decision(rail="recommend_only")
    payload = _run(RecommendOnlyAdapter().build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, IDEMPOTENCY_KEY))
    assert payload["rail"] == "recommend_only"
    assert payload["status"] == "ready"
    assert "reward" in payload


def test_recommend_only_deliver_no_op():
    action = {"rail": "recommend_only", "status": "ready", "payload": {}}
    result: DeliveryResult = _run(RecommendOnlyAdapter().deliver(action, {}))
    assert result.success
    assert result.status == "ready"


def test_recommend_only_config_valid():
    errors = RecommendOnlyAdapter().validate_config({})
    assert errors == []


# ═══════════════════════════════════════════════════════════════════════════
# ManualApprovalAdapter
# ═══════════════════════════════════════════════════════════════════════════

def test_manual_approval_payload_status_pending():
    decision = _make_decision(rail="manual_approval")
    payload = _run(ManualApprovalAdapter().build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, IDEMPOTENCY_KEY))
    assert payload["status"] == "pending_approval"


def test_manual_approval_deliver_raises():
    with pytest.raises(RailUnavailableError):
        _run(ManualApprovalAdapter().deliver({}, {}))


# ═══════════════════════════════════════════════════════════════════════════
# ManualExportAdapter
# ═══════════════════════════════════════════════════════════════════════════

def test_manual_export_builds_payload():
    decision = _make_decision(rail="manual_export")
    payload = _run(ManualExportAdapter().build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, IDEMPOTENCY_KEY))
    assert payload["status"] == "ready"
    assert "export_row" in payload or payload.get("rail") == "manual_export"


def test_manual_export_deliver_marks_ready():
    action = {"rail": "manual_export", "status": "ready", "payload": {}}
    result: DeliveryResult = _run(ManualExportAdapter().deliver(action, {}))
    assert result.success
    assert result.status in ("ready", "delivered")


# ═══════════════════════════════════════════════════════════════════════════
# TenantWebhookAdapter — HMAC signing
# ═══════════════════════════════════════════════════════════════════════════

def test_webhook_adapter_produces_hmac_signature():
    secret = "test_webhook_secret"
    adapter = TenantWebhookAdapter()
    payload_body = json.dumps({"event": "reward.action.ready", "action_id": "act_001"})
    timestamp = str(int(time.time()))
    sig = adapter._sign_payload(secret, timestamp, payload_body)
    assert sig.startswith("hmac-sha256=")
    # Verify manually
    expected = hmac_lib.new(
        secret.encode(),
        f"{timestamp}.{payload_body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert sig == f"hmac-sha256={expected}"


def test_webhook_adapter_config_requires_url():
    adapter = TenantWebhookAdapter()
    errors = adapter.validate_config({"secret_ref": "ref/key"})
    assert any("webhook_url" in e for e in errors)


def test_webhook_adapter_config_requires_secret():
    adapter = TenantWebhookAdapter()
    errors = adapter.validate_config({"webhook_url": "https://example.com/webhook"})
    assert any("secret" in e.lower() for e in errors)


def test_webhook_adapter_valid_config():
    adapter = TenantWebhookAdapter()
    errors = adapter.validate_config({
        "webhook_url": "https://example.com/reward/webhook",
        "secret_ref": "secrets/webhook_hmac_key",
    })
    assert errors == []


def test_webhook_adapter_deliver_calls_http(monkeypatch):
    """Deliver should make an HTTPS POST with correct Aether headers."""
    captured_headers = {}

    async def fake_post(url, *, json=None, headers=None, timeout=None):
        captured_headers.update(headers or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ok": True}
        return resp

    adapter = TenantWebhookAdapter()
    action = {
        "id": "act_001",
        "rail": "tenant_webhook",
        "payload": {"event": "reward.action.ready", "action_id": "act_001"},
        "status": "queued",
        "delivery_attempts": 0,
    }
    config = {
        "webhook_url": "https://example.com/webhook",
        "secret_ref": "test_secret",
        "config": {"timeout_ms": 5000, "max_retries": 1},
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_instance.post = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        result = _run(adapter.deliver(action, config))

    assert mock_instance.post.called
    _, call_kwargs = mock_instance.post.call_args
    sent_headers = call_kwargs.get("headers", {})
    assert "X-Aether-Signature" in sent_headers
    assert "X-Aether-Timestamp" in sent_headers
    assert "X-Aether-Idempotency-Key" in sent_headers


# ═══════════════════════════════════════════════════════════════════════════
# OnchainClaimAdapter
# ═══════════════════════════════════════════════════════════════════════════

def test_onchain_claim_requires_wallet_address():
    adapter = OnchainClaimAdapter()
    decision = _make_decision(
        rail="onchain_claim",
        reward={"amount": "10.0", "unit": "TOKEN", "currency": "TOKEN"},
    )
    # Decision with no wallet address
    decision = PolicyDecision(
        eligible=True,
        decision="eligible",
        campaign_id="camp-001",
        rule_id="rule-001",
        rail="onchain_claim",
        reward={"amount": "10.0", "unit": "TOKEN", "currency": "TOKEN"},
        identity={"user_id": "user_001"},  # no wallet_address
    )
    config = {"chain_id": 1, "contract_address": "0xdeadbeef"}
    with pytest.raises(ValueError, match="wallet"):
        _run(adapter.build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, IDEMPOTENCY_KEY))


def test_onchain_claim_proof_generated_in_local():
    os.environ["AETHER_ENV"] = "local"
    adapter = OnchainClaimAdapter()
    decision = PolicyDecision(
        eligible=True,
        decision="eligible",
        campaign_id="camp-001",
        rule_id="rule-001",
        rail="onchain_claim",
        reward={"amount": "100", "unit": "TOKEN", "currency": "TOKEN"},
        identity={"user_id": "user_001", "wallet_address": "0xdeadbeefdeadbeef"},
    )
    config = {"chain_id": 1, "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3"}
    payload = _run(adapter.build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, IDEMPOTENCY_KEY))
    assert "proof" in payload
    proof = payload["proof"]
    assert proof["user"] == "0xdeadbeefdeadbeef"
    assert "signature" in proof
    assert "nonce" in proof
    assert "expiry" in proof


def test_onchain_claim_nonce_unique():
    os.environ["AETHER_ENV"] = "local"
    adapter = OnchainClaimAdapter()
    decision = PolicyDecision(
        eligible=True,
        decision="eligible",
        campaign_id="camp-001",
        rule_id="rule-001",
        rail="onchain_claim",
        reward={"amount": "100", "unit": "TOKEN", "currency": "TOKEN"},
        identity={"wallet_address": "0xdeadbeef"},
    )
    config = {"chain_id": 1, "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3"}

    payload1 = _run(adapter.build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, "idem_001"))
    payload2 = _run(adapter.build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, "idem_002"))

    assert payload1["proof"]["nonce"] != payload2["proof"]["nonce"]


def test_onchain_claim_proof_expiry_in_future():
    os.environ["AETHER_ENV"] = "local"
    adapter = OnchainClaimAdapter()
    decision = PolicyDecision(
        eligible=True,
        decision="eligible",
        campaign_id="camp-001",
        rule_id="rule-001",
        rail="onchain_claim",
        reward={"amount": "50", "unit": "TOKEN", "currency": "TOKEN"},
        identity={"wallet_address": "0xdeadbeef"},
    )
    config = {"chain_id": 1, "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3"}

    payload = _run(adapter.build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, "idem_003"))
    assert payload["proof"]["expiry"] > int(time.time())


def test_onchain_claim_blocks_hardhat_key_in_staging():
    original_env = os.environ.get("AETHER_ENV", "local")
    os.environ["AETHER_ENV"] = "staging"
    os.environ.pop("ORACLE_SIGNER_KEY", None)
    os.environ.pop("EVM_SIGNER_KEY", None)

    try:
        adapter = OnchainClaimAdapter()
        decision = PolicyDecision(
            eligible=True,
            decision="eligible",
            campaign_id="camp-001",
            rule_id="rule-001",
            rail="onchain_claim",
            reward={"amount": "50", "unit": "TOKEN", "currency": "TOKEN"},
            identity={"wallet_address": "0xdeadbeef"},
        )
        config = {"chain_id": 1, "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3"}
        with pytest.raises((RuntimeError, ValueError)):
            _run(adapter.build_action_payload(decision, _RULE, _CAMPAIGN, TENANT, "idem_004"))
    finally:
        os.environ["AETHER_ENV"] = original_env


def test_onchain_claim_deliver_is_noop():
    action = {"rail": "onchain_claim", "status": "created", "payload": {"proof": {}}}
    result = _run(OnchainClaimAdapter().deliver(action, {}))
    assert result.success
    assert result.status == "created"


# ═══════════════════════════════════════════════════════════════════════════
# Beta rail stubs
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("adapter_cls", [
    StripeCreditAdapter,
    LoyaltyPointsAdapter,
    CouponAdapter,
    InternalCreditAdapter,
    X402CreditAdapter,
])
def test_beta_rail_validate_config_returns_error(adapter_cls):
    errors = adapter_cls().validate_config({})
    assert len(errors) >= 1
    assert any("beta" in e.lower() or "unavailable" in e.lower() for e in errors)


@pytest.mark.parametrize("adapter_cls", [
    StripeCreditAdapter,
    LoyaltyPointsAdapter,
    CouponAdapter,
    InternalCreditAdapter,
    X402CreditAdapter,
])
def test_beta_rail_deliver_raises_unavailable(adapter_cls):
    with pytest.raises(RailUnavailableError) as exc_info:
        _run(adapter_cls().deliver({}, {}))
    assert exc_info.value.reason == "beta_unavailable"
