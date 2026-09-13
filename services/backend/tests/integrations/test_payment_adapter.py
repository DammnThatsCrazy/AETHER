"""Tests for the observe-only payment-rail :class:`IntegrationAdapter` (§17).

No network: the real registry rails are exercised with *injected* fixtures.
Webhook signature verification reads the tenant signing secret from the
in-memory BYOK vault (the conftest defaults ``AETHER_CREDENTIAL_BACKEND`` to
``in_memory``); incremental status sync is driven with pre-supplied
provider-shaped records, so ``status_sync`` never opens an HTTP client; the
connection test is offline in local mode.

Invariants asserted: valid webhook signature → ok / invalid → unauthorized;
a polling rail's sync carries the rail's *sanitized* records while a
webhook-only rail is ``not_supported``; every fund-movement / non-rail op is a
typed ``not_supported`` (never a raise); a sensitive *value* fed through the
sync and normalize paths never surfaces in the serialized result; and
``payment_rail_adapter_for`` builds the honest ``<rail>.payment_rails.observe``
identity.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

import pytest

os.environ.setdefault("AETHER_CREDENTIAL_BACKEND", "in_memory")
os.environ.setdefault("AETHER_ENV", "local")

from services.integrations.adapter import AdapterContext, IntegrationAdapter
from services.integrations.payment_adapter import (
    PaymentRailIntegrationAdapter,
    payment_rail_adapter_for,
)
from services.integrations.providers.payment_rails.base import get_payment_rails_vault
from shared.common.common import NotFoundError
from shared.integration_contracts.results import AdapterStatus

# Distinctive sensitive VALUES that could never collide with a field/key name,
# so their presence in serialized output is an unambiguous leak. The sanitizer
# strips the *values* and records only the stripped key *names* in an audit
# ``stripped_keys`` list — so the guard asserts on values (and surviving payload
# keys), never on the audit key names.
_PAN = "4111111111111111"
_CVV_VALUE = "998877"
_SSN_VALUE = "123-45-6789"


def _ctx(tenant_id: str, provider: str, correlation_id: str = "corr-1") -> AdapterContext:
    return AdapterContext(
        tenant_id=tenant_id, connector_type=provider, correlation_id=correlation_id
    )


async def _seed_secret(tenant_id: str, vault_provider_name: str, secret: str) -> None:
    await get_payment_rails_vault().store_key(
        tenant_id, vault_provider_name, "payments", secret
    )


def _sensitive_keys(node: object) -> list[str]:
    """Sensitive keys that SURVIVED into a payload tree (should be none)."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("card_number", "cvv", "ssn"):
                found.append(key)
            found.extend(_sensitive_keys(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_sensitive_keys(item))
    return found


# ── Webhook verification (rails are webhook-first) ───────────────────────────


@pytest.mark.asyncio
async def test_verify_webhook_valid_signature_ok_invalid_unauthorized():
    tenant = "tenant-verify"
    secret = "whsec_privy_123"
    adapter = payment_rail_adapter_for("privy")
    await _seed_secret(tenant, adapter.rail.vault_provider_name, secret)

    timestamp = "1700000000"
    payload = b'{"type":"funding.completed","data":{"funding_id":"f1"}}'
    signed = f"{timestamp}.".encode("utf-8") + payload  # timestamped_hex scheme
    good_sig = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()

    ok = await adapter.verify_webhook(
        _ctx(tenant, "privy"), payload=payload, signature=good_sig, timestamp=timestamp
    )
    assert ok.success is True
    assert ok.status is AdapterStatus.OK
    assert ok.data["verified"] is True
    assert ok.correlation_id == "corr-1"

    bad = await adapter.verify_webhook(
        _ctx(tenant, "privy"), payload=payload, signature="deadbeef", timestamp=timestamp
    )
    assert bad.success is False
    assert bad.status is AdapterStatus.UNAUTHORIZED
    assert bad.error_code == "webhook_signature_invalid"


@pytest.mark.asyncio
async def test_verify_webhook_registration_gates_on_signing_secret():
    tenant = "tenant-reg"
    adapter = payment_rail_adapter_for("privy")

    missing = await adapter.verify_webhook_registration(_ctx(tenant, "privy"))
    assert missing.success is False
    assert missing.status is AdapterStatus.UNAUTHORIZED
    assert missing.error_code == "webhook_signing_secret_not_configured"

    await _seed_secret(tenant, adapter.rail.vault_provider_name, "whsec_reg")
    ready = await adapter.verify_webhook_registration(_ctx(tenant, "privy"))
    assert ready.success is True
    assert ready.status is AdapterStatus.OK
    assert ready.data["webhook_verification_ready"] is True
    # Honest: these rails do not self-register webhooks upstream.
    assert ready.data["registration_supported"] is False


# ── Incremental status sync (polling rails only) ─────────────────────────────


@pytest.mark.asyncio
async def test_run_incremental_sync_polling_rail_carries_sanitized_records():
    adapter = payment_rail_adapter_for("coinbase")  # a real polling rail
    assert adapter.rail.polling_supported is True
    assert adapter.manifest.sync.incremental is True

    records = [
        {
            "transaction_id": "tx_1",
            "status": "success",
            "purchase_amount": "100",
            "purchase_currency": "USDC",
            "purchase_network": "base",
            "wallet_address": "0xabc",
            # Sensitive fields that MUST be stripped from any surfaced data.
            "card_number": _PAN,
            "cvv": _CVV_VALUE,
            "ssn": _SSN_VALUE,
        }
    ]

    result = await adapter.run_incremental_sync(
        _ctx("t-sync", "coinbase"), cursor=None, records=records
    )

    assert result.success is True
    assert result.status is AdapterStatus.OK
    assert result.data is not None and len(result.data) == 1
    assert result.account["event_count"] == 1
    # The non-sensitive transaction id DID survive (records are carried through).
    serialized = result.model_dump_json()
    assert "tx_1" in serialized

    # Sanitization guard: no sensitive VALUE surfaces anywhere in the result,
    # and no sensitive key survived inside the event payload tree.
    assert _PAN not in serialized
    assert _CVV_VALUE not in serialized
    assert _SSN_VALUE not in serialized
    for event in result.data:
        assert _sensitive_keys(event.get("payload")) == []


@pytest.mark.asyncio
async def test_run_incremental_sync_webhook_only_rail_not_supported():
    adapter = payment_rail_adapter_for("privy")  # webhook-only: no pull API
    assert adapter.rail.polling_supported is False

    result = await adapter.run_incremental_sync(_ctx("t-sync2", "privy"))

    assert result.success is False
    assert result.status is AdapterStatus.NOT_SUPPORTED
    assert result.error_code == "not_supported:run_incremental_sync"


# ── Unsupported / fund-movement-adjacent ops are honest not_supported ────────


@pytest.mark.asyncio
async def test_unsupported_ops_return_not_supported_and_never_raise():
    adapter = payment_rail_adapter_for("privy")
    ctx = _ctx("t-unsupported", "privy")

    begin = await adapter.begin_authorization(ctx, redirect_uri="https://x/cb")
    backfill = await adapter.run_initial_backfill(ctx)
    discover = await adapter.discover_accounts(ctx)
    rotate = await adapter.rotate_credentials(ctx)
    reconcile = await adapter.reconcile(ctx)
    register = await adapter.register_webhooks(ctx)
    disconnect = await adapter.disconnect(ctx)

    for result in (begin, backfill, discover, rotate, reconcile, register, disconnect):
        assert result.success is False
        assert result.status is AdapterStatus.NOT_SUPPORTED
        assert result.error_code is not None
        assert result.error_code.startswith("not_supported:")


# ── Normalization (sanitizing, never surfaces sensitive fields) ──────────────


def test_normalize_delegates_and_never_surfaces_sensitive_fields():
    adapter = payment_rail_adapter_for("coinbase")
    payload = {
        "event_type": "onramp.transaction.updated",
        "transaction": {
            "transaction_id": "tx_9",
            "status": "success",
            "purchase_amount": "50",
            "purchase_currency": "USDC",
            "card_number": _PAN,
            "cvv": _CVV_VALUE,
        },
    }

    normalized = adapter.normalize(payload)

    assert isinstance(normalized, dict)
    assert normalized["provider"] == "coinbase"  # canonical funding projection
    serialized = json.dumps(normalized)
    assert _PAN not in serialized
    assert _CVV_VALUE not in serialized
    assert _sensitive_keys(normalized) == []


def test_normalize_non_funding_input_falls_back_to_sanitized_copy():
    adapter = payment_rail_adapter_for("coinbase")

    # No transaction id -> the rail yields no funding projection; the adapter
    # falls back to a sanitized copy rather than surfacing the raw record.
    normalized = adapter.normalize({"card_number": _PAN, "foo": "bar"})

    assert normalized == {"foo": "bar"}
    assert _PAN not in json.dumps(normalized)


# ── Health ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_unconfigured_unauthorized_then_ok_when_configured():
    tenant = "tenant-health"
    adapter = payment_rail_adapter_for("privy")

    unconfigured = await adapter.health_check(_ctx(tenant, "privy"))
    assert unconfigured.success is False
    assert unconfigured.status is AdapterStatus.UNAUTHORIZED
    assert unconfigured.error_code == "health:not_configured"

    await _seed_secret(tenant, adapter.rail.vault_provider_name, "whsec_health")
    healthy = await adapter.health_check(_ctx(tenant, "privy"))
    assert healthy.success is True
    assert healthy.status is AdapterStatus.OK
    # Privy is webhook-only: signature verification IS its supported connection.
    assert healthy.data["status"] == "webhook_only"


# ── Factory / identity ───────────────────────────────────────────────────────


def test_payment_rail_adapter_for_builds_observe_identity():
    adapter = payment_rail_adapter_for("privy")

    assert isinstance(adapter, PaymentRailIntegrationAdapter)
    assert isinstance(adapter, IntegrationAdapter)
    assert adapter.manifest.identity_key == "privy.payment_rails.observe"
    assert adapter.manifest.capability_id == "observe"
    # Observe-only: the manifest never claims history backfill or reconciliation.
    assert adapter.manifest.sync.initial_backfill is False
    assert adapter.manifest.sync.reconciliation is False


def test_payment_rail_adapter_for_unknown_rail_raises():
    with pytest.raises(NotFoundError):
        payment_rail_adapter_for("definitely_not_a_rail")
