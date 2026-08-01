"""Tests for the mobile app scaffold invariants (scripts/mobile_build_check.py).

Verifies the structural invariants the check enforces without a native toolchain:
both apps present + complete, distinct bundle ids and product planes, version pinned.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "mobile_build_check", ROOT / "scripts" / "mobile_build_check.py"
)
mbc = importlib.util.module_from_spec(_spec)
sys.modules["mobile_build_check"] = mbc
_spec.loader.exec_module(mbc)


def test_scaffolds_valid():
    assert mbc.check_scaffolds() == []


def test_both_apps_expected():
    assert set(mbc.EXPECTED) == {"aether-mobile", "kyber-mobile"}


def test_planes_and_bundles_are_distinct():
    planes = {v["app_kind"] for v in mbc.EXPECTED.values()}
    bundles = {v["bundle"] for v in mbc.EXPECTED.values()}
    assert len(planes) == 2, "the two apps must be on distinct product planes"
    assert len(bundles) == 2, "the two apps must have distinct bundle ids"


def test_main_reports_and_exits_zero(capsys):
    # Scaffolds are valid; a missing native toolchain must not fail the check.
    rc = mbc.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "com.aether.mobile" in out and "com.aether.kyber" in out
