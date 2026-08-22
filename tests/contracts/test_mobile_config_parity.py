"""TS <-> Python parity for the mobile config contract.

`packages/shared/mobile-config.ts` and `services/mobile/config.py` are
hand-authored twins; this test fails on drift in the distribution-profile /
upgrade-policy vocabularies or the MobileConfig field set. It also pins that
the per-build distribution-profile enforcement in
`scripts/mobile_build_check.py` agrees with the config enum (no drift between
the contract and the enforcement hook).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.mobile.config import (  # noqa: E402
    ANDROID_DISTRIBUTION_PROFILES,
    DISTRIBUTION_PROFILES,
    IOS_DISTRIBUTION_PROFILES,
    UPGRADE_POLICIES,
    DistributionProfile,
    MobileConfig,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "mobile-config.ts"
BUILD_CHECK_PATH = REPO_ROOT / "scripts" / "mobile_build_check.py"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in mobile-config.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(
        rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S
    )
    assert m, f"interface {interface} not found in mobile-config.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_distribution_profiles_parity():
    assert set(_const_array("distributionProfiles")) == set(DISTRIBUTION_PROFILES)


def test_distribution_profile_enum_matches_tuple():
    assert {m.value for m in DistributionProfile} == set(DISTRIBUTION_PROFILES)


def test_ios_family_profiles_parity():
    assert set(_const_array("iosDistributionProfiles")) == set(IOS_DISTRIBUTION_PROFILES)


def test_android_family_profiles_parity():
    assert set(_const_array("androidDistributionProfiles")) == set(ANDROID_DISTRIBUTION_PROFILES)


def test_upgrade_policies_parity():
    assert set(_const_array("upgradePolicies")) == set(UPGRADE_POLICIES)


def test_mobile_config_field_parity():
    ts_fields = _interface_fields("MobileConfig")
    py_fields = set(MobileConfig.model_fields.keys())
    assert ts_fields == py_fields, (
        f"MobileConfig drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_build_check_distribution_profiles_agree():
    """The enforcement hook's per-platform vocabulary matches the config enum."""
    text = BUILD_CHECK_PATH.read_text(encoding="utf-8")
    m = re.search(r"DISTRIBUTION_PROFILES\s*=\s*\{(.*?)\n\}", text, re.S)
    assert m, "DISTRIBUTION_PROFILES map not found in mobile_build_check.py"
    block = m.group(1)
    ios = re.search(r'"ios"\s*:\s*\(([^)]*)\)', block)
    android = re.search(r'"android"\s*:\s*\(([^)]*)\)', block)
    assert ios and android, "ios/android profile tuples not found in mobile_build_check.py"
    # Python constants use double quotes; the TS twin uses single quotes.
    _quote = r"""["']([a-z_]+)["']"""
    assert set(re.findall(_quote, ios.group(1))) == set(IOS_DISTRIBUTION_PROFILES)
    assert set(re.findall(_quote, android.group(1))) == set(ANDROID_DISTRIBUTION_PROFILES)


def test_barrel_exports_mobile_config():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './mobile-config';" in index
