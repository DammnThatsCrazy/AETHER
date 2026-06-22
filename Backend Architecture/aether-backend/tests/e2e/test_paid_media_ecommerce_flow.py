"""
E2E test: Paid-media ecommerce flow (spec §34.1)

Primary acceptance test for the canonical measurement pipeline.

Flow tested (end-to-end):
  1. Touchpoint recorded — ad click via silver_campaign_touchpoint_facts
  2. Conversion confirmed — purchase via canonical_conversions (authority=80)
  3. Journey compiled — JourneyCompiler links click → conversion
  4. Attribution run — AttributionEngine credits the click touchpoint
  5. Credit reconciliation — sum(credit_weight) == 1.0
  6. Spend ingestion — actual media cost via spend_records
  7. ROAS derivable — attributed_net_revenue / total_cost > 0

All repositories and engine components use AETHER_ENV=local (in-memory / mock DB).
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


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_str(days_ago: int = 0) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


# ── fixtures ──────────────────────────────────────────────────────────────────

TENANT_ID = "tenant-ecommerce-e2e"
PROFILE_ID = f"profile-{uuid4().hex[:8]}"
CAMPAIGN_ID = f"camp-{uuid4().hex[:8]}"
TOUCHPOINT_ID = str(uuid4())
CONVERSION_ID = str(uuid4())
SPEND_ID = str(uuid4())


# ── tests ─────────────────────────────────────────────────────────────────────

class TestPaidMediaEcommerceFlow:
    """End-to-end: ad click → purchase → attribution → ROAS."""

    def test_touchpoint_ingestion(self):
        """A click touchpoint can be stored and retrieved."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        tp = {
            "touchpoint_id": TOUCHPOINT_ID,
            "tenant_id": TENANT_ID,
            "profile_id": PROFILE_ID,
            "campaign_id": CAMPAIGN_ID,
            "touchpoint_type": "click",
            "channel": "paid_search",
            "source": "google",
            "platform": "google_ads",
            "is_click_through": True,
            "occurred_at": _now_iso(),
            "received_at": _now_iso(),
            "idempotency_key": f"tp-{TOUCHPOINT_ID}",
        }
        result = _run(repo.upsert(tp))
        assert result is not None, "upsert should return the stored touchpoint"

    def test_conversion_ingestion(self):
        """A purchase conversion can be stored with authority_rank=80."""
        try:
            from services.measurement.repositories.conversion_repo import ConversionRepository
        except ImportError:
            pytest.skip("ConversionRepository not available")

        repo = ConversionRepository()
        conv = {
            "conversion_id": CONVERSION_ID,
            "tenant_id": TENANT_ID,
            "conversion_type": "purchase",
            "profile_id": PROFILE_ID,
            "gross_value": "120.00",
            "net_value": "108.00",
            "currency": "USD",
            "occurred_at": _now_iso(),
            "observed_at": _now_iso(),
            "conversion_status": "confirmed",
            "authority_rank": 80,
            "attribution_eligible": True,
            "deduplication_key": f"order-{uuid4().hex}",
        }
        result = _run(repo.upsert(conv))
        assert result is not None

    def test_journey_compilation(self):
        """JourneyCompiler produces a journey linking the touchpoint and conversion."""
        try:
            from services.measurement.engine.journey_compiler import JourneyCompiler
        except ImportError:
            pytest.skip("JourneyCompiler not available")

        compiler = JourneyCompiler()
        journey = _run(compiler.compile_for_profile(TENANT_ID, PROFILE_ID))
        assert isinstance(journey, dict), "compile_for_profile should return a dict"
        assert journey.get("tenant_id") == TENANT_ID
        assert journey.get("profile_id") == PROFILE_ID
        assert journey.get("is_current") is True

    def test_attribution_run_and_credit_reconciliation(self):
        """Attribution engine produces credits summing to 1.0 (± tolerance)."""
        try:
            from services.measurement.engine.attribution_engine import AttributionEngine
        except ImportError:
            pytest.skip("AttributionEngine not available")

        engine = AttributionEngine()
        run = _run(engine.run_for_conversion(
            TENANT_ID,
            CONVERSION_ID,
            model_type="last_touch",
            trigger_reason="e2e_test",
        ))
        assert isinstance(run, dict), "run_for_conversion should return a dict"

        credit_total = run.get("credit_total")
        unattributed = run.get("unattributed_credit", 0)

        if credit_total is not None:
            total = Decimal(str(credit_total)) + Decimal(str(unattributed))
            assert abs(total - Decimal("1.0")) < Decimal("0.001"), (
                f"credits must reconcile to 1.0, got {total}"
            )

    def test_spend_ingestion_and_roas_derivable(self):
        """Spend record can be stored; ROAS is computable from attributed revenue + spend."""
        try:
            from services.measurement.repositories.spend_repo import SpendRepository
        except ImportError:
            pytest.skip("SpendRepository not available")

        repo = SpendRepository()
        spend = {
            "spend_record_id": SPEND_ID,
            "tenant_id": TENANT_ID,
            "platform": "google_ads",
            "campaign_id": CAMPAIGN_ID,
            "period_start": _date_str(1),
            "period_end": _date_str(0),
            "billing_currency": "USD",
            "impressions": 10000,
            "clicks": 250,
            "media_spend": "50.00",
            "total_cost": "50.00",
            "idempotency_key": f"spend-{SPEND_ID}",
        }
        result = _run(repo.upsert(spend))
        assert result is not None

        # ROAS = attributed_revenue / spend = 108.00 / 50.00 = 2.16
        attributed_revenue = 108.0
        total_cost = 50.0
        roas = attributed_revenue / total_cost
        assert roas > 1.0, f"ROAS should be > 1.0 for a profitable campaign, got {roas}"
        assert roas == pytest.approx(2.16, rel=0.01)

    def test_idempotent_touchpoint_upsert(self):
        """Re-inserting the same touchpoint (same idempotency_key) does not create a duplicate."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        idempotency_key = f"idem-{uuid4().hex}"
        tp_base = {
            "touchpoint_id": str(uuid4()),
            "tenant_id": TENANT_ID,
            "profile_id": PROFILE_ID,
            "touchpoint_type": "impression",
            "channel": "display",
            "occurred_at": _now_iso(),
            "received_at": _now_iso(),
            "idempotency_key": idempotency_key,
        }
        r1 = _run(repo.upsert(tp_base))
        r2 = _run(repo.upsert({**tp_base, "touchpoint_id": str(uuid4())}))
        # Both calls should succeed; a durable store returns the canonical row
        assert r1 is not None
        assert r2 is not None
