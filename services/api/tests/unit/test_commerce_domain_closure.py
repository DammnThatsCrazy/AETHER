"""
Unit tests for the commerce-domain closure pieces:

    - rail matrix (every configured rail reports one of four support buckets,
      never silent — unknown rails raise UnknownRailError)

The commerce lifecycle reconciliation, commerce metering, tenant signer
authority and control-plane metering pieces that this suite once covered were
retired with the commerce control plane (ADR-012: Aether observes x402, it does
not run a paywall).

All tests run against the in-memory backends (AETHER_ENV=local); per-test store
singletons are reset before each test.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from value.commerce.rail_matrix import (
    RailSupport,
    UnknownRailError,
    all_declared_rails,
    classify_rail,
    is_supported_for_production,
    is_supported_for_sandbox,
    native_rails,
    unsupported_reason,
)
from value.x402.facilitators import (
    reset_asset_registry,
    reset_facilitator_registry,
)


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset():
    from ingestion.silver.writer import reset_local_tables
    from value.x402 import commerce_store as cs, idempotency as idem, verification as ver

    # Reset the commerce store and every store-capturing x402 singleton so each
    # test rebuilds a fresh store graph (singletons built earlier in the same
    # pytest-xdist worker would otherwise keep a stale store reference).
    def _clear() -> None:
        cs.reset_commerce_store()
        idem.reset_idempotency_store()
        ver._engine = None
        reset_facilitator_registry()
        reset_asset_registry()

    _clear()
    reset_local_tables()
    yield
    reset_in_memory_stores()
    _clear()


def test_rail_matrix_production_bucket():
    assert classify_rail("onchain_claim") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("tenant_webhook") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("recommend_only") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("eip155:8453") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("solana:mainnet") is RailSupport.SUPPORTED_PRODUCTION


def test_rail_matrix_sandbox_bucket():
    assert classify_rail("onchain_claim.svm") is RailSupport.SUPPORTED_SANDBOX
    assert classify_rail("eip155:84532") is RailSupport.SUPPORTED_SANDBOX
    assert classify_rail("solana:devnet") is RailSupport.SUPPORTED_SANDBOX


def test_rail_matrix_beta_bucket():
    assert classify_rail("stripe_credit") is RailSupport.SUPPORTED_BETA
    assert classify_rail("loyalty_points") is RailSupport.SUPPORTED_BETA
    assert classify_rail("coupon") is RailSupport.SUPPORTED_BETA
    assert classify_rail("internal_credit") is RailSupport.SUPPORTED_BETA
    assert classify_rail("x402_credit") is RailSupport.SUPPORTED_BETA


def test_rail_matrix_intentionally_unsupported_has_reason():
    assert classify_rail("ach") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert classify_rail("wire") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert classify_rail("card_surcharge") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert classify_rail("crypto_custody") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert unsupported_reason("ach")
    assert unsupported_reason("wire")


def test_rail_matrix_aliases_resolve():
    # Aliases never invent support — they point at declared native rails.
    assert classify_rail("base_usdc") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("solana_usdc") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("on_chain_claim") is RailSupport.SUPPORTED_PRODUCTION


def test_rail_matrix_unknown_rail_raises():
    with pytest.raises(UnknownRailError):
        classify_rail("made_up_rail_xyz")
    with pytest.raises(UnknownRailError):
        is_supported_for_production("made_up_rail_xyz")


def test_rail_matrix_support_helpers():
    assert is_supported_for_production("onchain_claim") is True
    assert is_supported_for_production("onchain_claim.svm") is False
    assert is_supported_for_sandbox("onchain_claim.svm") is True
    assert is_supported_for_sandbox("stripe_credit") is False


def test_rail_matrix_all_declared_nonempty_and_complete():
    declared = all_declared_rails()
    assert len(declared) >= 20
    # Every declared rail must resolve to one of the four buckets (never silent).
    for rail in declared:
        assert classify_rail(rail) in (
            RailSupport.SUPPORTED_PRODUCTION,
            RailSupport.SUPPORTED_SANDBOX,
            RailSupport.SUPPORTED_BETA,
            RailSupport.INTENTIONALLY_UNSUPPORTED,
        )
    assert "onchain_claim" in native_rails()


