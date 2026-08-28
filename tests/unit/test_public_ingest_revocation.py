"""Fail-closed tests for tenant-owned public ingest identifiers."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _PREFIXES)
    }
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)
        # Other test modules import backend singletons at collection time.
        # Restore those exact module objects so this isolated import does not
        # leave a second repository/cache universe behind for later tests.
        sys.modules.update(saved_modules)


@pytest.fixture()
def ingest_service(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos._IN_MEMORY_STORES.setdefault("public_ingest_identifiers", {}).clear()
        sessions = importlib.import_module("services.auth.sessions.service")
        service = sessions.PublicIngestService()
        yield service


@pytest.mark.asyncio
async def test_revoke_all_for_tenant_fails_closed_on_identifier_update(ingest_service, monkeypatch):
    issued = await ingest_service.issue_identifier("tenant-rehearsal")

    async def failed_revoke(_identifier_id: str) -> bool:
        return False

    monkeypatch.setattr(ingest_service, "revoke_identifier", failed_revoke)

    with pytest.raises(RuntimeError, match="could not revoke all"):
        await ingest_service.revoke_all_for_tenant("tenant-rehearsal")

    remaining = await ingest_service.validate_identifier(issued["identifier"])
    assert remaining["status"] == "active"


@pytest.mark.asyncio
async def test_revoke_all_for_tenant_is_idempotent_for_revoked_records(ingest_service):
    issued = await ingest_service.issue_identifier("tenant-rehearsal")
    assert await ingest_service.revoke_identifier(issued["id"]) is True

    assert await ingest_service.revoke_all_for_tenant("tenant-rehearsal") == 0
