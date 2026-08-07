"""
Fail-closed gating for x402 verification + settlement outside the local env.

Pins the closure of two production defects:

1. The internal LOCAL facilitator (``fac_local_aether``) used to return
   ``(True, None)`` unconditionally — combined with it winning the fresh-tenant
   selection tie-break, every payment for a new tenant auto-verified. It must
   confer verification ONLY in the local environment; anywhere else it hands
   off to the on-chain RPC verifier and is never auto-selected.

2. ``SettlementTracker._advance`` used to mark every settlement SETTLED in all
   environments. Outside local, SETTLED means confirmed finality — _advance
   must park the settlement in PENDING for reconciliation instead.

The commerce store is constructed under local env (in-memory collections);
AETHER_ENV is flipped afterwards to exercise the non-local code paths.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

TENANT = "tenant-fail-closed-test"


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    from services.x402.commerce_store import reset_commerce_store

    reset_commerce_store()
    yield
    monkeypatch.setenv("AETHER_ENV", "local")
    reset_commerce_store()


async def _seed(tenant_id: str = TENANT):
    from services.x402.facilitators import seed_facilitators_and_assets

    await seed_facilitators_and_assets(tenant_id)


def _authorization(tenant_id: str = TENANT):
    from services.x402.commerce_models import PaymentAuthorization

    return PaymentAuthorization(
        tenant_id=tenant_id,
        challenge_id="chg-001",
        approval_id="apr-001",
        payment_identifier="pay-001",
        asset_symbol="USDC",
        chain="eip155:8453",
        amount_usd=5.0,
        payer="agent-001",
        recipient="0x00000000000000000000000000000000000000aa",
        facilitator_id="fac_local_aether",
    )


def _receipt(tenant_id: str = TENANT, verified: bool = True):
    from services.x402.commerce_models import PaymentReceipt

    return PaymentReceipt(
        tenant_id=tenant_id,
        authorization_id="auth-001",
        challenge_id="chg-001",
        tx_hash="0x" + "ab" * 32,
        chain="eip155:8453",
        asset_symbol="USDC",
        amount_usd=5.0,
        payer="agent-001",
        recipient="0x00000000000000000000000000000000000000aa",
        verified=verified,
        verified_by="fac_local_aether",
    )


# ── Local facilitator verification gating ─────────────────────────────────


@pytest.mark.asyncio
async def test_local_facilitator_verifies_in_local_env():
    await _seed()
    from services.x402.facilitators import get_facilitator_registry
    from services.x402.verification import VerificationEngine

    engine = VerificationEngine()
    facilitator = await get_facilitator_registry().get(TENANT, "fac_local_aether")
    verified, error = await engine._verify_via_facilitator(
        TENANT, facilitator, _authorization(), "0x" + "ab" * 32
    )
    assert verified is True
    assert error is None


@pytest.mark.asyncio
async def test_local_facilitator_never_verifies_outside_local(monkeypatch):
    await _seed()
    from services.x402.facilitators import get_facilitator_registry
    from services.x402.verification import VerificationEngine

    engine = VerificationEngine()
    facilitator = await get_facilitator_registry().get(TENANT, "fac_local_aether")

    for env in ("staging", "production", "integration", "dev"):
        monkeypatch.setenv("AETHER_ENV", env)
        verified, error = await engine._verify_via_facilitator(
            TENANT, facilitator, _authorization(), "0x" + "ab" * 32
        )
        assert verified is False, f"local facilitator conferred verification in {env}"
        # error=None → the engine falls through to real on-chain verification
        assert error is None


@pytest.mark.asyncio
async def test_local_mode_gating_applies_by_mode_not_only_id(monkeypatch):
    """A LOCAL-mode facilitator under any id must be gated identically."""
    await _seed()
    from services.x402.commerce_models import Facilitator, FacilitatorMode
    from services.x402.facilitators import get_facilitator_registry
    from services.x402.verification import VerificationEngine

    registry = get_facilitator_registry()
    rogue = Facilitator(
        facilitator_id="fac_rogue_internal",
        name="Renamed internal facilitator",
        endpoint_url="internal://aether/verify",
        mode=FacilitatorMode.LOCAL,
        supported_assets=["USDC"],
        supported_chains=["eip155:8453"],
        health_status="unknown",
        active=True,
    )
    await registry.register(TENANT, rogue)

    monkeypatch.setenv("AETHER_ENV", "production")
    engine = VerificationEngine()
    verified, error = await engine._verify_via_facilitator(
        TENANT, rogue, _authorization(), "0x" + "ab" * 32
    )
    assert verified is False
    assert error is None


@pytest.mark.asyncio
async def test_full_verify_path_does_not_auto_pass_outside_local(monkeypatch):
    """End-to-end regression for the free-access hole: with the local
    facilitator selected, a payment that fails on-chain verification must
    yield an UNVERIFIED receipt outside local."""
    await _seed()
    from services.x402.verification import VerificationEngine

    monkeypatch.setenv("AETHER_ENV", "production")
    engine = VerificationEngine()

    async def _no_transfer(authorization, tx_hash):
        return False, "no matching USDC Transfer log found"

    monkeypatch.setattr(engine, "_verify_evm", _no_transfer)
    receipt = await engine.verify(TENANT, _authorization(), "0x" + "ab" * 32)
    assert receipt.verified is False
    assert receipt.verification_error == "no matching USDC Transfer log found"


# ── Facilitator selection gating ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_for_prefers_local_facilitator_in_local_env():
    await _seed()
    from services.x402.facilitators import get_facilitator_registry

    chosen = await get_facilitator_registry().select_for(TENANT, "USDC", "eip155:8453")
    assert chosen is not None
    assert chosen.facilitator_id == "fac_local_aether"


@pytest.mark.asyncio
async def test_select_for_never_picks_local_mode_outside_local(monkeypatch):
    await _seed()
    from services.x402.commerce_models import FacilitatorMode
    from services.x402.facilitators import get_facilitator_registry

    monkeypatch.setenv("AETHER_ENV", "staging")
    chosen = await get_facilitator_registry().select_for(TENANT, "USDC", "eip155:8453")
    assert chosen is not None
    assert chosen.mode != FacilitatorMode.LOCAL
    assert chosen.facilitator_id == "fac_circle_v2"


@pytest.mark.asyncio
async def test_select_for_returns_none_when_only_local_exists_outside_local(monkeypatch):
    """A tenant with only the internal facilitator gets NO facilitator outside
    local — verification falls to the on-chain RPC verifier, never auto-pass."""
    from services.x402.facilitators import LOCAL_AETHER_FACILITATOR, get_facilitator_registry

    tenant = "tenant-only-local-facilitator"
    registry = get_facilitator_registry()
    await registry.register(tenant, LOCAL_AETHER_FACILITATOR.model_copy(deep=True))

    monkeypatch.setenv("AETHER_ENV", "production")
    chosen = await registry.select_for(tenant, "USDC", "eip155:8453")
    assert chosen is None


# ── Settlement gating ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_settlement_settles_immediately_in_local():
    from services.x402.commerce_models import SettlementState
    from services.x402.settlement import SettlementTracker

    tracker = SettlementTracker()
    settlement = await tracker.start(TENANT, _receipt(), "fac_local_aether")
    assert settlement.state == SettlementState.SETTLED


@pytest.mark.asyncio
async def test_settlement_parks_pending_outside_local(monkeypatch):
    from services.x402.commerce_models import SettlementState
    from services.x402.settlement import SettlementTracker

    tracker = SettlementTracker()
    monkeypatch.setenv("AETHER_ENV", "production")
    settlement = await tracker.start(TENANT, _receipt(), "fac_ext")
    assert settlement.state == SettlementState.PENDING
    assert settlement.settled_at is None


@pytest.mark.asyncio
async def test_settlement_retry_stays_pending_outside_local(monkeypatch):
    from services.x402.commerce_models import SettlementState
    from services.x402.settlement import SettlementTracker

    tracker = SettlementTracker()
    monkeypatch.setenv("AETHER_ENV", "staging")
    settlement = await tracker.start(TENANT, _receipt(), "fac_ext")
    retried = await tracker.retry(TENANT, settlement.settlement_id)
    assert retried.state == SettlementState.PENDING
    assert retried.attempts == settlement.attempts + 1
