"""Adapter-level tests: five named providers, status maps, normalization,
webhook signature verification, and PII redaction."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import NotFoundError  # noqa: E402
from services.integrations.providers.payment_rails import (  # noqa: E402
    ADAPTERS,
    PROVIDER_NAMES,
    get_adapter,
)
from services.integrations.providers.payment_rails.base import (  # noqa: E402
    get_payment_rails_vault,
    payload_hash,
    sanitize_payload,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


class TestRegistry:
    def test_exactly_five_named_providers(self):
        assert set(PROVIDER_NAMES) == {"privy", "stripe", "coinbase", "moonpay", "bridge"}

    def test_unknown_provider_is_not_found_no_generic_fallback(self):
        for unknown in ("paypal", "generic", "webhook", ""):
            with pytest.raises(NotFoundError):
                get_adapter(unknown)

    def test_status_maps_cover_canonical_statuses_only(self):
        canonical = {
            "initiated", "submitted", "pending", "completed",
            "failed", "refunded", "cancelled", "unresolved",
        }
        for name, adapter in ADAPTERS.items():
            mapped = set(adapter.STATUS_MAP.values())
            assert mapped <= canonical, f"{name} maps outside canonical statuses: {mapped}"
            ordering = adapter.status_map().ordering
            assert set(ordering) == canonical

    def test_unknown_provider_status_maps_to_unresolved(self):
        for adapter in ADAPTERS.values():
            assert adapter.map_status("definitely_not_a_status") == "unresolved"
            assert adapter.map_status(None) == "unresolved"


class TestWebhookVerification:
    async def test_valid_hmac_accepted_and_invalid_rejected(self):
        tenant_id = _tenant()
        adapter = ADAPTERS["moonpay"]
        secret = "whsec_test_secret"
        await get_payment_rails_vault().store_key(
            tenant_id, adapter.vault_provider_name, "payment", secret
        )
        payload = json.dumps({"type": "transaction_updated", "data": {"id": "tx1"}}).encode()
        # MoonPay signs with the compound `Moonpay-Signature-V2: t=<unix>,s=<hex>`
        # header; the HMAC is over `f"{t}.".encode() + payload` and the timestamp
        # must be within the freshness tolerance of the live clock.
        timestamp = str(int(time.time()))
        signature = hmac.new(
            secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
        ).hexdigest()

        assert await adapter.verify_webhook(
            tenant_id, payload, f"t={timestamp},s={signature}", timestamp
        ) is True
        assert await adapter.verify_webhook(
            tenant_id, payload, f"t={timestamp},s=deadbeef", timestamp
        ) is False
        assert await adapter.verify_webhook(tenant_id, payload, None, timestamp) is False

    async def test_unconfigured_tenant_never_verifies(self):
        adapter = ADAPTERS["privy"]
        assert await adapter.verify_webhook(_tenant(), b"{}", "v1=abc", "1") is False

    async def test_not_configured_is_typed_response(self):
        adapter = ADAPTERS["bridge"]
        response = adapter.not_configured()
        assert response["configured"] is False
        assert response["provider"] == "bridge"


class TestSanitization:
    def test_sensitive_keys_redacted_recursively(self):
        payload = {
            "card_number": "4111111111111111",
            "bank": {"account_number": "123456789", "routing_number": "021000021"},
            "kyc_document": "base64...",
            "cvv": "123",
            "iban": "DE44...",
            "ok_field": "keep",
        }
        sanitized, stripped = sanitize_payload(payload)
        flat = json.dumps(sanitized)
        assert "4111111111111111" not in flat
        assert "123456789" not in flat
        assert "021000021" not in flat
        assert sanitized["ok_field"] == "keep"
        assert stripped  # at least one key reported


class TestPrivy:
    def test_processor_passthrough_detail(self):
        adapter = ADAPTERS["privy"]
        event = adapter.parse_webhook(_tenant(), {
            "type": "funding.completed",
            "data": {
                "funding_id": "fund_1", "status": "completed", "flow": "fiat_onramp",
                "provider": "moonpay", "provider_transaction_id": "mp_9",
                "amount": "100", "source_currency": "usd", "asset": "usdc",
                "chain": "base", "wallet_address": "0xabc",
                "journey_id": "j1", "campaign_id": "c1", "user_id": "u1",
            },
        }, "hash1")[0]
        session = adapter.normalize_to_funding_session(_tenant(), event)
        assert session is not None
        assert session.provider == "privy"
        assert session.provider_detail == "moonpay"
        assert session.metadata["underlying"]["provider"] == "moonpay"
        assert session.status == "completed"
        assert session.journey_id == "j1" and session.campaign_id == "c1"
        assert session.fiat_currency == "USD" and session.destination_asset == "USDC"

    def test_deposit_address_side_record_not_a_session(self):
        adapter = ADAPTERS["privy"]
        tenant_id = _tenant()
        event = adapter.parse_webhook(tenant_id, {
            "type": "deposit_address.created",
            "data": {"id": "da1", "address": "0xdead", "chain": "base", "asset": "usdc"},
        }, "hash2")[0]
        assert adapter.normalize_to_funding_session(tenant_id, event) is None
        record = adapter.extract_deposit_address(tenant_id, event)
        assert record and record["address"] == "0xdead" and record["status"] == "active"


class TestCoinbase:
    def test_partner_user_ref_polling(self):
        adapter = ADAPTERS["coinbase"]
        events = adapter.status_map() and adapter._parse_poll_records(_tenant(), [
            {"transactionId": "cb1", "partnerUserRef": "user-42",
             "status": "ONRAMP_TRANSACTION_STATUS_SUCCESS",
             "purchaseAmount": {"value": "50", "currency": "USDC"}},
        ])
        assert events, "polling records should produce parsed events"
        assert events[0].source == "polling"

    def test_status_mapping_in_progress_and_success(self):
        adapter = ADAPTERS["coinbase"]
        in_progress = [k for k, v in adapter.STATUS_MAP.items() if v in ("pending", "submitted")]
        success = [k for k, v in adapter.STATUS_MAP.items() if v == "completed"]
        failed = [k for k, v in adapter.STATUS_MAP.items() if v == "failed"]
        assert in_progress and success and failed


class TestMoonPay:
    def test_aml_rejection_maps_to_failed_with_reason(self):
        adapter = ADAPTERS["moonpay"]
        tenant_id = _tenant()
        event = adapter.parse_webhook(tenant_id, {
            "type": "transaction_updated",
            "data": {"id": "mp1", "status": "pending",
                     "failureReason": "AML check rejected",
                     "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
                     "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"},
                     "walletAddress": "0xabc"},
        }, "h1")[0]
        session = adapter.normalize_to_funding_session(tenant_id, event)
        assert session is not None
        assert session.status == "failed"
        assert "AML" in (session.status_reason or "")

    def test_buy_and_sell_direction(self):
        adapter = ADAPTERS["moonpay"]
        tenant_id = _tenant()
        buy = adapter.normalize_to_funding_session(tenant_id, adapter.parse_webhook(tenant_id, {
            "type": "transaction_updated",
            "data": {"id": "mp2", "status": "completed", "baseCurrencyAmount": 100,
                     "quoteCurrencyAmount": 95, "baseCurrency": {"code": "usd"},
                     "currency": {"code": "eth"}, "walletAddress": "0x1",
                     "cryptoTransactionId": "0xhash"},
        }, "h2")[0])
        assert buy.flow_type == "fiat_onramp" and buy.destination_asset == "ETH"
        assert buy.tx_hash == "0xhash"

        sell = adapter.normalize_to_funding_session(tenant_id, adapter.parse_webhook(tenant_id, {
            "type": "sell_transaction_updated",
            "data": {"id": "mp3", "status": "completed", "baseCurrencyAmount": 100,
                     "quoteCurrencyAmount": 0.03, "baseCurrency": {"code": "usd"},
                     "currency": {"code": "eth"}},
        }, "h3")[0])
        assert sell.flow_type == "offramp" and sell.metadata.get("is_sell") is True

    def test_fee_summation_single_currency_only(self):
        adapter = ADAPTERS["moonpay"]
        tenant_id = _tenant()
        session = adapter.normalize_to_funding_session(tenant_id, adapter.parse_webhook(tenant_id, {
            "type": "transaction_updated",
            "data": {"id": "mp4", "status": "completed", "feeAmount": 1.5,
                     "extraFeeAmount": 0.5, "networkFeeAmount": 0.25,
                     "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"},
                     "baseCurrencyAmount": 100, "quoteCurrencyAmount": 97.75},
        }, "h4")[0])
        assert session.fee_amount == "2.25"
        assert session.fee_currency == "USD"


class TestBridge:
    def test_virtual_account_masked_reference(self):
        adapter = ADAPTERS["bridge"]
        tenant_id = _tenant()
        event = adapter.parse_webhook(tenant_id, {
            "event_type": "virtual_account.created",
            "event_object": {
                "id": "va1", "customer_id": "cust1", "status": "activated",
                "source_deposit_instructions": {
                    "currency": "usd", "bank_account_number": "9876543210",
                },
                "destination": {"address": "0xdest", "payment_rail": "base"},
            },
        }, "h5")[0]
        assert adapter.normalize_to_funding_session(tenant_id, event) is None
        record = adapter.extract_virtual_account(tenant_id, event)
        assert record is not None
        assert record["masked_account_ref"] == "****3210"
        assert "9876543210" not in json.dumps({k: v for k, v in record.items()
                                               if k != "masked_account_ref"})

    def test_activity_normalizes_to_funding_session(self):
        adapter = ADAPTERS["bridge"]
        tenant_id = _tenant()
        event = adapter.parse_webhook(tenant_id, {
            "event_type": "virtual_account.activity",
            "event_object": {
                "id": "act1", "type": "payment_processed", "status": "processed",
                "amount": "250.00", "currency": "usd", "customer_id": "cust1",
                "virtual_account_id": "va1", "deposit_id": "dep1",
                "source": {"payment_rail": "ach", "currency": "usd"},
                "destination": {"currency": "usdc", "payment_rail": "base",
                                "address": "0xdest", "transaction_hash": "0xtx"},
            },
        }, "h6")[0]
        session = adapter.normalize_to_funding_session(tenant_id, event)
        assert session is not None
        assert session.rail == "ach"
        assert session.status == "completed"
        assert session.virtual_account_id == "va1"
        assert session.tx_hash == "0xtx"


class TestCanonicalEvents:
    def test_completed_session_implies_initiated_and_completed(self):
        adapter = ADAPTERS["privy"]
        tenant_id = _tenant()
        event = adapter.parse_webhook(tenant_id, {
            "type": "funding.completed",
            "data": {"funding_id": "f9", "status": "completed", "amount": "10",
                     "source_currency": "usd"},
        }, "h7")[0]
        session = adapter.normalize_to_funding_session(tenant_id, event)
        types = [e["event_type"] for e in adapter.normalize_to_aether_events(session)]
        assert types == ["payment_initiated", "payment_completed"]

    def test_canonical_payloads_have_no_sensitive_fields(self):
        adapter = ADAPTERS["moonpay"]
        tenant_id = _tenant()
        session = adapter.normalize_to_funding_session(tenant_id, adapter.parse_webhook(tenant_id, {
            "type": "transaction_updated",
            "data": {"id": "mp5", "status": "failed", "failureReason": "fraud",
                     "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}},
        }, "h8")[0])
        for canonical in adapter.normalize_to_aether_events(session):
            flat = json.dumps(canonical).lower()
            for banned in ("card_number", "account_number", "routing", "kyc", "cvv"):
                assert banned not in flat

    def test_payload_hash_is_deterministic(self):
        a = payload_hash({"b": 2, "a": 1})
        b = payload_hash({"a": 1, "b": 2})
        assert a == b
