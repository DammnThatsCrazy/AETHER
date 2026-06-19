"""Unit tests for POST /v1/batch ingestion: consent, PII, idempotency, size limit."""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
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


@pytest.fixture()
def batch(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        mod = importlib.import_module("services.ingestion.batch")
        yield mod


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(event_type: str = "track", event_id: str = "evt-1", **props) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "timestamp": _ts(),
        "sessionId": "sess-1",
        "anonymousId": "anon-1",
        "properties": props,
    }


class _FakeCache:
    """In-memory stand-in for CacheClient (only set_nx + get needed)."""

    def __init__(self):
        self._store: dict = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set_nx(self, key: str, value: str, ttl=None) -> bool:
        if key in self._store:
            return False
        self._store[key] = value
        return True

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.mark.asyncio
async def test_event_type_validation_rejected(batch):
    """Unknown event type → rejected."""
    cache = _FakeCache()
    result = await batch._process_single_event(
        sdk_event=batch.BaseEvent(**_event(event_type="unknown_xyz")),
        tenant_id="t1", batch_id="b1", received_at=_ts(), cache=cache,
        granted_consents=frozenset(["analytics"]),
    )
    assert result.status == "rejected"
    assert "unknown_event_type" in (result.reason or "")


@pytest.mark.asyncio
async def test_consent_required_rejected(batch):
    """Commerce event without commerce consent → rejected."""
    cache = _FakeCache()
    result = await batch._process_single_event(
        sdk_event=batch.BaseEvent(**_event(event_type="payment_completed")),
        tenant_id="t1", batch_id="b1", received_at=_ts(), cache=cache,
        granted_consents=frozenset(["analytics"]),  # missing commerce
    )
    assert result.status == "rejected"
    assert "commerce" in (result.reason or "")


@pytest.mark.asyncio
async def test_consent_granted_accepted(batch):
    """Commerce event with commerce consent → accepted (idempotency new)."""
    cache = _FakeCache()
    result = await batch._process_single_event(
        sdk_event=batch.BaseEvent(**_event(event_type="payment_completed", event_id="pmt-1")),
        tenant_id="t1", batch_id="b1", received_at=_ts(), cache=cache,
        granted_consents=frozenset(["analytics", "commerce"]),
    )
    assert result.status == "accepted"


@pytest.mark.asyncio
async def test_pii_scrub_sensitive_key_redacted(batch):
    """Properties with sensitive key → scrubbed to [REDACTED], event still accepted."""
    cache = _FakeCache()
    evt = batch.BaseEvent(**_event(event_type="track", event_id="scrub-1"))
    evt.properties = {"username": "alice", "password": "hunter2"}
    result = await batch._process_single_event(
        sdk_event=evt,
        tenant_id="t1", batch_id="b1", received_at=_ts(), cache=cache,
        granted_consents=frozenset(["analytics"]),
    )
    # Scrubbing → accepted (not rejected); sensitive key redacted in-place
    assert result.status == "accepted"
    assert evt.properties.get("password") == "[REDACTED]"


@pytest.mark.asyncio
async def test_duplicate_idempotency(batch):
    """Pre-claimed idempotency key → duplicate status returned."""
    cache = _FakeCache()
    event_id = "dup-1"
    tenant_id = "t1"
    # Pre-claim the key as the handler would after a previous Bronze write
    idempotency_key = batch._make_idempotency_key(tenant_id, event_id, batch.SCHEMA_VERSION)
    cache_key = f"aether:idempotency:{idempotency_key}"
    await cache.set_nx(cache_key, "1")

    result = await batch._process_single_event(
        sdk_event=batch.BaseEvent(**_event(event_type="track", event_id=event_id)),
        tenant_id=tenant_id, batch_id="b1", received_at=_ts(), cache=cache,
        granted_consents=frozenset(["analytics"]),
    )
    assert result.status == "duplicate"


def test_idempotency_key_is_tenant_scoped(batch):
    """Idempotency key must differ for same event_id across tenants."""
    key_a = batch._make_idempotency_key("tenant-a", "evt-1", "1.0.0")
    key_b = batch._make_idempotency_key("tenant-b", "evt-1", "1.0.0")
    assert key_a != key_b


def test_scrub_sensitive_fields(batch):
    """_scrub_sensitive_fields must redact private_key, seed_phrase, etc."""
    props = {
        "username": "alice",
        "private_key": "deadbeef" * 8,
        "nested": {"seed_phrase": "word1 word2", "value": 42},
    }
    scrubbed, had = batch._scrub_sensitive_fields(props)
    assert had is True
    assert scrubbed["username"] == "alice"
    assert scrubbed["private_key"] == "[REDACTED]"
    assert scrubbed["nested"]["seed_phrase"] == "[REDACTED]"
    assert scrubbed["nested"]["value"] == 42


def test_batch_request_consents_field(batch):
    """BatchRequest accepts a consents list alongside the event batch."""
    req = batch.BatchRequest(
        batch=[batch.BaseEvent(**_event(event_type="track"))],
        sentAt=_ts(),
        consents=["analytics", "commerce"],
    )
    assert "analytics" in req.consents
    assert "commerce" in req.consents


def test_batch_request_size_limit(batch):
    """BatchRequest rejects more than 500 events."""
    events = [batch.BaseEvent(**_event(event_type="track", event_id=f"e{i}")) for i in range(501)]
    with pytest.raises(Exception):
        batch.BatchRequest(batch=events, sentAt=_ts())
