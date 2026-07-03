"""Unit tests — comms attribution eligibility policy (Phase 16, ADR-C8)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


class TestEligibility:
    def test_delivery_context_only_no_credit(self):
        from services.comms.attribution_policy import comms_touchpoint_eligibility
        eligible, reason = comms_touchpoint_eligibility({"touchpoint_type": "email_delivery"})
        assert not eligible and reason == "delivery_context_only"

    def test_reported_open_excluded_by_default(self):
        from services.comms.attribution_policy import comms_touchpoint_eligibility
        eligible, reason = comms_touchpoint_eligibility({"touchpoint_type": "email_open"})
        assert not eligible and reason == "reported_open_excluded"

    def test_reported_open_view_through_when_enabled(self):
        from services.comms.attribution_policy import (
            CommsAttributionConfig, comms_touchpoint_eligibility,
        )
        cfg = CommsAttributionConfig(reported_opens_as_view_through=True)
        eligible, _ = comms_touchpoint_eligibility({"touchpoint_type": "email_open"}, cfg)
        assert eligible

    def test_machine_click_excluded(self):
        from services.comms.attribution_policy import comms_touchpoint_eligibility
        eligible, reason = comms_touchpoint_eligibility({
            "touchpoint_type": "email_click", "machine_activity_probability": 0.95,
        })
        assert not eligible and reason == "machine_activity"

    def test_human_click_eligible(self):
        from services.comms.attribution_policy import comms_touchpoint_eligibility
        eligible, _ = comms_touchpoint_eligibility({
            "touchpoint_type": "email_click", "machine_activity_probability": 0.05,
        })
        assert eligible

    def test_reply_configurable(self):
        from services.comms.attribution_policy import (
            CommsAttributionConfig, comms_touchpoint_eligibility,
        )
        eligible, _ = comms_touchpoint_eligibility({"touchpoint_type": "email_reply"})
        assert eligible  # default on
        cfg = CommsAttributionConfig(replies_eligible=False)
        eligible, reason = comms_touchpoint_eligibility({"touchpoint_type": "email_reply"}, cfg)
        assert not eligible and reason == "reply_ineligible_by_config"

    def test_non_comms_touchpoints_untouched(self):
        from services.comms.attribution_policy import comms_touchpoint_eligibility
        for tp_type in ("click", "page_view", "impression", "landing"):
            eligible, reason = comms_touchpoint_eligibility({"touchpoint_type": tp_type})
            assert eligible and reason is None, tp_type

    def test_transactional_category_never_acquisition_eligible(self):
        from services.comms.attribution_policy import message_category_attribution_eligible
        for category in ("transactional", "security", "account", "operational"):
            assert not message_category_attribution_eligible(category), category
        for category in ("marketing", "sales", None):
            assert message_category_attribution_eligible(category), category


class TestEngineIntegration:
    def test_engine_filter_hook_matches_policy(self):
        """The engine's _comms_eligibility delegates to the shared policy."""
        from services.measurement.engine.attribution_engine import _comms_eligibility
        assert _comms_eligibility({"touchpoint_type": "email_delivery"})[0] is False
        assert _comms_eligibility({"touchpoint_type": "email_click"})[0] is True
        assert _comms_eligibility({"touchpoint_type": "page_view"})[0] is True
