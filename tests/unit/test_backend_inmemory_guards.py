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
    monkeypatch.delenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", raising=False)

    with backend_module_path():
        module = importlib.import_module("services.attribution.resolver")
        importlib.reload(module)

        with pytest.raises(RuntimeError, match="JourneyStore is disabled outside local mode"):
            module.JourneyStore()
