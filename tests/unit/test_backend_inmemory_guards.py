from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
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
        if ":touchpoint" in ExpressionAttributeValues:
            item["tenant_id"] = ExpressionAttributeValues[":tenant_id"]
            item["user_id"] = ExpressionAttributeValues[":user_id"]
            item.setdefault("touchpoints", []).extend(
                ExpressionAttributeValues[":touchpoint"]
            )
        else:
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


class _FakeRedisPipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.operations = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def rpush(self, key, value):
        self.operations.append(("rpush", key, value))
        return self

    def sadd(self, key, value):
        self.operations.append(("sadd", key, value))
        return self

    def llen(self, key):
        self.operations.append(("llen", key))
        return self

    def delete(self, key):
        self.operations.append(("delete", key))
        return self

    def srem(self, key, value):
        self.operations.append(("srem", key, value))
        return self

    def execute(self):
        return [getattr(self.redis_client, operation[0])(*operation[1:]) for operation in self.operations]


class _FakeRedis:
    def __init__(self):
        self.lists = {}
        self.sets = {}

    @classmethod
    def from_url(cls, _url, **_kwargs):
        return cls()

    def pipeline(self, *, transaction):
        assert transaction is True
        return _FakeRedisPipeline(self)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def sadd(self, key, value):
        values = self.sets.setdefault(key, set())
        before = len(values)
        values.add(value)
        return int(len(values) != before)

    def llen(self, key):
        return len(self.lists.get(key, []))

    def lrange(self, key, _start, _end):
        return list(self.lists.get(key, []))

    def delete(self, key):
        return int(self.lists.pop(key, None) is not None)

    def srem(self, key, value):
        values = self.sets.get(key, set())
        before = len(values)
        values.discard(value)
        return int(len(values) != before)

    def smembers(self, key):
        return set(self.sets.get(key, set()))


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
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.delenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", raising=False)

    with backend_module_path():
        module = importlib.import_module("services.attribution.resolver")
        importlib.reload(module)

        with pytest.raises(RuntimeError, match="JourneyStore is disabled outside local mode"):
            module.JourneyStore()


def test_journey_store_uses_dynamodb_for_staging_and_preserves_tenant_isolation(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.setenv("AETHER_ROLE", "api")
    monkeypatch.setenv("CACHE_BACKEND", "dynamodb")
    monkeypatch.setenv("DYNAMODB_CACHE_TABLE", "AETHER-staging-cache")
    monkeypatch.delenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", raising=False)
    for key, value in {
        "JWT_SECRET": "test-secret",
        "DATABASE_URL": "postgresql://aether:test@localhost:5432/aether",
        "BYOK_ENCRYPTION_KEY": "test-byok-key-for-testing",
        "WATERMARK_SECRET_KEY": "test-watermark-secret-key-for-tests",
        "CANARY_SECRET_SEED": "test-canary-secret-seed-for-tests",
        "EXTRACTION_CANARY_SEED": "test-extraction-canary-seed-for-tests",
        "SDK_CONFIG_SECRET": "test-sdk-config-secret-for-tests",
        "KYBER_GOOGLE_CLIENT_ID": "test-kyber-client-id",
        "KYBER_GOOGLE_REDIRECT_URI": "https://kyber.test.invalid/v1/kyber/auth/callback",
        "KYBER_WEBAUTHN_RP_ID": "kyber.test.invalid",
        "KYBER_WEBAUTHN_ORIGIN": "https://kyber.test.invalid",
    }.items():
        monkeypatch.setenv(key, value)

    with backend_module_path():
        module = importlib.import_module("services.attribution.resolver")
        importlib.reload(module)
        table = _FakeDynamoTable()
        monkeypatch.setattr(module, "_boto3_journey", _FakeBoto3(table))

        store = module.JourneyStore()
        touchpoint = {
            "channel": "social",
            "source": "test",
            "campaign": "",
            "event_type": "click",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        store.add("tenant-a", "user-1", touchpoint)
        store.add("tenant-a", "user-1", {**touchpoint, "channel": "email"})
        store.add("tenant-b", "user-1", {**touchpoint, "channel": "organic"})

        assert store.count("tenant-a", "user-1") == 2
        assert [item["channel"] for item in store.get("tenant-a", "user-1")] == [
            "social",
            "email",
        ]
        assert [item["channel"] for item in store.get("tenant-b", "user-1")] == [
            "organic",
        ]
        assert store.all_user_ids("tenant-a") == ["user-1"]
        assert store.clear("tenant-a", "user-1") == 2
        assert store.get("tenant-a", "user-1") == []
        assert store.get("tenant-b", "user-1")


def test_journey_store_uses_redis_for_scale_profiles_and_preserves_tenant_isolation(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("AETHER_ROLE", "api")
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://redis.test.invalid:6379/0")
    monkeypatch.delenv("DYNAMODB_CACHE_TABLE", raising=False)
    monkeypatch.delenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", raising=False)
    for key, value in {
        "JWT_SECRET": "test-secret",
        "DATABASE_URL": "postgresql://aether:test@localhost:5432/aether",
        "BYOK_ENCRYPTION_KEY": "test-byok-key-for-testing",
        "WATERMARK_SECRET_KEY": "test-watermark-secret-key-for-tests",
        "CANARY_SECRET_SEED": "test-canary-secret-seed-for-tests",
        "EXTRACTION_CANARY_SEED": "test-extraction-canary-seed-for-tests",
        "SDK_CONFIG_SECRET": "test-sdk-config-secret-for-tests",
        "KYBER_GOOGLE_CLIENT_ID": "test-kyber-client-id",
        "KYBER_GOOGLE_REDIRECT_URI": "https://kyber.test.invalid/v1/kyber/auth/callback",
        "KYBER_WEBAUTHN_RP_ID": "kyber.test.invalid",
        "KYBER_WEBAUTHN_ORIGIN": "https://kyber.test.invalid",
    }.items():
        monkeypatch.setenv(key, value)

    with backend_module_path():
        module = importlib.import_module("services.attribution.resolver")
        importlib.reload(module)
        fake_redis = _FakeRedis()

        class _RedisModule:
            Redis = fake_redis

        monkeypatch.setattr(module, "_redis_journey", _RedisModule)
        store = module.JourneyStore()
        touchpoint = {
            "channel": "social",
            "source": "test",
            "campaign": "",
            "event_type": "click",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        store.add("tenant-a", "user-1", touchpoint)
        store.add("tenant-a", "user-1", {**touchpoint, "channel": "email"})
        store.add("tenant-b", "user-1", {**touchpoint, "channel": "organic"})

        assert store.count("tenant-a", "user-1") == 2
        assert [item["channel"] for item in store.get("tenant-a", "user-1")] == [
            "social",
            "email",
        ]
        assert [item["channel"] for item in store.get("tenant-b", "user-1")] == [
            "organic",
        ]
        assert store.all_user_ids("tenant-a") == ["user-1"]
        assert store.clear("tenant-a", "user-1") == 2
        assert store.get("tenant-a", "user-1") == []
        assert store.get("tenant-b", "user-1")


def test_hosted_redis_store_is_constructible_with_auth_without_memory_fallback(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("AETHER_ROLE", "api")
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    for key, value in {
        "JWT_SECRET": "test-secret",
        "DATABASE_URL": "postgresql://aether:test@localhost:5432/aether",
        "BYOK_ENCRYPTION_KEY": "test-byok-key-for-testing",
        "WATERMARK_SECRET_KEY": "test-watermark-secret-key-for-tests",
        "CANARY_SECRET_SEED": "test-canary-secret-seed-for-tests",
        "EXTRACTION_CANARY_SEED": "test-extraction-canary-seed-for-tests",
        "SDK_CONFIG_SECRET": "test-sdk-config-secret-for-tests",
        "KYBER_GOOGLE_CLIENT_ID": "test-kyber-client-id",
        "KYBER_GOOGLE_REDIRECT_URI": "https://kyber.test.invalid/v1/kyber/auth/callback",
        "KYBER_WEBAUTHN_RP_ID": "kyber.test.invalid",
        "KYBER_WEBAUTHN_ORIGIN": "https://kyber.test.invalid",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("REDIS_HOST", "redis.test.invalid")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_DB", "2")
    monkeypatch.setenv("REDIS_PASSWORD", "p@ssword")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DYNAMODB_CACHE_TABLE", raising=False)

    with backend_module_path():
        module = importlib.import_module("shared.store")
        importlib.reload(module)
        store = module.get_store("hosted-redis-regression")

        assert isinstance(store, module.RedisStore)
        assert store._redis_url == "redis://:p%40ssword@redis.test.invalid:6379/2"
        assert store._fallback is None


def test_staging_api_imports_with_the_configured_durable_backends():
    """The full API import graph must be safe before an ECS health probe runs."""
    from scripts.lib.preflight_env import parse_env_file

    env = os.environ.copy()
    env.update(parse_env_file(ROOT / "tests/fixtures/staging_preflight/valid.env"))
    env.update({
        "AETHER_ENV": "staging",
        "AETHER_ROLE": "api",
        "CACHE_BACKEND": "dynamodb",
        "DYNAMODB_CACHE_TABLE": "AETHER-staging-cache",
        "POLICY_ENFORCEMENT_ENABLED": "true",
        "ROUTE_REGISTRY_ENFORCED": "true",
        "KYBER_OPERATOR_GATE_ENFORCED": "true",
        "AWS_EC2_METADATA_DISABLED": "true",
        "PYTHONPATH": str(BACKEND_ROOT),
    })
    env.pop("AETHER_ALLOW_INMEMORY_STORE", None)
    env.pop("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", None)

    result = subprocess.run(
        [sys.executable, "-c", "import main; print('STAGING_IMPORT_OK')"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "STAGING_IMPORT_OK" in result.stdout


def test_backend_image_preserves_runtime_authority_layout():
    """The image must retain the source depth used by canonical asset readers."""
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert 'COPY ["services/backend/services/", "./services/backend/services/"]' in dockerfile
    assert 'COPY ["services/backend/shared/", "./services/backend/shared/"]' in dockerfile
    assert 'COPY ["config/", "./config/"]' in dockerfile
    assert 'COPY ["packages/shared/contracts/", "./packages/shared/contracts/"]' in dockerfile
    assert 'COPY ["contracts/delivery/", "./contracts/delivery/"]' in dockerfile
    assert 'COPY ["pyproject.toml", "./pyproject.toml"]' in dockerfile
    assert "ENV PYTHONPATH=/app/services/backend:/app" in dockerfile
    assert "WORKDIR /app/services/backend" in dockerfile
    assert "packages/*" in dockerignore
    assert "!packages/shared/contracts/" in dockerignore
    assert "!packages/shared/contracts/**" in dockerignore

    # These are the first startup/request-time authorities whose absence must
    # never be hidden by a fallback or discovered only by an ECS health probe.
    for relative in (
        "config/route_registry.yaml",
        "config/founding_tenant_release.yaml",
        "packages/shared/contracts/consent-registry.json",
        "packages/shared/contracts/signal-use-matrix.json",
        "packages/shared/contracts/surface-capability-registry.json",
        "contracts/delivery/release-evidence-bundle.schema.json",
        "pyproject.toml",
    ):
        assert (ROOT / relative).is_file(), relative
