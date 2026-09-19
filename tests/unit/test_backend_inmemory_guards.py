from __future__ import annotations

import asyncio
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "backend"


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in ("config", "services", "shared"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in ("config", "services", "shared"):
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def test_shared_store_rejects_inmemory_outside_local(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://aether:test@localhost:5432/aether")
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "test-byok-key-for-testing")
    monkeypatch.setenv("WATERMARK_SECRET_KEY", "test-watermark-secret-key-for-tests")
    monkeypatch.setenv("CANARY_SECRET_SEED", "test-canary-secret-seed-for-tests")
    monkeypatch.setenv("EXTRACTION_CANARY_SEED", "test-extraction-canary-seed-for-tests")
    monkeypatch.setenv("SDK_CONFIG_SECRET", "test-sdk-config-secret-for-tests")
    # Kyber workforce SSO/WebAuthn anchors. A non-local Settings() already requires
    # seven secrets; these are the same kind. The guard itself is covered by
    # tests/security/test_kyber_gate_migration.py — this test must trip only
    # the guard it is actually testing.
    monkeypatch.setenv("KYBER_GOOGLE_CLIENT_ID", "test-kyber-client-id")
    monkeypatch.setenv("KYBER_GOOGLE_REDIRECT_URI", "https://kyber.test.invalid/v1/kyber/auth/callback")
    monkeypatch.setenv("KYBER_WEBAUTHN_RP_ID", "kyber.test.invalid")
    monkeypatch.setenv("KYBER_WEBAUTHN_ORIGIN", "https://kyber.test.invalid")
    # PR 4: production requires an explicit role + non-memory core backends.
    monkeypatch.setenv("AETHER_ROLE", "api")
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("AETHER_ALLOW_INMEMORY_STORE", raising=False)

    with backend_module_path():
        module = importlib.import_module("shared.store")
        importlib.reload(module)

        with pytest.raises(RuntimeError, match="In-memory store 'campaign_touchpoints'"):
            module.get_store("campaign_touchpoints")


class _FakeDynamoTable:
    def __init__(self):
        self.items = {}

    def get_item(self, *, Key, **_kwargs):
        item = self.items.get(Key["cache_key"])
        return {"Item": dict(item)} if item else {}

    def put_item(self, *, Item, **_kwargs):
        self.items[Item["cache_key"]] = dict(Item)

    def delete_item(self, *, Key, **kwargs):
        item = self.items.pop(Key["cache_key"], None)
        return {"Attributes": item} if kwargs.get("ReturnValues") == "ALL_OLD" and item else {}

    def update_item(self, *, Key, ExpressionAttributeValues, **_kwargs):
        item = self.items.setdefault(Key["cache_key"], {"cache_key": Key["cache_key"]})
        item.setdefault("items", []).extend(ExpressionAttributeValues[":item"])

    def scan(self, **_kwargs):
        return {"Items": [dict(item) for item in self.items.values()]}


class _FakeDynamoResource:
    def __init__(self, table):
        self.table = table

    def Table(self, _name):
        return self.table


class _FakeBoto3:
    def __init__(self, table):
        self.resource_instance = _FakeDynamoResource(table)

    def resource(self, service):
        assert service == "dynamodb"
        return self.resource_instance


def test_shared_store_uses_dynamodb_for_the_lean_cache_backend(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://aether:test@localhost:5432/aether")
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "test-byok-key-for-testing")
    monkeypatch.setenv("WATERMARK_SECRET_KEY", "test-watermark-secret-key-for-tests")
    monkeypatch.setenv("CANARY_SECRET_SEED", "test-canary-secret-seed-for-tests")
    monkeypatch.setenv("EXTRACTION_CANARY_SEED", "test-extraction-canary-seed-for-tests")
    monkeypatch.setenv("SDK_CONFIG_SECRET", "test-sdk-config-secret-for-tests")
    monkeypatch.setenv("KYBER_GOOGLE_CLIENT_ID", "test-kyber-client-id")
    monkeypatch.setenv(
        "KYBER_GOOGLE_REDIRECT_URI",
        "https://kyber.test.invalid/v1/kyber/auth/callback",
    )
    monkeypatch.setenv("KYBER_WEBAUTHN_RP_ID", "kyber.test.invalid")
    monkeypatch.setenv("KYBER_WEBAUTHN_ORIGIN", "https://kyber.test.invalid")
    monkeypatch.setenv("AETHER_ROLE", "api")
    monkeypatch.setenv("CACHE_BACKEND", "dynamodb")
    monkeypatch.setenv("DYNAMODB_CACHE_TABLE", "AETHER-staging-cache")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    with backend_module_path():
        module = importlib.import_module("shared.store")
        importlib.reload(module)
        table = _FakeDynamoTable()
        monkeypatch.setattr(module, "_boto3_store", _FakeBoto3(table))

        store = module.get_store("observability_traces")
        assert isinstance(store, module.DynamoDBStore)

        async def exercise_store():
            await store.set("record-1", {"tenant_id": "tenant-a", "status": "ok"})
            assert await store.get("record-1") == {
                "tenant_id": "tenant-a",
                "status": "ok",
            }
            await store.append_list("traces:tenant-a", {"request_id": "req-1"})
            await store.append_list("traces:tenant-a", {"request_id": "req-2"})
            assert await store.get_list("traces:tenant-a") == [
                {"request_id": "req-1"},
                {"request_id": "req-2"},
            ]
            assert await store.find(status="ok") == [
                {"tenant_id": "tenant-a", "status": "ok"},
            ]
            assert await store.delete("record-1") is True
            assert await store.get("record-1") is None

        asyncio.run(exercise_store())


def test_journey_store_rejects_inmemory_outside_local(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://aether:test@localhost:5432/aether")
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "test-byok-key-for-testing")
    monkeypatch.setenv("WATERMARK_SECRET_KEY", "test-watermark-secret-key-for-tests")
    monkeypatch.setenv("CANARY_SECRET_SEED", "test-canary-secret-seed-for-tests")
    monkeypatch.setenv("EXTRACTION_CANARY_SEED", "test-extraction-canary-seed-for-tests")
    monkeypatch.setenv("SDK_CONFIG_SECRET", "test-sdk-config-secret-for-tests")
    # Kyber workforce SSO/WebAuthn anchors. A non-local Settings() already requires
    # seven secrets; these are the same kind. The guard itself is covered by
    # tests/security/test_kyber_gate_migration.py — this test must trip only
    # the guard it is actually testing.
    monkeypatch.setenv("KYBER_GOOGLE_CLIENT_ID", "test-kyber-client-id")
    monkeypatch.setenv("KYBER_GOOGLE_REDIRECT_URI", "https://kyber.test.invalid/v1/kyber/auth/callback")
    monkeypatch.setenv("KYBER_WEBAUTHN_RP_ID", "kyber.test.invalid")
    monkeypatch.setenv("KYBER_WEBAUTHN_ORIGIN", "https://kyber.test.invalid")
    # PR 4: production requires an explicit role + non-memory core backends.
    monkeypatch.setenv("AETHER_ROLE", "api")
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.delenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", raising=False)

    with backend_module_path():
        module = importlib.import_module("services.attribution.resolver")
        importlib.reload(module)

        with pytest.raises(RuntimeError, match="JourneyStore is disabled outside local mode"):
            module.JourneyStore()
