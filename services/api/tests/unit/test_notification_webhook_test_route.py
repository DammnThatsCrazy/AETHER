"""Tenant-scoped Access Kit webhooks use encrypted secrets and the hardened delivery service."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import repositories.repos as repos_mod
from journeys.notification_intelligence import customer_webhook_delivery as delivery_mod
from journeys.notification_intelligence import routes as ni_routes
from shared.common.common import ForbiddenError, NotFoundError


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"

    def __init__(self):
        self.permissions = []

    def require_permission(self, permission):
        self.permissions.append(permission)


def _req(tenant_id="tenant-a"):
    tenant = _Tenant()
    tenant.tenant_id = tenant_id
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


def _repos(monkeypatch, records=None):
    records = records if records is not None else {}
    provider_records = {}

    class Webhooks:
        async def insert(self, record_id, data):
            data["id"] = record_id
            records[record_id] = data
            return data

        async def find_by_id(self, record_id):
            return records.get(record_id)

        async def find_many(self, filters=None, limit=50, offset=0, sort_by=None, sort_order="desc"):
            found = [row for row in records.values() if all(row.get(k) == v for k, v in (filters or {}).items())]
            return found[offset:offset + limit]

        async def update(self, record_id, data):
            records[record_id].update(data)
            return records[record_id]

        async def delete(self, record_id):
            return records.pop(record_id, None) is not None

    class Providers:
        async def delete(self, record_id):
            return provider_records.pop(record_id, None) is not None

    monkeypatch.setattr(repos_mod, "WebhookRepository", Webhooks)
    monkeypatch.setattr(repos_mod, "ProvidersRepository", Providers)
    return records, provider_records


def _fake_secret_store(monkeypatch):
    class SecretStore:
        def __init__(self, _repository):
            pass

        async def store(self, tenant_id, webhook_id, secret=None):
            return {
                "secret_ref": f"customer_webhook:{tenant_id}:{webhook_id}",
                "secret_hash": "safe-hash",
                "secret_configured": True,
            }

        async def resolve(self, _tenant_id, _secret_ref):
            return "generated-signing-secret-value"

    monkeypatch.setattr(delivery_mod, "CustomerWebhookSecretStore", SecretStore)
    return SecretStore


def test_create_webhook_encrypts_secret_reference_and_returns_secret_once(monkeypatch):
    records, _providers = _repos(monkeypatch)
    _fake_secret_store(monkeypatch)
    monkeypatch.setattr(delivery_mod, "resolve_safe_destination", lambda _url: object())
    monkeypatch.setattr(ni_routes.secrets, "token_urlsafe", lambda _length: "generated-signing-secret-value")
    request = _req()
    body = ni_routes._WebhookConfig(
        url="https://hooks.example.test/aether",
        events=["access.interaction.completed"],
    )

    result = _run(ni_routes.create_webhook(body, request))["data"]
    saved = records[result["id"]]
    assert result["secret"] == "generated-signing-secret-value"
    assert result["active"] is False
    assert result["status"] == "pending_test"
    assert saved["secret_ref"].startswith("customer_webhook:tenant-a:")
    assert "secret" not in saved
    assert "secret_ref" not in result
    assert "secret_hash" not in result
    assert request.state.tenant.permissions == ["write"]


def test_webhook_contract_rejects_unbounded_or_unrelated_event_types():
    with pytest.raises(ValueError):
        ni_routes._WebhookConfig(url="https://hooks.example.test", events=["entity.created"])
    with pytest.raises(ValueError):
        ni_routes._WebhookConfig(url="https://hooks.example.test", events=[])


def test_create_rejects_private_destinations_before_secret_or_record_write(monkeypatch):
    records, _providers = _repos(monkeypatch)
    _fake_secret_store(monkeypatch)

    def reject(_url):
        raise delivery_mod.WebhookPolicyError("blocked")

    monkeypatch.setattr(delivery_mod, "resolve_safe_destination", reject)
    body = ni_routes._WebhookConfig(
        url="http://127.0.0.1/hook", events=["access.interaction.completed"],
    )
    with pytest.raises(Exception, match="public HTTPS"):
        _run(ni_routes.create_webhook(body, _req()))
    assert records == {}


def test_list_webhooks_redacts_all_secret_fields(monkeypatch):
    records, _providers = _repos(monkeypatch, {
        "wh-1": {
            "id": "wh-1", "tenant_id": "tenant-a", "url": "https://hooks.example.test",
            "events": ["access.interaction.completed"], "active": True,
            "secret": "legacy-raw-secret", "secret_ref": "private-reference",
            "secret_hash": "private-hash", "created_at": "2026-10-12T00:00:00Z",
        },
    })
    result = _run(ni_routes.list_webhooks(_req(), limit=50, offset=0))["data"]
    assert result["pagination"]["total"] == 1
    hook = result["webhooks"][0]
    assert hook["secret_configured"] is True
    assert not {"secret", "secret_ref", "secret_hash"} & hook.keys()
    assert "legacy-raw-secret" not in str(result)


def test_test_webhook_uses_hardened_signed_service_and_activates_only_on_success(monkeypatch):
    records, _providers = _repos(monkeypatch, {
        "wh-1": {
            "id": "wh-1", "tenant_id": "tenant-a", "url": "https://hooks.example.test",
            "events": ["access.interaction.completed"], "active": False,
            "secret_ref": "customer_webhook:tenant-a:wh-1",
        },
    })
    _fake_secret_store(monkeypatch)
    deliveries = []

    class Service:
        async def test(self, **kwargs):
            deliveries.append(kwargs)
            return delivery_mod.WebhookDeliveryOutcome(
                status="delivered", success=True, webhook_id="wh-1", tenant_id="tenant-a",
                idempotency_key="test-key", attempts=1, status_code=204,
                latency_ms=12.0, attempt_id="attempt-1",
            )

    monkeypatch.setattr(delivery_mod, "CustomerWebhookDeliveryService", Service)
    request = _req()
    result = _run(ni_routes.test_webhook("wh-1", request))["data"]
    assert result["success"] is True
    assert result["status_code"] == 204
    assert result["webhook"]["active"] is True
    assert records["wh-1"]["verification_status"] == "verified"
    assert deliveries[0]["secret"] == "generated-signing-secret-value"
    assert deliveries[0]["url"] == "https://hooks.example.test"
    assert request.state.tenant.permissions == ["write"]


def test_test_webhook_denies_cross_tenant_and_does_not_dispatch(monkeypatch):
    _repos(monkeypatch, {
        "wh-1": {"id": "wh-1", "tenant_id": "other", "url": "https://hooks.example.test"},
    })
    class Service:
        async def test(self, **_kwargs):
            raise AssertionError("cross-tenant webhook must never dispatch")

    monkeypatch.setattr(delivery_mod, "CustomerWebhookDeliveryService", Service)
    with pytest.raises(ForbiddenError):
        _run(ni_routes.test_webhook("wh-1", _req()))


def test_delete_webhook_removes_tenant_owned_vault_reference(monkeypatch):
    _records, providers = _repos(monkeypatch, {
        "wh-1": {"id": "wh-1", "tenant_id": "tenant-a", "secret_ref": "customer_webhook:tenant-a:wh-1"},
    })
    providers["customer_webhook:tenant-a:wh-1"] = {"encrypted_api_key": "ciphertext"}
    result = _run(ni_routes.delete_webhook("wh-1", _req()))["data"]
    assert result == {"deleted": True}
    assert "wh-1" not in _records
    assert providers == {}


def test_rotate_webhook_secret_pauses_delivery_before_replacing_vault_value(monkeypatch):
    records, _providers = _repos(monkeypatch, {
        "wh-1": {
            "id": "wh-1", "tenant_id": "tenant-a", "url": "https://hooks.example.test",
            "events": ["access.interaction.completed"], "active": True,
            "status": "active", "secret_ref": "customer_webhook:tenant-a:wh-1",
        },
    })
    store = _fake_secret_store(monkeypatch)
    state = {}

    class CheckingSecretStore(store):
        async def store(self, tenant_id, webhook_id, secret=None):
            state["paused_before_store"] = records[webhook_id]["active"] is False
            return await super().store(tenant_id, webhook_id, secret)

    monkeypatch.setattr(delivery_mod, "CustomerWebhookSecretStore", CheckingSecretStore)
    monkeypatch.setattr(ni_routes.secrets, "token_urlsafe", lambda _length: "rotated-signing-secret-value")
    result = _run(ni_routes.rotate_webhook_secret("wh-1", _req()))["data"]

    assert state["paused_before_store"] is True
    assert result["secret"] == "rotated-signing-secret-value"
    assert result["active"] is False
    assert result["status"] == "pending_test"
    assert "secret_ref" not in result and "secret_hash" not in result


def test_delivery_history_is_tenant_scoped_and_minimized(monkeypatch):
    _repos(monkeypatch, {"wh-1": {"id": "wh-1", "tenant_id": "tenant-a"}})

    class Outbox:
        async def find_many(self, **kwargs):
            assert kwargs["filters"] == {
                "tenant_id": "tenant-a", "channel": "customer_webhook:wh-1",
            }
            return [{
                "id": "access-row-1", "created_at": "2026-10-12T00:00:00Z",
                "status": "delivered", "attempts": 1,
                "notification": {"id": "request-1", "type": "access.interaction.completed"},
                "delivery": {"status": "delivered", "status_code": 204, "error": None},
                "tenant_id": "private", "url": "private",
            }]

    monkeypatch.setattr(
        "journeys.notification_intelligence.delivery_outbox.get_delivery_outbox_repository",
        lambda: Outbox(),
    )
    result = _run(ni_routes.list_webhook_deliveries("wh-1", _req()))["data"]
    assert result["count"] == 1
    assert result["items"][0]["event_type"] == "access.interaction.completed"
    assert "tenant_id" not in result["items"][0]
    assert "url" not in result["items"][0]


def test_delivery_history_rejects_cross_tenant_webhook(monkeypatch):
    _repos(monkeypatch, {"wh-1": {"id": "wh-1", "tenant_id": "other"}})
    with pytest.raises(ForbiddenError):
        _run(ni_routes.list_webhook_deliveries("wh-1", _req()))


def test_missing_webhook_returns_not_found(monkeypatch):
    _repos(monkeypatch)
    with pytest.raises(NotFoundError):
        _run(ni_routes.test_webhook("wh-missing", _req()))
