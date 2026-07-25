from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


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
