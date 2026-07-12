from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


def _evict_backend_modules() -> None:
    for prefix in ("config", "services", "shared"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)


@contextmanager
def backend_module_path():
    original = list(sys.path)
    _evict_backend_modules()
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        # Evict again on exit so the production-constructed config.settings
        # singleton does not leak into later tests (suite-ordering hygiene).
        _evict_backend_modules()


def test_oracle_routes_require_explicit_secrets_outside_local(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://aether:test@localhost:5432/aether")
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "test-byok-key-for-testing")
    monkeypatch.setenv("WATERMARK_SECRET_KEY", "test-watermark-secret-key-for-tests")
    monkeypatch.setenv("CANARY_SECRET_SEED", "test-canary-secret-seed-for-tests")
    monkeypatch.setenv("EXTRACTION_CANARY_SEED", "test-extraction-canary-seed-for-tests")
    monkeypatch.setenv("SDK_CONFIG_SECRET", "test-sdk-config-secret-for-tests")
    # PR 4: production requires an explicit role + non-memory core backends.
    monkeypatch.setenv("AETHER_ROLE", "api")
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.delenv("ORACLE_SIGNER_KEY", raising=False)
    monkeypatch.delenv("ORACLE_INTERNAL_KEY", raising=False)
    monkeypatch.delenv("REWARD_CONTRACT_ADDRESS", raising=False)

    with backend_module_path():
        with pytest.raises(RuntimeError, match="ORACLE_SIGNER_KEY must be set"):
            module = importlib.import_module("services.oracle.routes")
            importlib.reload(module)
