"""Concurrent/racing rotation on one credential slot (A3).

Two rotations racing on the same active version must not both win: optimistic
concurrency admits exactly one and rejects the other with a ConflictError, so a
slot never ends up with two active versions. All in-memory (AETHER_ENV=local).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.providers.credentials.authority import credential_authority  # noqa: E402
from services.providers.credentials.schema import CredentialState  # noqa: E402
from shared.common.common import ConflictError  # noqa: E402

pytestmark = pytest.mark.asyncio

_ENV = "sandbox"
_SLOT = "webhook_signing_secret"


async def test_concurrent_rotation_one_wins():
    reset_in_memory_stores()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await credential_authority.create_pending(tenant, "coinbase", _ENV, _SLOT, "v1", created_by="a")
    await credential_authority.activate(tenant, "coinbase", _ENV, _SLOT, credential_version=1, actor="a")

    async def _rotate(value: str):
        try:
            await credential_authority.rotate(
                tenant, "coinbase", _ENV, _SLOT, value,
                actor="a", expected_active_version=1, idempotency_key=value,
            )
            return "ok"
        except ConflictError:
            return "conflict"

    results = await asyncio.gather(_rotate("alpha"), _rotate("beta"))
    assert sorted(results) == ["conflict", "ok"]  # exactly one wins

    # Invariant: still exactly one ACTIVE version for the slot.
    rows = await credential_authority._repo.versions_for_slot(tenant, "coinbase", _ENV, _SLOT)
    active = [r for r in rows if r.get("state") == CredentialState.ACTIVE]
    assert len(active) == 1
