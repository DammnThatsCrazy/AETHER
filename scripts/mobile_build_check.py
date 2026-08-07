#!/usr/bin/env python3
"""Mobile app build posture — structural invariants + honest native-build gating.

Three jobs, all honest:

  1. Verify the STRUCTURAL invariants of the two app scaffolds that CAN be checked
     without a native toolchain: both apps exist and are complete (package.json,
     app.json, entry, SDK wiring); the two apps have DISTINCT bundle ids, schemes,
     and product planes (an Aether token can never call Kyber, and no Kyber code
     ships in the Aether binary); each app pins version 8.12.0. These are real
     failures if violated (exit 1).

  1b. Enforce the per-build DISTRIBUTION PROFILE declaration: each app must
     declare a valid snake_case profile per platform in app.json
     (expo.extra.distributionProfiles.ios/.android). The vocabulary must agree
     with services/mobile/config.py (drift-guarded by the contract parity test).

  2. Report the NATIVE build posture. The iOS-simulator / Android-emulator compile
     (`expo prebuild` -> xcodebuild / gradlew) needs macOS + Xcode + the Android SDK
     + the Expo toolchain. When those are absent (this Linux CI container) the native
     build is reported ``externally_blocked`` — a SKIP, never a "compiled" claim.
     Exit stays 0: a missing toolchain is not a scaffold defect.

Exit codes:
  0  scaffolds valid + profiles declared; native build reported (blocked or, on a capable host, runnable)
  1  a structural invariant is violated (missing/incomplete/colliding scaffold, or undeclared/invalid distribution profile)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "apps"

EXPECTED = {
    "aether-mobile": {"app_kind": "aether", "bundle": "com.aether.mobile", "scheme": "aether"},
    "kyber-mobile": {"app_kind": "kyber", "bundle": "com.aether.kyber", "scheme": "kyber"},
}
PLATFORM_VERSION = "8.12.0"

# Distribution profiles per platform family (snake_case). Must agree with
# services/mobile/config.py DISTRIBUTION_PROFILES — drift-guarded by
# tests/contracts/test_mobile_config_parity.py. Every app build MUST declare a
# per-platform profile in app.json:
#   expo.extra.distributionProfiles = { "ios": "testflight", "android": "dev" }
# `dev` is family-agnostic (valid on both platforms); the rest are single-family.
DISTRIBUTION_PROFILES = {
    "ios": ("dev", "testflight", "app_store"),
    "android": ("dev", "play_internal", "managed"),
}


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def check_scaffolds() -> list[str]:
    errors: list[str] = []
    seen_bundles: dict[str, str] = {}
    seen_planes: dict[str, str] = {}
    for name, want in EXPECTED.items():
        app_dir = APPS / name
        if not app_dir.is_dir():
            errors.append(f"{name}: app directory missing")
            continue
        for required in ("package.json", "app.json", "src/index.ts", "src/client.ts", "README.md"):
            if not (app_dir / required).exists():
                errors.append(f"{name}: missing {required}")

        pkg_path = app_dir / "package.json"
        app_path = app_dir / "app.json"
        if pkg_path.exists():
            pkg = _read_json(pkg_path)
            if pkg.get("version") != PLATFORM_VERSION:
                errors.append(f"{name}: package version {pkg.get('version')!r} != {PLATFORM_VERSION}")
            if "@aether/mobile-core" not in pkg.get("dependencies", {}):
                errors.append(f"{name}: does not depend on @aether/mobile-core")
        if app_path.exists():
            expo = _read_json(app_path).get("expo", {})
            bundle = expo.get("ios", {}).get("bundleIdentifier")
            android = expo.get("android", {}).get("package")
            scheme = expo.get("scheme")
            plane = expo.get("extra", {}).get("appKind")
            if bundle != want["bundle"]:
                errors.append(f"{name}: ios bundle {bundle!r} != {want['bundle']!r}")
            if android != want["bundle"]:
                errors.append(f"{name}: android package {android!r} != {want['bundle']!r}")
            if scheme != want["scheme"]:
                errors.append(f"{name}: scheme {scheme!r} != {want['scheme']!r}")
            if plane != want["app_kind"]:
                errors.append(f"{name}: extra.appKind {plane!r} != {want['app_kind']!r}")
            # Cross-app isolation: bundle ids and planes must be distinct.
            if bundle in seen_bundles:
                errors.append(f"{name}: bundle id {bundle!r} collides with {seen_bundles[bundle]}")
            if bundle:
                seen_bundles[bundle] = name
            if plane in seen_planes:
                errors.append(f"{name}: product plane {plane!r} collides with {seen_planes[plane]}")
            if plane:
                seen_planes[plane] = name
    return errors


def check_distribution_profiles() -> list[str]:
    """Every app build must declare a valid per-platform distribution profile.

    Missing or unknown profiles are a real failure (exit 1): the per-build
    declaration is what the config endpoint and distribution gating rely on.
    """
    errors: list[str] = []
    for name, want in EXPECTED.items():
        app_path = APPS / name / "app.json"
        if not app_path.exists():
            continue  # missing app.json is already reported by check_scaffolds
        extra = _read_json(app_path).get("expo", {}).get("extra", {})
        profiles = extra.get("distributionProfiles")
        if not isinstance(profiles, dict):
            errors.append(
                f"{name}: expo.extra.distributionProfiles (ios+android map) required"
            )
            continue
        for platform, allowed in DISTRIBUTION_PROFILES.items():
            value = profiles.get(platform)
            if value is None:
                errors.append(
                    f"{name}: expo.extra.distributionProfiles.{platform} required"
                )
            elif not isinstance(value, str) or value not in allowed:
                errors.append(
                    f"{name}: expo.extra.distributionProfiles.{platform}={value!r} "
                    f"must be one of {', '.join(allowed)}"
                )
    return errors


def declared_profile(name: str) -> str:
    """Human-readable summary of the declared per-platform profiles (or MISSING)."""
    app_path = APPS / name / "app.json"
    if not app_path.exists():
        return "-"
    profiles = _read_json(app_path).get("expo", {}).get("extra", {}).get("distributionProfiles", {})
    if not isinstance(profiles, dict):
        return "MISSING"
    ios, android = profiles.get("ios"), profiles.get("android")
    if ios is None or android is None:
        return "MISSING"
    return f"{ios}/{android}"


def native_toolchain_present() -> dict[str, bool]:
    return {
        "expo": shutil.which("expo") is not None,
        "xcodebuild": shutil.which("xcodebuild") is not None,
        "gradle": shutil.which("gradle") is not None,
        "android_sdk": bool(shutil.which("adb")),
    }


def main() -> int:
    print("Mobile app build check — structural invariants + native posture")
    print("=" * 78)
    errors = check_scaffolds()
    errors += check_distribution_profiles()
    for name, want in EXPECTED.items():
        status = "OK" if not any(name in e for e in errors) else "FAIL"
        print(f"  [{status}] {name:<16} plane={want['app_kind']:<7} "
              f"bundle={want['bundle']} profiles={declared_profile(name)}")
    if errors:
        print("-" * 78)
        for e in errors:
            print(f"  ERROR: {e}")
        print("STRUCTURAL INVARIANT VIOLATED.")
        return 1

    print("-" * 78)
    tools = native_toolchain_present()
    # A real compile needs a platform compiler AND its SDK AND the Expo prebuild
    # toolchain — gradle merely on PATH is not an Android build capability.
    ios_capable = tools["xcodebuild"]
    android_capable = tools["gradle"] and tools["android_sdk"]
    have_native = tools["expo"] and (ios_capable or android_capable)
    if not have_native:
        print("Native build: externally_blocked — no macOS/Xcode, Android SDK, or Expo "
              "toolchain in this environment.")
        print("The iOS-simulator / Android-emulator compile runs in the hosted (macOS) CI; "
              "see reports/mobile-productization/external-blockers.json.")
        print("Scaffolds are valid and the shared SDK typechecks in `make ci-check`. This is "
              "NOT a 'compiled' claim.")
    else:
        print(f"Native toolchain detected ({tools}); run `npx expo prebuild` + platform build "
              "to compile. This check does not itself invoke the native compiler.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
