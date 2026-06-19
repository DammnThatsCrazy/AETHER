"""
Shared fixtures and path setup for agentic commerce unit tests.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware",
    "dependencies", "repositories",
)


@contextmanager
def backend_path_ctx(monkeypatch):
    """Add backend root to sys.path with local env vars set."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")
    monkeypatch.delenv("REDIS_HOST", raising=False)

    original = list(sys.path)
    original_mods = set(sys.modules.keys())
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for name in list(sys.modules):
            if name in original_mods:
                continue
            if name.split(".", 1)[0] in _BACKEND_PREFIXES:
                sys.modules.pop(name, None)
