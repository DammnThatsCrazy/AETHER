"""Credentialless certification of the five payment-rail adapters.

Runs ``shared.certification.run_certification`` against each adapter's honest
descriptor + duck-typed hooks (offline, no credentials) and asserts:
- every check passes (skips are allowed; failures are not),
- behavioural checks actually RUN (secret redaction, dedupe, ordering,
  normalize idempotency, health) rather than all skipping,
- implementation_state is the honest CREDENTIAL_WAITING for all five,
- Privy + Stripe are classified ``webhook_only`` (capability flag + connection
  test + descriptor unsupported ops), a supported terminal state,
- the three pull adapters declare pagination + status_poll/backfill support.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.certification import (  # noqa: E402
    AdapterCertificationDescriptor,
    CredentialReadiness,
    run_certification,
)
from services.integrations.providers.payment_rails import (  # noqa: E402
    ADAPTERS,
    PROVIDER_NAMES,
)
from services.integrations.providers.payment_rails.base import (  # noqa: E402
    get_payment_rails_vault,
)

pytestmark = pytest.mark.asyncio


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


# Real provider webhook payloads so normalize-based checks exercise a genuine
# normalization (idempotent replay, schema drift) rather than trivially None.
_NORMALIZE_SAMPLE = {
    "privy": {
        "type": "funding.completed",
        "data": {"funding_id": "f1", "status": "completed", "flow": "fiat_onramp",
                 "amount": "100", "source_currency": "usd", "asset": "usdc"},
    },
    "stripe": {
        "type": "crypto.onramp_session_updated",
        "data": {"object": {"id": "cos_1", "status": "fulfillment_complete",
                            "transaction_details": {"destination_currency": "usdc",
                                                    "destination_amount": "10"}}},
    },
    "coinbase": {
        "event_type": "onramp.transaction.updated",
        "transaction": {"transaction_id": "cb1", "status": "success",
                        "purchase_currency": "USDC", "purchase_network": "base",
                        "partner_user_ref": "u1"},
    },
    "moonpay": {
        "type": "transaction_updated",
        "data": {"id": "mp1", "status": "completed", "baseCurrency": {"code": "usd"},
                 "currency": {"code": "usdc"}, "baseCurrencyAmount": 100,
                 "quoteCurrencyAmount": 95},
    },
    "bridge": {
        "event_type": "virtual_account.activity",
        "event_object": {"id": "act1", "type": "payment_processed", "status": "processed",
                         "amount": "250.00", "currency": "usd",
                         "source": {"payment_rail": "ach", "currency": "usd"},
                         "destination": {"currency": "usdc", "payment_rail": "base"}},
    },
}


def _ctx(name: str) -> dict:
    return {"timeout_seconds": 15.0, "normalize_sample": _NORMALIZE_SAMPLE[name]}


class TestCertification:
    @pytest.mark.parametrize("name", list(PROVIDER_NAMES))
    def test_all_checks_pass(self, name):
        results = run_certification(ADAPTERS[name], _ctx(name))
        failed = [(r.name, r.detail) for r in results if not r.passed]
        assert not failed, f"{name} certification failures: {failed}"

    @pytest.mark.parametrize("name", list(PROVIDER_NAMES))
    def test_behavioral_checks_actually_run(self, name):
        results = run_certification(ADAPTERS[name], _ctx(name))
        ran = {r.name for r in results if not r.skipped}
        # These behavioural hooks are exposed by every adapter, so they must RUN.
        for required in (
            "secret_redaction", "duplicate_handling", "out_of_order_handling",
            "schema_drift", "malformed_input", "idempotent_replay",
            "health_transitions",
        ):
            assert required in ran, f"{name}: {required} did not run (got {sorted(ran)})"

    @pytest.mark.parametrize("name", list(PROVIDER_NAMES))
    def test_descriptor_is_honest_credential_waiting(self, name):
        d = ADAPTERS[name].certification_descriptor()
        assert isinstance(d, AdapterCertificationDescriptor)
        assert d.implementation_state is CredentialReadiness.CREDENTIAL_WAITING
        assert d.provider == name and d.domain == "payments"
        assert d.streaming_model == "webhook"
        assert d.required_credentials, "must declare required credentials"
        assert d.secret_ref_names, "must declare a vault secret ref"
        assert set(d.expected_webhook_headers) >= {"signature", "timestamp"}
        assert d.retry_policy and d.retry_policy != "unspecified"
        assert d.rate_limit_behavior and d.rate_limit_behavior != "unspecified"
        assert d.first_release is True


class TestWebhookOnlyClassification:
    @pytest.mark.parametrize("name", ["privy", "stripe"])
    async def test_webhook_only_terminal_state(self, name):
        adapter = ADAPTERS[name]
        assert adapter.webhook_only is True
        assert adapter.polling_supported is False

        d = adapter.certification_descriptor()
        assert "status_poll" in d.unsupported_operations
        assert "backfill" in d.unsupported_operations
        assert d.pagination_model == "none"
        assert "webhook_ingest" in d.supported_operations

        tenant_id = _tenant()
        await get_payment_rails_vault().store_key(
            tenant_id, adapter.vault_provider_name, "payment", "whsec_x"
        )
        result = await adapter.test_connection(tenant_id)
        assert result.status == "webhook_only"
        assert result.ok is True  # supported terminal state, not an error

    async def test_unconfigured_webhook_only_is_not_configured(self):
        # Missing secret still resolves to a typed not_configured, never 500.
        result = await ADAPTERS["privy"].test_connection(_tenant())
        assert result.status == "not_configured" and result.ok is False


class TestPullClassification:
    @pytest.mark.parametrize(
        "name,pagination",
        [("coinbase", "cursor"), ("moonpay", "time_window"), ("bridge", "cursor")],
    )
    def test_pull_descriptor_declares_polling(self, name, pagination):
        adapter = ADAPTERS[name]
        assert adapter.polling_supported is True
        assert adapter.webhook_only is False
        d = adapter.certification_descriptor()
        assert d.pagination_model == pagination
        assert "status_poll" in d.supported_operations
        assert "backfill" in d.supported_operations

    async def test_pull_connection_test_not_configured_without_secret(self):
        # Non-local live check with no credential -> typed not_configured.
        result = await ADAPTERS["coinbase"]._live_connection_test(_tenant())
        assert result.status == "not_configured" and result.ok is False
