"""
Unit tests for the commerce components that remain after the control plane was
retired (ADR-012): idempotency, facilitator registry and the historical store.
"""

from __future__ import annotations

import logging
import pytest


@pytest.fixture(autouse=True)
def _quiet_logging():
    """Silence logging for these tests only; never leak the disable to other suites."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(previous)


@pytest.fixture(autouse=True)
def _reset():
    from value.x402 import (
        commerce_store as cs,
        idempotency as idem,
        facilitators as fac,
        verification as ver,
    )
    cs.reset_commerce_store()
    idem.reset_idempotency_store()
    fac._facilitator_registry = None
    fac._asset_registry = None
    ver._engine = None
    yield


@pytest.mark.asyncio
async def test_idempotency_record_and_lookup():
    from value.x402.idempotency import IdempotencyStore

    store = IdempotencyStore(ttl_seconds=60)
    await store.record("t1", "pay_123", {"ok": True})
    assert await store.lookup("t1", "pay_123") == {"ok": True}
    assert await store.lookup("t1", "pay_456") is None
    assert await store.lookup("t2", "pay_123") is None  # tenant isolation


@pytest.mark.asyncio
async def test_idempotency_ttl_expiry():
    from value.x402.idempotency import IdempotencyStore

    store = IdempotencyStore(ttl_seconds=-1)  # already expired
    await store.record("t1", "pay_123", {"ok": True})
    assert await store.lookup("t1", "pay_123") is None


@pytest.mark.asyncio
async def test_facilitator_selection():
    from value.x402.facilitators import (
        get_facilitator_registry,
        seed_facilitators_and_assets,
    )

    await seed_facilitators_and_assets("t_fac")
    registry = get_facilitator_registry()

    fac = await registry.select_for("t_fac", "USDC", "eip155:8453")
    assert fac is not None
    assert "USDC" in fac.supported_assets
    assert "eip155:8453" in fac.supported_chains

    # Unknown asset
    fac2 = await registry.select_for("t_fac", "DOGE", "eip155:8453")
    assert fac2 is None


@pytest.mark.asyncio
async def test_facilitator_selection_filters_by_environment():
    """r819: a live authorization must not route through a sandbox-only
    facilitator, nor a sandbox authorization through a live-only one."""
    from value.x402.facilitators import (
        get_facilitator_registry,
        seed_facilitators_and_assets,
    )

    await seed_facilitators_and_assets("t_env")
    registry = get_facilitator_registry()

    # Seeded external facilitators default to sandbox-only.
    fac_sandbox = await registry.select_for("t_env", "USDC", "eip155:8453", "sandbox")
    fac_live = await registry.select_for("t_env", "USDC", "eip155:8453", "live")
    # No live-capable facilitator seeded → live selection returns None while
    # sandbox selection still resolves.
    if fac_sandbox is not None:
        assert "sandbox" in (fac_sandbox.supported_environments or [])
    assert fac_live is None or "live" in (fac_live.supported_environments or [])
    # Omitting environment keeps the legacy (unfiltered) behavior.
    assert await registry.select_for("t_env", "USDC", "eip155:8453") is not None


@pytest.mark.asyncio
async def test_store_authorization_idempotent_lookup_by_payment_identifier():
    """r824: the store resolves an existing authorization by payment_identifier
    so authorize retries return the original instead of colliding on the unique
    index."""
    from value.x402.commerce_store import get_commerce_store
    from value.x402.commerce_models import PaymentAuthorization

    store = get_commerce_store()
    auth = PaymentAuthorization(
        tenant_id="t_idem", challenge_id="chg1", approval_id="ap1",
        payment_identifier="pay-xyz", amount_usd=1.0, asset_symbol="USDC",
        chain="eip155:8453", recipient="0xrecipient", payer="0xpayer",
        facilitator_id="fac_local_aether",
    )
    await store.put_authorization(auth)
    found = await store.get_authorization_by_payment_identifier("t_idem", "pay-xyz")
    assert found is not None and found.authorization_id == auth.authorization_id
    # Wrong tenant / unknown identifier → None.
    assert await store.get_authorization_by_payment_identifier("t_other", "pay-xyz") is None
    assert await store.get_authorization_by_payment_identifier("t_idem", "nope") is None
