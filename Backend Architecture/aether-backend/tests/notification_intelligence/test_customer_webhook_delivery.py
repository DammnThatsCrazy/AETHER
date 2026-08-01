from __future__ import annotations

import time
from unittest.mock import patch

import httpx
import pytest

from repositories.repos import reset_in_memory_stores
from services.notification_intelligence.customer_webhook_delivery import (
    CustomerWebhookDeliveryRepository,
    CustomerWebhookDeliveryService,
    CustomerWebhookSecretStore,
    ResolvedDestination,
    WebhookPolicyError,
    make_idempotency_key,
    redact_webhook_record,
    resolve_safe_destination,
    sign_payload,
    verify_signature,
)


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _public_dns(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def test_secret_is_write_only_in_webhook_response():
    record = {
        "id": "wh-1",
        "tenant_id": "tenant-a",
        "url": "https://example.com/hook",
        "secret_ref": "customer_webhook:tenant-a:wh-1",
        "secret_hash": "hash-only",
        "secret": "never-return-this",
    }

    response = redact_webhook_record(record)

    assert response["secret_configured"] is True
    assert "secret" not in response
    assert "secret_ref" not in response
    assert "secret_hash" not in response


@pytest.mark.asyncio
async def test_secret_store_returns_reference_and_hash_only():
    class ProviderDouble:
        def __init__(self):
            self.rows = {}

        async def upsert(self, key, value):
            self.rows[key] = value

        async def find_by_id(self, key):
            return self.rows.get(key)

    providers = ProviderDouble()
    store = CustomerWebhookSecretStore(providers)

    record = await store.store("tenant-a", "wh-1", "write-only-secret")

    assert record["secret_ref"] == "customer_webhook:tenant-a:wh-1"
    assert "write-only-secret" not in record
    assert providers.rows[record["secret_ref"]]["api_key"] == "write-only-secret"
    assert await store.resolve("tenant-a", record["secret_ref"]) == "write-only-secret"
    with pytest.raises(RuntimeError, match="unavailable"):
        await store.resolve("tenant-b", record["secret_ref"])


def test_signature_requires_fresh_timestamp_and_detects_tampering():
    body = b'{"event":"created"}'
    timestamp = str(1_700_000_000)
    signature = sign_payload("secret", body, timestamp)

    assert verify_signature("secret", body, timestamp, signature, now=1_700_000_100)
    assert not verify_signature("secret", body, timestamp, signature, now=1_700_000_301)
    assert not verify_signature("secret", b"tampered", timestamp, signature, now=1_700_000_100)


@pytest.mark.parametrize("url", [
    "http://example.com/hook",
    "https://127.0.0.1/hook",
    "https://metadata.internal/hook",
])
def test_destination_policy_blocks_unsafe_production_destinations(monkeypatch, url):
    monkeypatch.setenv("AETHER_ENV", "production")
    with patch(
        "services.notification_intelligence.customer_webhook_delivery.socket.getaddrinfo",
        side_effect=lambda host, port, **kwargs: [(2, 1, 6, "", ("169.254.169.254" if "metadata" in host else host, port))],
    ):
        with pytest.raises(WebhookPolicyError):
            resolve_safe_destination(url)


def test_local_development_allows_only_local_http(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with patch(
        "services.notification_intelligence.customer_webhook_delivery.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 8080))],
    ):
        assert resolve_safe_destination("http://localhost:8080/hook").hostname == "localhost"


class _Response:
    def __init__(self, status_code: int, body: bytes = b"ok", headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    async def aiter_bytes(self):
        yield self._body


class _Stream:
    def __init__(self, response: _Response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        return False


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.calls = 0

    def stream(self, *_args, **_kwargs):
        self.calls += 1
        return _Stream(self.response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _factory_for(client: _Client):
    def factory(**_kwargs):
        return client
    return factory


@pytest.mark.asyncio
async def test_delivery_is_durable_idempotent_and_tenant_scoped(monkeypatch):
    # Repository-backed tests use the explicitly local-only repository mode;
    # destination policy itself is covered against production separately.
    monkeypatch.setenv("AETHER_ENV", "local")
    client = _Client(_Response(204))
    with patch(
        "services.notification_intelligence.customer_webhook_delivery.resolve_safe_destination",
        return_value=ResolvedDestination("https://example.com/hook", "example.com", 443, ("93.184.216.34",)),
    ):
        service = CustomerWebhookDeliveryService(
            attempts=CustomerWebhookDeliveryRepository(),
            http_client_factory=_factory_for(client),
            sleeper=lambda _seconds: __import__("asyncio").sleep(0),
        )
        first = await service.deliver(
            tenant_id="tenant-a", webhook_id="wh-1", url="https://example.com/hook",
            payload={"event": "created"}, secret="secret", event_id="event-1",
        )
        second = await service.deliver(
            tenant_id="tenant-a", webhook_id="wh-1", url="https://example.com/hook",
            payload={"event": "created"}, secret="secret", event_id="event-1",
        )

    assert first.success and second.success
    assert first.idempotency_key == second.idempotency_key
    assert client.calls == 1
    rows = await service.attempts.find_for_webhook("tenant-a", "wh-1")
    assert rows[0]["status"] == "delivered"
    assert await service.attempts.find_for_webhook("tenant-b", "wh-1") == []


@pytest.mark.asyncio
async def test_redirect_and_response_size_are_blocked(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    for response in (
        _Response(302, headers={"location": "https://other.example/hook"}),
        _Response(200, body=b"x" * (64 * 1024 + 1)),
    ):
        client = _Client(response)
        with patch(
            "services.notification_intelligence.customer_webhook_delivery.resolve_safe_destination",
            return_value=ResolvedDestination("https://example.com/hook", "example.com", 443, ("93.184.216.34",)),
        ):
            service = CustomerWebhookDeliveryService(
                attempts=CustomerWebhookDeliveryRepository(),
                http_client_factory=_factory_for(client),
                sleeper=lambda _seconds: __import__("asyncio").sleep(0),
            )
            result = await service.deliver(
                tenant_id="tenant-a", webhook_id="wh-1", url="https://example.com/hook",
                payload={"event": "created"}, secret="secret", event_id=str(time.time()),
            )
        assert not result.success
        assert result.status == "blocked"


@pytest.mark.asyncio
async def test_timeout_policy_is_bounded_and_retried(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    options = {}

    class TimeoutClient(_Client):
        def stream(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("simulated timeout")

    def factory(**kwargs):
        options.update(kwargs)
        return TimeoutClient(_Response(200))

    with patch(
        "services.notification_intelligence.customer_webhook_delivery.resolve_safe_destination",
        return_value=ResolvedDestination("https://example.com/hook", "example.com", 443, ("93.184.216.34",)),
    ):
        service = CustomerWebhookDeliveryService(
            attempts=CustomerWebhookDeliveryRepository(),
            http_client_factory=factory,
            sleeper=lambda _seconds: __import__("asyncio").sleep(0),
        )
        result = await service.deliver(
            tenant_id="tenant-a", webhook_id="wh-1", url="https://example.com/hook",
            payload={"event": "created"}, secret="secret", event_id="timeout-event",
        )

    assert result.status == "failed"
    assert result.attempts == 3
    assert options["follow_redirects"] is False
    assert options["max_redirects"] == 0
    assert options["timeout"].connect == 3.0
    assert options["timeout"].read == 15.0


@pytest.mark.asyncio
async def test_missing_secret_is_explicit_provider_unavailable(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with patch(
        "services.notification_intelligence.customer_webhook_delivery.resolve_safe_destination",
        return_value=ResolvedDestination("https://example.com/hook", "example.com", 443, ("93.184.216.34",)),
    ):
        result = await CustomerWebhookDeliveryService().deliver(
            tenant_id="tenant-a", webhook_id="wh-1", url="https://example.com/hook",
            payload={"event": "created"}, secret="", event_id="event-1",
        )
    assert result.status == "provider_unavailable"
    assert not result.success


def test_idempotency_key_is_tenant_and_endpoint_scoped():
    assert make_idempotency_key("tenant-a", "wh-1", "event-1") != make_idempotency_key("tenant-b", "wh-1", "event-1")
    assert make_idempotency_key("tenant-a", "wh-1", "event-1") != make_idempotency_key("tenant-a", "wh-2", "event-1")
