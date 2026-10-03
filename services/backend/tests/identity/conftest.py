"""Identity tests opt in to the staging proof posture unless testing an OFF flag."""

from __future__ import annotations

from dataclasses import replace

import pytest

from config.settings import settings


@pytest.fixture(autouse=True)
def _identity_flags_on_for_identity_tests(monkeypatch):
    """Exercise existing identity behavior explicitly under enabled flags."""
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=True,
        auto_merge_enabled=True,
        manual_review_enabled=True,
        conflict_detection_enabled=True,
        split_enabled=True,
        manual_split_enabled=True,
        sdk_late_binding_enabled=True,
        anonymous_to_known_binding_enabled=True,
        multi_sdk_stitching_enabled=True,
        connector_backfill_enabled=True,
        projection_restatement_enabled=True,
        campaign_restatement_enabled=True,
        value_restatement_enabled=True,
        explainability_enabled=True,
        activation_dashboard_enabled=True,
        agent_resolution_enabled=True,
    ))
