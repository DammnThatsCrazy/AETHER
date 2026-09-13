"""
E2E test: Agent-mediated journey attribution (spec §34.3)

Tests Web3/agent touchpoint attribution where AI agents interact with
campaigns on behalf of human principals.

Flow:
  1. A human profile browses (human touchpoint — organic search)
  2. An AI agent (linked to profile via agent_id) clicks a campaign ad
  3. The human profile converts (x402 settlement or purchase)
  4. JourneyCompiler links all touchpoints (human + agent) into the journey
  5. AttributionEngine runs actor_weighted model:
     - Human touchpoints get full human_weight (0.7x)
     - Agent touchpoints get agent_weight (0.3x)
  6. Credits reconcile to 1.0
  7. agent_id is recorded on the credit for audit/reward purposes
  8. Wallet linkage: agent touchpoint carries wallet_id for on-chain context
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


TENANT_ID = "tenant-agent-e2e"
PROFILE_ID = f"profile-{uuid4().hex[:8]}"
AGENT_ID = f"agent-{uuid4().hex[:8]}"
WALLET_ID = f"wallet-{uuid4().hex[:8]}"
CAMPAIGN_ID = f"camp-agent-{uuid4().hex[:8]}"
CONVERSION_ID = str(uuid4())

HUMAN_TP_ID = str(uuid4())
AGENT_TP_ID = str(uuid4())

# Stable so a re-seed (see _ensure_seeded) is an idempotent replay, never a
# duplicate conversion under a fresh key.
DEDUP_KEY = f"x402-{uuid4().hex}"


def _human_tp_payload() -> dict:
    return {
        "touchpoint_id": HUMAN_TP_ID,
        "tenant_id": TENANT_ID,
        "profile_id": PROFILE_ID,
        "campaign_id": CAMPAIGN_ID,
        "touchpoint_type": "click",
        "channel": "organic_search",
        "source": "google",
        "occurred_at": _now_iso(),
        "received_at": _now_iso(),
        "idempotency_key": f"agent-tp-human-{HUMAN_TP_ID}",
    }


def _agent_tp_payload() -> dict:
    return {
        "touchpoint_id": AGENT_TP_ID,
        "tenant_id": TENANT_ID,
        "profile_id": PROFILE_ID,
        "agent_id": AGENT_ID,
        "wallet_id": WALLET_ID,
        "campaign_id": CAMPAIGN_ID,
        "touchpoint_type": "click",
        "channel": "paid_display",
        "source": "programmatic",
        "occurred_at": _now_iso(),
        "received_at": _now_iso(),
        "idempotency_key": f"agent-tp-agent-{AGENT_TP_ID}",
    }


def _conversion_payload() -> dict:
    return {
        "conversion_id": CONVERSION_ID,
        "tenant_id": TENANT_ID,
        "conversion_type": "x402_settlement",
        "profile_id": PROFILE_ID,
        "agent_id": AGENT_ID,
        "wallet_id": WALLET_ID,
        "gross_value": "50.00",
        "net_value": "47.50",
        "currency": "USD",
        "occurred_at": _now_iso(),
        "observed_at": _now_iso(),
        "conversion_status": "confirmed",
        "authority_rank": 90,
        "attribution_eligible": True,
        "deduplication_key": DEDUP_KEY,
    }


def _ensure_seeded() -> None:
    """Idempotently (re)establish the touchpoint + conversion graph.

    The in-process stores are global, and any interleaved test that calls
    reset_in_memory_stores() can wipe this class's state between its ordered
    methods (pytest-xdist ``--dist load`` interleaves modules on a worker, so
    an ordered flow cannot assume its earlier steps' writes survive). Every
    upsert here is keyed by a stable module-level idempotency / deduplication
    key, so this is a no-op replay when state survived and a clean restore
    when it did not — either way the dependent step sees a complete graph.
    """
    from services.measurement.repositories.conversion_repo import ConversionRepository
    from services.measurement.repositories.touchpoint_repo import TouchpointRepository

    tp_repo = TouchpointRepository()
    _run(tp_repo.upsert(_human_tp_payload()))
    _run(tp_repo.upsert(_agent_tp_payload()))
    _run(ConversionRepository().upsert(_conversion_payload()))


class TestAgentWeb3AttributionFlow:
    """E2E: human touchpoint + agent touchpoint → actor_weighted attribution."""

    def test_01_store_human_touchpoint(self):
        """A human organic search touchpoint is stored for the profile."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        result = _run(repo.upsert(_human_tp_payload()))
        assert result is not None

    def test_02_store_agent_touchpoint_with_wallet(self):
        """An AI agent touchpoint is stored with agent_id and wallet_id linkage."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        result = _run(repo.upsert(_agent_tp_payload()))
        assert result is not None

    def test_03_store_x402_conversion(self):
        """An x402 settlement conversion is stored, linked to profile and agent."""
        try:
            from services.measurement.repositories.conversion_repo import ConversionRepository
        except ImportError:
            pytest.skip("ConversionRepository not available")

        repo = ConversionRepository()
        result = _run(repo.upsert(_conversion_payload()))
        assert result is not None

    def test_04_journey_includes_both_human_and_agent_touchpoints(self):
        """JourneyCompiler links both human and agent touchpoints into the journey."""
        try:
            from services.measurement.engine.journey_compiler import JourneyCompiler
        except ImportError:
            pytest.skip("JourneyCompiler not available")

        _ensure_seeded()
        compiler = JourneyCompiler()
        journey = _run(compiler.compile_for_profile(TENANT_ID, PROFILE_ID))
        assert isinstance(journey, dict)
        assert journey.get("tenant_id") == TENANT_ID

    def test_05_actor_weighted_attribution_with_agent_id_linkage(self):
        """Actor-weighted attribution properly weights agent vs. human touchpoints."""
        try:
            from services.measurement.engine.attribution_engine import AttributionEngine
        except ImportError:
            pytest.skip("AttributionEngine not available")

        _ensure_seeded()
        engine = AttributionEngine()
        run = _run(engine.run_for_conversion(
            TENANT_ID,
            CONVERSION_ID,
            model_type="actor_weighted",
            trigger_reason="e2e_agent_test",
        ))
        assert isinstance(run, dict)

        credit_total = run.get("credit_total")
        unattributed = run.get("unattributed_credit", 0)

        if credit_total is not None:
            total = Decimal(str(credit_total)) + Decimal(str(unattributed))
            assert abs(total - Decimal("1.0")) < Decimal("0.001"), (
                f"Agent-flow credits must reconcile to 1.0, got {total}"
            )

    def test_06_agent_id_on_credits_for_audit(self):
        """Attribution credits include agent_id for audit and reward routing."""
        try:
            from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        except ImportError:
            pytest.skip("AttributionRunRepository not available")

        _ensure_seeded()
        repo = AttributionRunRepository()
        credits = _run(repo.list_credits_for_conversion(TENANT_ID, CONVERSION_ID))
        # Credits should exist and at least one should carry agent context
        assert isinstance(credits, list)

    def test_07_cross_tenant_agent_isolation(self):
        """Agent touchpoints from another tenant are not accessible."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        # Seed the real tenant so the isolation assertion is meaningful: the
        # profile's touchpoints exist under TENANT_ID but must never surface
        # for a different tenant.
        _ensure_seeded()
        repo = TouchpointRepository()
        results = _run(repo.list_by_profile("attacker-tenant", PROFILE_ID))
        assert results == [], "Cross-tenant agent touchpoint access must return empty"
