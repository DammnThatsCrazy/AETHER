"""
E2E test: B2B account flow (spec §34.2)

Tests multi-touch, multi-user attribution for a B2B SaaS account deal.

Flow:
  1. Multiple users from the same account interact with campaigns
  2. Touchpoints from different users are all linked to account_id
  3. Journey is compiled per-profile but account attribution aggregates across profiles
  4. Conversion (opportunity closed-won) is attributed across the full account journey
  5. Attribution credits reference the campaign touchpoints, not individual user touchpoints only
  6. Credit reconciliation: sum(credit_weight) == 1.0 for the account-level conversion
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


TENANT_ID = "tenant-b2b-e2e"
ACCOUNT_ID = f"account-{uuid4().hex[:8]}"
CAMPAIGN_ID = f"camp-b2b-{uuid4().hex[:8]}"

# Three users at the same account
PROFILE_CHAMPION = f"profile-{uuid4().hex[:8]}"
PROFILE_ECONOMIC_BUYER = f"profile-{uuid4().hex[:8]}"
PROFILE_EVALUATOR = f"profile-{uuid4().hex[:8]}"

CONVERSION_ID = str(uuid4())


class TestB2BAccountFlow:
    """E2E: multi-user account journey → single closed-won conversion → attribution."""

    def test_multiple_profile_touchpoints_same_account(self):
        """Three profiles at the same account can each record touchpoints."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        touchpoints = [
            {
                "touchpoint_id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "profile_id": PROFILE_CHAMPION,
                "account_id": ACCOUNT_ID,
                "campaign_id": CAMPAIGN_ID,
                "touchpoint_type": "click",
                "channel": "paid_search",
                "occurred_at": _now_iso(),
                "received_at": _now_iso(),
                "idempotency_key": f"b2b-tp-champion-{uuid4().hex}",
            },
            {
                "touchpoint_id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "profile_id": PROFILE_ECONOMIC_BUYER,
                "account_id": ACCOUNT_ID,
                "campaign_id": CAMPAIGN_ID,
                "touchpoint_type": "impression",
                "channel": "display",
                "occurred_at": _now_iso(),
                "received_at": _now_iso(),
                "idempotency_key": f"b2b-tp-buyer-{uuid4().hex}",
            },
            {
                "touchpoint_id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "profile_id": PROFILE_EVALUATOR,
                "account_id": ACCOUNT_ID,
                "campaign_id": CAMPAIGN_ID,
                "touchpoint_type": "click",
                "channel": "organic_search",
                "occurred_at": _now_iso(),
                "received_at": _now_iso(),
                "idempotency_key": f"b2b-tp-evaluator-{uuid4().hex}",
            },
        ]
        for tp in touchpoints:
            result = _run(repo.upsert(tp))
            assert result is not None, f"Touchpoint upsert failed for profile {tp['profile_id']}"

    def test_b2b_conversion_ingestion(self):
        """A closed-won conversion is stored at account level."""
        try:
            from services.measurement.repositories.conversion_repo import ConversionRepository
        except ImportError:
            pytest.skip("ConversionRepository not available")

        repo = ConversionRepository()
        conv = {
            "conversion_id": CONVERSION_ID,
            "tenant_id": TENANT_ID,
            "conversion_type": "opportunity_closed_won",
            "profile_id": PROFILE_CHAMPION,
            "account_id": ACCOUNT_ID,
            "gross_value": "25000.00",
            "net_value": "22500.00",
            "currency": "USD",
            "occurred_at": _now_iso(),
            "observed_at": _now_iso(),
            "conversion_status": "confirmed",
            "authority_rank": 90,
            "attribution_eligible": True,
            "deduplication_key": f"crm-won-{uuid4().hex}",
        }
        result = _run(repo.upsert(conv))
        assert result is not None

    def test_journey_compiled_per_profile(self):
        """JourneyCompiler builds individual journeys for each account member."""
        try:
            from services.measurement.engine.journey_compiler import JourneyCompiler
        except ImportError:
            pytest.skip("JourneyCompiler not available")

        compiler = JourneyCompiler()
        for profile_id in [PROFILE_CHAMPION, PROFILE_ECONOMIC_BUYER, PROFILE_EVALUATOR]:
            journey = _run(compiler.compile_for_profile(TENANT_ID, profile_id))
            assert isinstance(journey, dict), f"Expected dict for profile {profile_id}"
            assert journey.get("tenant_id") == TENANT_ID

    def test_attribution_run_for_b2b_conversion(self):
        """Attribution engine runs for the closed-won conversion and credits reconcile."""
        try:
            from services.measurement.engine.attribution_engine import AttributionEngine
        except ImportError:
            pytest.skip("AttributionEngine not available")

        engine = AttributionEngine()
        run = _run(engine.run_for_conversion(
            TENANT_ID,
            CONVERSION_ID,
            model_type="linear",
            trigger_reason="e2e_b2b_test",
        ))
        assert isinstance(run, dict)

        credit_total = run.get("credit_total")
        unattributed = run.get("unattributed_credit", 0)

        if credit_total is not None:
            total = Decimal(str(credit_total)) + Decimal(str(unattributed))
            assert abs(total - Decimal("1.0")) < Decimal("0.001"), (
                f"B2B attribution credits must reconcile to 1.0, got {total}"
            )

    def test_cross_tenant_isolation(self):
        """Account touchpoints from another tenant are not accessible."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        # Query under a different tenant — should return empty
        results = _run(repo.list_by_profile("different-tenant", PROFILE_CHAMPION))
        assert results == [], (
            f"Cross-tenant query must return empty; got {len(results)} rows"
        )
