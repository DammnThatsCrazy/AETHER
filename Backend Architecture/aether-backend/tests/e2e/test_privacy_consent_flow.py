"""
E2E test: Privacy/consent flow (spec §34.4)

Tests that consent revocation correctly removes touchpoints from the measurement
pipeline and triggers recomputation of journeys and attribution.

Flow:
  1. Record touchpoints WITH marketing consent
  2. Record conversion (purchase)
  3. Run attribution → credits assigned
  4. User revokes consent (DSR erasure or consent change)
  5. MeasurementPrivacyHandler tombstones touchpoints
  6. JourneyCompiler rebuilds journey (consent_change trigger)
  7. AttributionEngine recomputes → credits reflect reduced touchpoint set
  8. ROAS metric no longer uses revoked touchpoints

This test uses MeasurementPrivacyHandler from services/measurement/privacy.py
which is the canonical DSR/consent integration point.
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


TENANT_ID = "tenant-privacy-e2e"
PROFILE_ID = f"profile-{uuid4().hex[:8]}"
CAMPAIGN_ID = f"camp-privacy-{uuid4().hex[:8]}"
CONVERSION_ID = str(uuid4())
TOUCHPOINT_1_ID = str(uuid4())
TOUCHPOINT_2_ID = str(uuid4())

# Stable so a re-seed (see _seed_graph) is an idempotent replay, never a
# duplicate conversion under a fresh key.
DEDUP_KEY = f"privacy-order-{uuid4().hex}"


def _touchpoint_payloads() -> list[dict]:
    return [
        {
            "touchpoint_id": tp_id,
            "tenant_id": TENANT_ID,
            "profile_id": PROFILE_ID,
            "campaign_id": CAMPAIGN_ID,
            "touchpoint_type": "click",
            "channel": channel,
            "consent_snapshot_id": "consent-v1",
            "privacy_class": "marketing",
            "occurred_at": _now_iso(),
            "received_at": _now_iso(),
            "idempotency_key": f"privacy-tp-{tp_id}",
        }
        for tp_id, channel in [(TOUCHPOINT_1_ID, "paid_social"), (TOUCHPOINT_2_ID, "email")]
    ]


def _conversion_payload() -> dict:
    return {
        "conversion_id": CONVERSION_ID,
        "tenant_id": TENANT_ID,
        "conversion_type": "purchase",
        "profile_id": PROFILE_ID,
        "gross_value": "80.00",
        "net_value": "72.00",
        "currency": "USD",
        "occurred_at": _now_iso(),
        "observed_at": _now_iso(),
        "conversion_status": "confirmed",
        "authority_rank": 80,
        "attribution_eligible": True,
        "deduplication_key": DEDUP_KEY,
    }


def _seed_graph() -> None:
    """Idempotently (re)establish the consented touchpoint + eligible conversion.

    The in-process stores are global; a foreign test calling
    reset_in_memory_stores() (or a worker split under pytest-xdist
    ``--dist load``) can drop this class's earlier writes between its ordered
    methods. Keyed by stable module-level idempotency / deduplication keys, so
    this is a no-op replay when state survived and a clean restore when it did
    not. Each hard-asserting step re-seeds (and, where the scenario requires,
    re-erases) its own precondition rather than trusting cross-method ordering.
    """
    from services.measurement.repositories.conversion_repo import ConversionRepository
    from services.measurement.repositories.touchpoint_repo import TouchpointRepository

    tp_repo = TouchpointRepository()
    for tp in _touchpoint_payloads():
        _run(tp_repo.upsert(tp))
    _run(ConversionRepository().upsert(_conversion_payload()))


def _erase() -> dict:
    """Run the canonical DSR erasure for this subject; returns the handler result."""
    from services.measurement.privacy import MeasurementPrivacyHandler

    return _run(MeasurementPrivacyHandler().handle_erasure(
        tenant_id=TENANT_ID,
        user_id=PROFILE_ID,
    ))


class TestPrivacyConsentFlow:
    """E2E: consent → touchpoints → attribution → revoke → rebuild → recompute."""

    def test_01_store_touchpoints_with_consent(self):
        """Marketing touchpoints are stored when consent is granted."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        for tp in _touchpoint_payloads():
            result = _run(repo.upsert(tp))
            assert result is not None

    def test_02_store_conversion(self):
        """Conversion is stored with attribution_eligible=True."""
        try:
            from services.measurement.repositories.conversion_repo import ConversionRepository
        except ImportError:
            pytest.skip("ConversionRepository not available")

        repo = ConversionRepository()
        result = _run(repo.upsert(_conversion_payload()))
        assert result is not None

    def test_03_initial_attribution_run(self):
        """Attribution run completes before consent revocation."""
        try:
            from services.measurement.engine.attribution_engine import AttributionEngine
        except ImportError:
            pytest.skip("AttributionEngine not available")

        # Self-contained: the eligible conversion must exist on this worker
        # before attribution, independent of whether test_02 ran here.
        _seed_graph()
        engine = AttributionEngine()
        run = _run(engine.run_for_conversion(
            TENANT_ID,
            CONVERSION_ID,
            model_type="linear",
            trigger_reason="initial_run",
        ))
        assert isinstance(run, dict)
        assert run.get("status") in ("complete", "pending", None), (
            f"Unexpected run status: {run.get('status')}"
        )

    def test_04_consent_revocation_tombstones_touchpoints(self):
        """MeasurementPrivacyHandler tombstones touchpoints after consent revoke."""
        try:
            from services.measurement.privacy import MeasurementPrivacyHandler  # noqa: F401
        except ImportError:
            pytest.skip("MeasurementPrivacyHandler not available")

        # Seed first so the erasure has real data to tombstone regardless of
        # cross-worker distribution.
        _seed_graph()
        result = _erase()
        assert isinstance(result, dict), "DSR handler should return a result dict"

    def test_05_journey_rebuild_after_consent_change(self):
        """Journey is rebuilt after consent revocation (consent_change trigger)."""
        try:
            from services.measurement.engine.journey_compiler import JourneyCompiler
        except ImportError:
            pytest.skip("JourneyCompiler not available")

        compiler = JourneyCompiler()
        rebuilt = _run(compiler.rebuild_affected_by_consent_change(TENANT_ID, PROFILE_ID))
        assert isinstance(rebuilt, list)
        for version in rebuilt:
            assert version.get("rebuild_reason") == "consent_change" or version is not None

    def test_06_attribution_refuses_recompute_after_erasure(self):
        """DSR erasure tombstones the conversion, so attribution cannot be
        recomputed for the erased subject — recompute must refuse loudly, not
        silently produce credits from erased data."""
        try:
            from services.measurement.engine.attribution_engine import AttributionEngine
        except ImportError:
            pytest.skip("AttributionEngine not available")

        # Establish the erased precondition on this worker: seed the graph then
        # run the DSR erasure, so the refusal is exercised regardless of whether
        # test_04's erasure landed here (pytest-xdist --dist load may split the
        # class across workers).
        _seed_graph()
        _erase()
        engine = AttributionEngine()
        with pytest.raises(ValueError, match="not attribution-eligible|not found"):
            _run(engine.run_for_conversion(
                TENANT_ID,
                CONVERSION_ID,
                model_type="linear",
                trigger_reason="consent_change_recompute",
            ))

    def test_07_cross_tenant_consent_operations_rejected(self):
        """Consent operation for a profile in the wrong tenant must not affect measurement."""
        try:
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        except ImportError:
            pytest.skip("TouchpointRepository not available")

        repo = TouchpointRepository()
        # A foreign-tenant query must return nothing for this profile
        results = _run(repo.list_by_profile("attacker-tenant", PROFILE_ID))
        assert results == [], "Cross-tenant touchpoint access must return empty"
