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

from services.rewards.policy_engine import IdentityInput, PolicyDecision, _amount_to_decimal
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
    _resolve_asset_decimals,
    _reward_amount_to_atomic,
    get_rail_adapter,
)


def _run(coro):
    # Robust against asyncio-auto-mode tests having closed the thread's
    # loop earlier in the same worker: drive on a fresh loop each call.
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


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
    "asset_decimals": 18,
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

# ═══════════════════════════════════════════════════════════════════════════
# Rail matrix: native rails vs intentionally-unsupported (deliverable 5)
# ═══════════════════════════════════════════════════════════════════════════

# Rails that must never be a beta stub or intentionally-unsupported.
FIRST_RELEASE_RAILS = [
    "recommend_only", "manual_approval", "manual_export", "tenant_webhook",
    "onchain_claim", "internal_credit",
]
# Rails that are deliberately out of this release — configuring is refused.
INTENTIONALLY_UNSUPPORTED = ["loyalty_points", "coupon"]


def test_rail_matrix_tiers_match_adapters():
    """Every adapter is classified, and the tiers are the confirmed release scope."""
    from services.rewards.rail_matrix import RAIL_MATRIX
    from services.rewards.rails import _RAIL_ADAPTERS
    assert set(RAIL_MATRIX) == set(_RAIL_ADAPTERS)
    tiers = {name: c.tier for name, c in RAIL_MATRIX.items()}
    assert tiers["internal_credit"] == "production"
    assert tiers["stripe_credit"] == "sandbox"
    assert tiers["x402_credit"] == "explicit_beta"
    assert tiers["loyalty_points"] == "intentionally_unsupported"
    assert tiers["coupon"] == "intentionally_unsupported"


@pytest.mark.parametrize("rail", INTENTIONALLY_UNSUPPORTED)
def test_intentionally_unsupported_rails_refuse_config_and_delivery(rail):
    from services.rewards.rail_matrix import is_configurable
    adapter = get_rail_adapter(rail)
    assert not is_configurable(rail)
    errors = adapter.validate_config({})
    assert any("intentionally unsupported" in e.lower() for e in errors)
    with pytest.raises(RailUnavailableError) as exc:
        _run(adapter.deliver({}, {}))
    assert exc.value.reason == "intentionally_unsupported"


def test_native_rails_are_configurable():
    from services.rewards.rail_matrix import is_configurable
    for rail in ("internal_credit", "stripe_credit", "x402_credit"):
        assert is_configurable(rail)


def test_internal_credit_delivers_through_ledger():
    """internal_credit is a real production rail: it posts a durable, idempotent
    double-entry credit and returns success."""
    from decimal import Decimal
    from services.rewards.credit_ledger import get_internal_credit_ledger

    adapter = get_rail_adapter("internal_credit")
    action = {
        "id": "act-ic-1",
        "tenant_id": TENANT,
        "payload": {
            "recipient_id": "rcpt-1", "campaign_id": "cmp-1",
            "amount": "12.50", "currency": "USD", "idempotency_key": "ic-idem-1",
        },
    }
    result = _run(adapter.deliver(action, {}))
    assert result.success and result.status == "delivered"
    bal = _run(get_internal_credit_ledger().get_balance(TENANT, "rcpt-1", "USD"))
    assert bal == Decimal("12.50")
    # idempotent: redelivery does not double-credit
    _run(adapter.deliver(action, {}))
    bal2 = _run(get_internal_credit_ledger().get_balance(TENANT, "rcpt-1", "USD"))
    assert bal2 == Decimal("12.50")


def test_tenant_webhook_is_first_release_and_durable_ready():
    """tenant_webhook is a real first-release rail with PR-1 SSRF + a durable
    outbox path."""
    adapter = get_rail_adapter("tenant_webhook")
    assert adapter.rail_name == "tenant_webhook"
    from services.rewards.delivery_outbox import RewardWebhookSender
    assert isinstance(RewardWebhookSender()._adapter, TenantWebhookAdapter)


# ═══════════════════════════════════════════════════════════════════════════
# TenantWebhookAdapter — SSRF hardening (DEFECT 1)
# ═══════════════════════════════════════════════════════════════════════════

_WEBHOOK_ACTION = {
    "payload": {"event": "reward.action.ready", "idempotency_key": "idem-ssrf", "tenant_id": "t1"},
}


def _webhook_config(url: str) -> dict:
    return {"webhook_url": url, "config": {"signing_secret": "s3cr3t", "timeout_ms": 5000}}


@pytest.mark.parametrize("url", [
    "https://169.254.169.254/hook",   # cloud metadata endpoint
    "https://127.0.0.1/hook",         # loopback
    "https://10.1.2.3/hook",          # RFC-1918 private
])
def test_webhook_ssrf_blocked_no_network(monkeypatch, url):
    """Outside local mode, an SSRF destination is rejected with success=False and NO HTTP call."""
    monkeypatch.setenv("AETHER_ENV", "production")
    adapter = TenantWebhookAdapter()

    with patch("httpx.AsyncClient") as mock_client:
        result = _run(adapter.deliver(_WEBHOOK_ACTION, _webhook_config(url)))

    assert result.success is False
    assert result.status == "failed"
    assert result.error and "SSRF" in result.error
    # Fail-closed: the HTTP client is never even constructed.
    assert mock_client.called is False


def test_webhook_enforces_https_outside_local(monkeypatch):
    """A plain-HTTP URL is rejected outside local mode, before any network I/O."""
    monkeypatch.setenv("AETHER_ENV", "production")
    adapter = TenantWebhookAdapter()

    with patch("httpx.AsyncClient") as mock_client:
        result = _run(adapter.deliver(_WEBHOOK_ACTION, _webhook_config("http://example.com/hook")))

    assert result.success is False
    assert result.status == "failed"
    assert "HTTPS" in (result.error or "")
    assert mock_client.called is False


def test_webhook_malformed_url_rejected_no_network(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    adapter = TenantWebhookAdapter()

    with patch("httpx.AsyncClient") as mock_client:
        result = _run(adapter.deliver(_WEBHOOK_ACTION, _webhook_config("not-a-real-url")))

    assert result.success is False
    assert result.status == "failed"
    assert mock_client.called is False


def test_webhook_allows_loopback_in_local(monkeypatch):
    """Local/test mode keeps loopback reachable so the HTTP call proceeds."""
    monkeypatch.setenv("AETHER_ENV", "local")
    adapter = TenantWebhookAdapter()

    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_instance.post = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        result = _run(adapter.deliver(_WEBHOOK_ACTION, _webhook_config("http://127.0.0.1/hook")))

    assert mock_instance.post.called
    assert result.success is True
    assert result.status == "delivered"


def test_webhook_follow_redirects_disabled_in_local(monkeypatch):
    """The httpx client must be constructed with follow_redirects=False."""
    monkeypatch.setenv("AETHER_ENV", "local")
    adapter = TenantWebhookAdapter()

    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_instance.post = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        _run(adapter.deliver(_WEBHOOK_ACTION, _webhook_config("https://example.com/hook")))

    _, ctor_kwargs = mock_client.call_args
    assert ctor_kwargs.get("follow_redirects") is False


def test_webhook_validate_config_rejects_malformed_url():
    adapter = TenantWebhookAdapter()
    errors = adapter.validate_config({"webhook_url": "http://", "signing_secret": "s"})
    assert any("malformed" in e for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# Exact reward-amount conversion (DEFECT 2)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("amount, decimals, expected", [
    ("0.1", 6, 100_000),                                   # 0.1 USDC (6dp)
    ("1.005", 6, 1_005_000),                               # fractional, exact
    ("10", 18, 10_000_000_000_000_000_000),               # 10 tokens @ 18dp
    (10.0, 18, 10_000_000_000_000_000_000),               # float in, via str()
    ("123456789.123456789", 18, 123456789123456789000000000),  # large + fractional
    ("0", 18, 0),
])
def test_reward_amount_exact_atomic_conversion(amount, decimals, expected):
    assert _reward_amount_to_atomic(amount, decimals) == expected


def test_reward_amount_no_binary_float_artifacts():
    """The classic float trap: 0.1 must not leak binary-float error into the atomic value."""
    # float(0.1) * 10**18 == 100000000000000000.00000001 → int() == 100000000000000000
    # but Decimal("0.1") scaled by 18 is exactly 10**17.
    assert _reward_amount_to_atomic("0.1", 18) == 100_000_000_000_000_000
    assert _amount_to_decimal(0.1) == __import__("decimal").Decimal("0.1")


def test_reward_amount_inexact_for_decimals_rejected():
    """More fractional digits than the asset allows → reject, never silently truncate."""
    with pytest.raises(ValueError, match="not exactly representable"):
        _reward_amount_to_atomic("1.005", 2)


def test_reward_amount_non_numeric_rejected():
    with pytest.raises(ValueError):
        _reward_amount_to_atomic("not-a-number", 18)


def test_reward_amount_negative_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        _reward_amount_to_atomic("-1", 18)


def test_resolve_asset_decimals_priority_and_absence():
    assert _resolve_asset_decimals({"asset_decimals": 6}, {}, {}) == 6
    assert _resolve_asset_decimals({}, {"decimals": 8}, {}) == 8
    assert _resolve_asset_decimals({}, {}, {"asset_decimals": 2}) == 2
    assert _resolve_asset_decimals({}, {}, {}) is None


def test_onchain_claim_rejects_ambiguous_decimals(monkeypatch):
    """A reward amount with no explicit decimals is rejected BEFORE any signing."""
    monkeypatch.setenv("AETHER_ENV", "local")
    adapter = OnchainClaimAdapter()
    decision = PolicyDecision(
        eligible=True,
        decision="eligible",
        campaign_id="camp-001",
        rule_id="rule-001",
        rail="onchain_claim",
        reward={"amount": "10.0", "unit": "TOKEN", "currency": "TOKEN"},
        identity={"wallet_address": "0xdeadbeef"},
    )
    rule = {"id": "rule-001", "name": "R", "reward_amount": "10.0"}  # no decimals anywhere
    campaign = {"id": "camp-001", "chain_id": 1,
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3"}
    with pytest.raises(ValueError, match="decimals"):
        _run(adapter.build_action_payload(decision, rule, campaign, TENANT, "idem-dec"))


def test_onchain_claim_threads_exact_decimal_amount(monkeypatch):
    """With explicit decimals, the proof payload carries the exact atomic amount."""
    monkeypatch.setenv("AETHER_ENV", "local")

    class _FakeProof:
        nonce = "abc123"
        expiry = 9999999999
        chain_id = 1
        contract_address = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
        message_hash = "0xhash"
        signature = "0xsig"

    captured = {}

    class _FakeSigner:
        signer_address = "0xSigner"

        def __init__(self, config):
            self.config = config

        async def generate_proof(self, *, user, action_type, amount_wei):
            captured["amount_wei"] = amount_wei
            return _FakeProof()

    adapter = OnchainClaimAdapter()
    decision = PolicyDecision(
        eligible=True,
        decision="eligible",
        campaign_id="camp-001",
        rule_id="rule-001",
        rail="onchain_claim",
        reward={"amount": "1.5", "unit": "TOKEN", "currency": "TOKEN", "asset_decimals": 6},
        identity={"wallet_address": "0xdeadbeef"},
    )
    rule = {"id": "rule-001", "name": "R", "reward_amount": "1.5", "asset_decimals": 6}
    campaign = {"id": "camp-001", "chain_id": 1,
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3"}

    with patch("services.oracle.signer.OracleProofSigner", _FakeSigner):
        payload = _run(adapter.build_action_payload(decision, rule, campaign, TENANT, "idem-exact"))

    # 1.5 * 10**6 == 1_500_000, exactly.
    assert captured["amount_wei"] == 1_500_000
    assert payload["proof_data"]["amount"] == "1500000"
