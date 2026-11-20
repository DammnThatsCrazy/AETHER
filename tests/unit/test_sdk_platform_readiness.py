"""The per-platform SDK readiness ladder in scripts/production_status.py.

One aggregate "SDKs" score hid that nothing was installable from a public
registry. The ladder is cumulative, so a rung met above an unmet one (onboarding
already issues the right key while the package is unpublished) is reported
without lifting the level.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import production_status as ps  # noqa: E402


def _rows():
    return {row["platform"]: row for row in ps.sdk_platform_readiness()}


def test_every_platform_is_placed_and_stops_below_publication():
    rows = _rows()
    assert set(rows) == {"web", "react", "react-native", "ios", "android", "server"}
    for platform, row in rows.items():
        # Nothing is published yet, so no platform may claim L4 or above.
        assert row["level"] == 3, (platform, row)
        assert row["next"].startswith("L4 published")


def test_rungs_met_above_the_level_are_reported_not_counted():
    for platform, row in _rows().items():
        # Onboarding issues each SDK its key class today (L5) while L4 is unmet.
        assert row["rungs"]["L5"] is True, platform
        assert row["met_above_level"] == ["L5"], platform


def test_client_sdks_must_get_publishable_keys_for_l5(monkeypatch):
    """L5 is derived from onboarding: a client SDK given a secret key fails it."""
    real = ps._onboarding_key_kind
    monkeypatch.setattr(ps, "_onboarding_key_kind", lambda sdk_id: "secret" if sdk_id == "ios" else real(sdk_id))
    assert _rows()["ios"]["rungs"]["L5"] is False


def test_declaring_an_external_rung_lifts_the_level(monkeypatch):
    rungs = {p: dict(v) for p, v in ps.SDK_EXTERNAL_RUNGS.items()}
    rungs["web"][4] = True
    monkeypatch.setattr(ps, "SDK_EXTERNAL_RUNGS", rungs)
    row = _rows()["web"]
    assert row["level"] == 5
    assert row["next"].startswith("L6 first event from an install")


def test_sdk_area_score_matches_the_ladder():
    """The aggregate score must not claim release-ready while no platform is published."""
    area = next(a for a in ps.AREAS if a.name == "SDKs")
    assert max(row["level"] for row in ps.sdk_platform_readiness()) < 4
    assert area.score <= 3
