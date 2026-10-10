"""Local encrypted backend: durability, encryption at rest, rotation window."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from shared.credentials.local_encrypted import LocalEncryptedCredentialBackend
from shared.credentials.store import CredentialStore

_FAKE = "sk-test-0000"


def _shared_rows() -> dict:
    return {}


@pytest.mark.asyncio
async def test_durable_roundtrip_across_simulated_restart():
    """Write with one instance, read with a fresh instance sharing the store."""
    rows = _shared_rows()
    writer = LocalEncryptedCredentialBackend(store=CredentialStore(rows=rows))
    await writer.create("t1", "r1", _FAKE)

    # Fresh backend + fresh store object sharing the same underlying rows.
    reader = LocalEncryptedCredentialBackend(store=CredentialStore(rows=rows))
    cred = await reader.get("t1", "r1")
    assert cred is not None
    assert cred.api_key.get_secret_value() == _FAKE


@pytest.mark.asyncio
async def test_ciphertext_at_rest_is_not_plaintext():
    rows = _shared_rows()
    b = LocalEncryptedCredentialBackend(store=CredentialStore(rows=rows))
    await b.create("t1", "r1", _FAKE)
    row = await b._store.get("t1", "r1")  # noqa: SLF001 - inspecting storage
    assert row["ciphertext"] != _FAKE
    assert _FAKE not in row["ciphertext"]


@pytest.mark.asyncio
async def test_rotation_reencrypts_and_bumps_version():
    key = Fernet.generate_key().decode()
    b = LocalEncryptedCredentialBackend(store=CredentialStore(rows=_shared_rows()), encryption_key=key)
    md1 = await b.create("t1", "r1", _FAKE)
    ct1 = (await b._store.get("t1", "r1"))["ciphertext"]  # noqa: SLF001
    md2 = await b.rotate("t1", "r1", "sk-test-1111")
    ct2 = (await b._store.get("t1", "r1"))["ciphertext"]  # noqa: SLF001
    assert md1.version == 1
    assert md2.version == 2
    assert ct1 != ct2
    assert (await b.get("t1", "r1")).api_key.get_secret_value() == "sk-test-1111"


@pytest.mark.asyncio
async def test_previous_key_rotation_window():
    k1 = Fernet.generate_key().decode()
    k2 = Fernet.generate_key().decode()
    rows = _shared_rows()
    old = LocalEncryptedCredentialBackend(store=CredentialStore(rows=rows), encryption_key=k1)
    await old.create("t1", "r1", _FAKE)

    # New active key k2, previous key k1 — the row was encrypted under k1.
    rotated = LocalEncryptedCredentialBackend(
        store=CredentialStore(rows=rows), encryption_key=k2, encryption_key_previous=k1
    )
    cred = await rotated.get("t1", "r1")
    assert cred is not None
    assert cred.api_key.get_secret_value() == _FAKE


@pytest.mark.asyncio
async def test_masked_metadata_carries_no_secret():
    b = LocalEncryptedCredentialBackend(store=CredentialStore(rows=_shared_rows()))
    await b.create("t1", "r1", _FAKE)
    md = await b.metadata("t1", "r1")
    assert md is not None
    assert md.masked_identifier.startswith("****")
    assert _FAKE not in md.model_dump_json()
    listed = await b.list("t1")
    assert _FAKE not in str([m.model_dump() for m in listed])


@pytest.mark.asyncio
async def test_revoke_blocks_get_on_durable_backend():
    rows = _shared_rows()
    b = LocalEncryptedCredentialBackend(store=CredentialStore(rows=rows))
    await b.create("t1", "r1", _FAKE)
    assert await b.revoke("t1", "r1") is True
    assert await b.get("t1", "r1") is None
