"""In-memory backend: full lifecycle semantics."""
from __future__ import annotations

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.types import ApiKeyCredential

_FAKE = "sk-test-0000"


def _backend() -> InMemoryCredentialBackend:
    return InMemoryCredentialBackend(store={})


@pytest.mark.asyncio
async def test_create_and_get():
    b = _backend()
    md = await b.create("t1", "r1", _FAKE)
    assert md.version == 1
    assert md.status == CredentialReadiness.PARTNER_LIVE
    cred = await b.get("t1", "r1")
    assert isinstance(cred, ApiKeyCredential)
    assert cred.api_key.get_secret_value() == _FAKE


@pytest.mark.asyncio
async def test_rotate_increments_version():
    b = _backend()
    await b.create("t1", "r1", _FAKE)
    md2 = await b.rotate("t1", "r1", "sk-test-1111")
    assert md2.version == 2
    cred = await b.get("t1", "r1")
    assert cred.api_key.get_secret_value() == "sk-test-1111"


@pytest.mark.asyncio
async def test_revoke_blocks_get():
    b = _backend()
    await b.create("t1", "r1", _FAKE)
    assert await b.revoke("t1", "r1") is True
    assert await b.get("t1", "r1") is None
    md = await b.metadata("t1", "r1")
    assert md is not None
    assert md.status == CredentialReadiness.DISABLED


@pytest.mark.asyncio
async def test_delete():
    b = _backend()
    await b.create("t1", "r1", _FAKE)
    assert await b.delete("t1", "r1") is True
    assert await b.metadata("t1", "r1") is None
    assert await b.delete("t1", "r1") is False


@pytest.mark.asyncio
async def test_metadata_is_masked():
    b = _backend()
    await b.create("t1", "r1", _FAKE)
    md = await b.metadata("t1", "r1")
    assert md.masked_identifier.startswith("****")
    assert _FAKE not in md.model_dump_json()


@pytest.mark.asyncio
async def test_list_is_tenant_scoped_and_masked():
    b = _backend()
    await b.create("t1", "r1", _FAKE)
    await b.create("t1", "r2", "sk-test-2222")
    await b.create("t2", "r3", "sk-test-3333")
    items = await b.list("t1")
    assert {m.ref for m in items} == {"r1", "r2"}
    assert _FAKE not in str([m.model_dump() for m in items])


@pytest.mark.asyncio
async def test_health_check():
    health = await _backend().health_check()
    assert health.backend == "in_memory"
    assert health.durable is False
    assert health.healthy is True
