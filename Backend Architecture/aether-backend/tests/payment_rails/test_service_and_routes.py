"""Service pipeline + route tests: idempotency, status ordering, reconciliation,
canonical event emission, flag gating, tenant isolation, Kyber permissions."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from shared.common.common import BadRequestError, NotFoundError  # noqa: E402
from services.integrations.providers.payment_rails.base import (  # noqa: E402
    get_payment_rails_vault,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
    provider_enabled,
    require_provider_enabled,
)
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails import routes as rails_routes  # noqa: E402
from services.integrations.providers.payment_rails import kyber_routes as rails_kyber  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="function")


class RecordingProducer:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)

    async def publish_batch(self, events) -> None:
        self.events.extend(events)


class FakeTenant:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self.permissions = permissions if permissions is not None else {"read", "write", "admin"}

    def require_permission(self, permission: str) -> None:
        assert permission in self.permissions or "admin" in self.permissions


class FakeRequest:
    def __init__(self, tenant_id: str, headers: dict | None = None, body: bytes = b""):
        self.state = SimpleNamespace(tenant=FakeTenant(tenant_id), request_id="req-1")
        self.headers = headers or {}
        self._body = body

    async def body(self) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def _enable_rails(monkeypatch):
    patched = dataclasses.replace(
        settings.payment_rails,
        enabled=True, privy_enabled=True, stripe_enabled=True,
        coinbase_enabled=True, moonpay_enabled=True, bridge_enabled=True,
        kyber_enabled=True,
    )
    monkeypatch.setattr(settings, "payment_rails", patched)


@pytest.fixture()
def service():
    return PaymentRailsService(
        repositories=PaymentRailsRepositories(), producer=RecordingProducer()
    )


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _moonpay_body(tx_id: str, status: str, **extra) -> bytes:
    data = {"id": tx_id, "status": status,
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"},
            "walletAddress": "0xabc", **extra}
    return json.dumps({"type": "transaction_updated", "data": data}).encode()


async def _signed_webhook(service, tenant_id: str, body: bytes, provider: str = "moonpay"):
    secret = "whsec_" + tenant_id
    vault = get_payment_rails_vault()
    stored = await vault.get_key(tenant_id, f"payment_{provider}")
    if not stored:
        await vault.store_key(tenant_id, f"payment_{provider}", "payment", secret)
    timestamp = "1720500000"
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return await service.handle_webhook(tenant_id, provider, body, f"v1={signature}", timestamp)


class TestFlagGating:
    async def test_disabled_provider_rejected(self, monkeypatch):
        patched = dataclasses.replace(settings.payment_rails, enabled=True, moonpay_enabled=False)
        monkeypatch.setattr(settings, "payment_rails", patched)
        assert provider_enabled("moonpay") is False
        with pytest.raises(BadRequestError):
            require_provider_enabled("moonpay")

    async def test_master_flag_off_disables_everything(self, monkeypatch):
        patched = dataclasses.replace(settings.payment_rails, enabled=False, privy_enabled=True)
        monkeypatch.setattr(settings, "payment_rails", patched)
        assert provider_enabled("privy") is False

    async def test_unknown_provider_404_even_when_enabled(self):
        with pytest.raises(NotFoundError):
            require_provider_enabled("paypal")


class TestWebhookPipeline:
    async def test_full_flow_persists_session_and_emits_canonical_events(self, service):
        tenant_id = _tenant()
        result = await _signed_webhook(service, tenant_id, _moonpay_body("tx1", "completed"))
        assert result["handled"] is True
        event_result = result["events"][0]
        assert event_result["disposition"] == "created"
        assert event_result["status"] == "completed"
        emitted = [e.payload["event_type"] for e in service.producer.events]
        assert emitted == ["payment_initiated", "payment_completed"]
        # Canonical events flow on the validated-events bus, tenant-scoped.
        assert all(e.tenant_id == tenant_id for e in service.producer.events)
        assert all(e.topic.value == "aether.sdk.events.validated"
                   for e in service.producer.events)

    async def test_duplicate_delivery_never_double_counts(self, service):
        tenant_id = _tenant()
        body = _moonpay_body("tx2", "completed")
        await _signed_webhook(service, tenant_id, body)
        first_count = len(service.producer.events)
        result = await _signed_webhook(service, tenant_id, body)
        assert result["events"][0]["disposition"] == "ignored_duplicate"
        assert len(service.producer.events) == first_count  # no re-emission
        sessions = await service.repos.sessions.list_for_tenant(tenant_id)
        assert len(sessions) == 1

    async def test_out_of_order_final_state_never_regresses(self, service):
        tenant_id = _tenant()
        await _signed_webhook(service, tenant_id, _moonpay_body("tx3", "completed"))
        result = await _signed_webhook(service, tenant_id, _moonpay_body("tx3", "pending"))
        assert result["events"][0]["disposition"] == "downgrade_blocked"
        session = (await service.repos.sessions.list_for_tenant(tenant_id))[0]
        assert session["status"] == "completed"
        assert session["metadata"]["downgrade_attempts"]

    async def test_forward_progression_emits_terminal_event_once(self, service):
        tenant_id = _tenant()
        await _signed_webhook(service, tenant_id, _moonpay_body("tx4", "pending"))
        assert [e.payload["event_type"] for e in service.producer.events] == [
            "payment_initiated"
        ]
        await _signed_webhook(service, tenant_id, _moonpay_body("tx4", "completed"))
        emitted = [e.payload["event_type"] for e in service.producer.events]
        assert emitted == ["payment_initiated", "payment_completed"]

    async def test_bad_signature_rejected_and_audited(self, service):
        tenant_id = _tenant()
        vault = get_payment_rails_vault()
        await vault.store_key(tenant_id, "payment_moonpay", "payment", "whsec_x")
        result = await service.handle_webhook(
            tenant_id, "moonpay", _moonpay_body("tx5", "completed"), "v1=bad", "1720500000"
        )
        assert result["handled"] is False
        audits = await service.repos.audit.list_for_tenant(tenant_id)
        assert any(a["action"] == "webhook_rejected" for a in audits)

    async def test_unconfigured_tenant_webhook_rejected(self, service):
        result = await service.handle_webhook(
            _tenant(), "moonpay", _moonpay_body("tx6", "completed"), "v1=abc", "1"
        )
        assert result["handled"] is False


class TestStatusSync:
    async def test_polling_records_flow_through_pipeline(self, service):
        tenant_id = _tenant()
        result = await service.status_sync(tenant_id, "moonpay", records=[
            {"id": "poll1", "status": "completed", "baseCurrencyAmount": 10,
             "quoteCurrencyAmount": 9, "baseCurrency": {"code": "usd"},
             "currency": {"code": "usdc"}},
        ])
        assert result["synced"] is True
        sessions = await service.repos.sessions.list_for_tenant(tenant_id)
        assert len(sessions) == 1
        account = await service.repos.accounts.get(tenant_id, "moonpay")
        assert account and account.get("last_poll_at")


class TestReconciliation:
    async def test_provider_only_state_for_webhook_without_sdk_signal(self, service):
        tenant_id = _tenant()
        await _signed_webhook(service, tenant_id, _moonpay_body("tx7", "completed"))
        records = await service.repos.reconciliation.list_for_tenant(tenant_id)
        assert len(records) == 1
        assert records[0]["state"] in ("provider_only", "matched")

    async def test_health_reports_all_five_providers(self, service):
        tenant_id = _tenant()
        health = await service.health(tenant_id)
        assert {h.provider for h in health} == {"privy", "stripe", "coinbase", "moonpay", "bridge"}
        assert all(h.status == "not_configured" for h in health)


class TestTenantIsolation:
    async def test_sessions_are_tenant_scoped(self, service):
        tenant_a, tenant_b = _tenant(), _tenant()
        await _signed_webhook(service, tenant_a, _moonpay_body("tx8", "completed"))
        assert await service.repos.sessions.list_for_tenant(tenant_b) == []
        session_id = (await service.repos.sessions.list_for_tenant(tenant_a))[0]["id"]
        with pytest.raises(NotFoundError):
            await service.repos.sessions.get(tenant_b, session_id)


class TestRoutes:
    async def test_routes_reject_when_master_flag_off(self, monkeypatch):
        patched = dataclasses.replace(settings.payment_rails, enabled=False)
        monkeypatch.setattr(settings, "payment_rails", patched)
        with pytest.raises(BadRequestError):
            await rails_routes.payment_rails_health(FakeRequest(_tenant()))

    async def test_webhook_route_requires_tenant_header(self):
        request = FakeRequest(_tenant(), headers={}, body=b"{}")
        with pytest.raises(BadRequestError):
            await rails_routes.payment_rail_webhook("moonpay", request)

    async def test_session_list_unknown_provider_404(self):
        with pytest.raises(NotFoundError):
            await rails_routes.list_funding_sessions(
                FakeRequest(_tenant()), provider="paypal"
            )

    async def test_health_route_returns_five_providers(self, monkeypatch, service):
        monkeypatch.setattr(
            "services.integrations.providers.payment_rails.routes.get_payment_rails_service",
            lambda: service,
        )
        response = await rails_routes.payment_rails_health(FakeRequest(_tenant()))
        assert len(response["data"]["providers"]) == 5

    async def test_provider_status_not_configured_typed(self):
        response = await rails_routes.provider_status("privy", FakeRequest(_tenant()))
        assert response["data"]["configured"] is False

    async def test_kyber_routes_require_operator(self, monkeypatch):
        calls = []

        def _fake_operator(request):
            calls.append(request)
            return SimpleNamespace(operator_id="op-1")

        monkeypatch.setattr(
            "services.security.request_context.require_kyber_operator", _fake_operator
        )
        response = await rails_kyber.fleet_health(FakeRequest(_tenant()))
        assert calls, "operator check must run"
        assert "providers" in response["data"]

    async def test_kyber_fleet_has_no_raw_tenant_payloads(self, monkeypatch, service):
        monkeypatch.setattr(
            "services.security.request_context.require_kyber_operator",
            lambda request: SimpleNamespace(operator_id="op-1"),
        )
        monkeypatch.setattr(
            "services.integrations.providers.payment_rails.kyber_routes.get_payment_rails_service",
            lambda: service,
        )
        tenant_id = _tenant()
        await _signed_webhook(service, tenant_id, _moonpay_body("tx9", "completed"))
        response = await rails_kyber.fleet_health(FakeRequest("operator"))
        flat = json.dumps(response)
        assert "walletAddress" not in flat and "0xabc" not in flat


class TestSecretSafety:
    async def test_secret_never_in_responses_or_audit(self, service):
        tenant_id = _tenant()
        secret = "whsec_" + tenant_id
        await _signed_webhook(service, tenant_id, _moonpay_body("tx10", "completed"))
        health = [h.model_dump(mode="json") for h in await service.health(tenant_id)]
        audits = await service.repos.audit.list_for_tenant(tenant_id)
        flat = json.dumps({"health": health, "audits": audits})
        assert secret not in flat
