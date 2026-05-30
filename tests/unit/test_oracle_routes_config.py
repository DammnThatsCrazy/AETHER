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


def test_oracle_routes_require_explicit_secrets_outside_local(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://aether:test@localhost:5432/aether")
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "test-byok-key-for-testing")
    monkeypatch.setenv("WATERMARK_SECRET_KEY", "test-watermark-secret-key-for-tests")
    monkeypatch.setenv("CANARY_SECRET_SEED", "test-canary-secret-seed-for-tests")
    monkeypatch.delenv("ORACLE_SIGNER_KEY", raising=False)
    monkeypatch.delenv("ORACLE_INTERNAL_KEY", raising=False)
    monkeypatch.delenv("REWARD_CONTRACT_ADDRESS", raising=False)

    with backend_module_path():
        with pytest.raises(RuntimeError, match="ORACLE_SIGNER_KEY must be set"):
            module = importlib.import_module("services.oracle.routes")
            importlib.reload(module)
