"""Tests for the app privacy-manifest generator (scripts/generate_privacy_manifests.py).

Verifies the honest, fail-closed contract:
  (a) generation is deterministic and --check passes on the committed artifacts;
  (b) a data-flow declaring a purpose absent from the consent registry fails closed;
  (c) both apps produce a PrivacyInfo.xcprivacy and a data-safety.json;
  (d) no generated PrivacyInfo declares NSPrivacyTracking=true (these apps do not track).
"""
from __future__ import annotations

import importlib.util
import json
import plistlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "generate_privacy_manifests", ROOT / "scripts" / "generate_privacy_manifests.py"
)
gpm = importlib.util.module_from_spec(_spec)
sys.modules["generate_privacy_manifests"] = gpm
_spec.loader.exec_module(gpm)


# ── (a) deterministic + committed artifacts are in sync ─────────────────────────
def test_check_passes_on_committed_artifacts():
    assert gpm.main(["--check"]) == 0


def test_generation_is_deterministic():
    first = gpm.build_all()
    second = gpm.build_all()
    assert {str(k): v for k, v in first.items()} == {str(k): v for k, v in second.items()}


def test_build_all_matches_disk():
    for path, content in gpm.build_all().items():
        assert path.exists(), f"missing artifact: {path}"
        assert path.read_text(encoding="utf-8") == content, f"drift in {path}"


# ── (b) fail closed on a purpose absent from the consent registry ───────────────
def test_bogus_purpose_fails_closed_via_validate():
    consent_purposes = gpm.load_consent_purposes()
    cls = gpm.load_classification_module()
    bogus = [
        {
            "field": "device_installation_id",
            "apple_data_type": "DeviceID",
            "apple_purpose": "AppFunctionality",
            "play_category": "Device or other IDs",
            "play_data_type": "Device or other IDs",
            "play_purpose": "App functionality",
            "purpose": "totally_not_a_real_purpose",
            "linked": True,
            "tracking": False,
            "classification": "confidential",
        }
    ]
    with pytest.raises(gpm.ManifestError):
        gpm.validate_flows("aether-mobile", bogus, consent_purposes, cls)


def test_bogus_purpose_exits_nonzero_via_cli(tmp_path, monkeypatch):
    # Point the generator at a temp app tree whose data-flow names a bogus purpose,
    # and assert the CLI exits 2 (fail closed) without writing anything.
    app_key = "aether-mobile"
    app_dir = tmp_path / "apps" / app_key
    app_dir.mkdir(parents=True)
    (app_dir / "app.json").write_text(
        json.dumps(
            {
                "expo": {
                    "name": "Aether",
                    "version": "8.12.0",
                    "ios": {"bundleIdentifier": "com.aether.mobile"},
                    "android": {"package": "com.aether.mobile"},
                    "extra": {"appKind": "aether"},
                }
            }
        ),
        encoding="utf-8",
    )
    (app_dir / "privacy-data-flows.yaml").write_text(
        "version: 1\n"
        "data_flows:\n"
        "  - field: device_installation_id\n"
        "    apple_data_type: DeviceID\n"
        "    apple_purpose: AppFunctionality\n"
        "    play_category: Device or other IDs\n"
        "    play_data_type: Device or other IDs\n"
        "    play_purpose: App functionality\n"
        "    purpose: NOT_A_REGISTRY_PURPOSE\n"
        "    linked: true\n"
        "    tracking: false\n"
        "    classification: confidential\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gpm, "APPS_DIR", tmp_path / "apps")
    monkeypatch.setattr(gpm, "APP_KEYS", [app_key])
    assert gpm.main([]) == 2  # write mode still refuses
    assert gpm.main(["--check"]) == 2
    assert not (app_dir / "PrivacyInfo.xcprivacy").exists()
    assert not (app_dir / "data-safety.json").exists()


def test_bogus_classification_fails_closed():
    consent_purposes = gpm.load_consent_purposes()
    cls = gpm.load_classification_module()
    bad = [
        {
            "field": "push_token",
            "apple_data_type": "DeviceID",
            "apple_purpose": "AppFunctionality",
            "play_category": "Device or other IDs",
            "play_data_type": "Device or other IDs",
            "play_purpose": "App functionality",
            "purpose": "analytics",
            "linked": True,
            "tracking": False,
            "classification": "ultra_secret_tier",
        }
    ]
    with pytest.raises(gpm.ManifestError):
        gpm.validate_flows("aether-mobile", bad, consent_purposes, cls)


# ── (c) both apps produce both artifacts ────────────────────────────────────────
def test_both_apps_produce_both_artifacts():
    assert set(gpm.APP_KEYS) == {"aether-mobile", "kyber-mobile"}
    for app_key in gpm.APP_KEYS:
        app_dir = gpm.APPS_DIR / app_key
        xcprivacy = app_dir / "PrivacyInfo.xcprivacy"
        data_safety = app_dir / "data-safety.json"
        assert xcprivacy.exists(), f"{app_key}: no PrivacyInfo.xcprivacy"
        assert data_safety.exists(), f"{app_key}: no data-safety.json"
        # The plist parses as a real property list.
        plist = plistlib.loads(xcprivacy.read_bytes())
        assert "NSPrivacyCollectedDataTypes" in plist
        # The data-safety file is valid JSON with the expected shape.
        doc = json.loads(data_safety.read_text(encoding="utf-8"))
        assert doc["data_collection"]["collects_data"] is True
        assert doc["security_practices"]["user_can_request_data_deletion"] is True
        assert doc["security_practices"]["data_encrypted_in_transit"] is True
        assert doc["collected_data"], "expected at least one collected field"


# ── (d) these apps do not track ─────────────────────────────────────────────────
def test_no_manifest_declares_tracking():
    for app_key in gpm.APP_KEYS:
        plist = plistlib.loads(
            (gpm.APPS_DIR / app_key / "PrivacyInfo.xcprivacy").read_bytes()
        )
        assert plist["NSPrivacyTracking"] is False
        assert plist["NSPrivacyTrackingDomains"] == []
        for collected in plist["NSPrivacyCollectedDataTypes"]:
            assert collected["NSPrivacyCollectedDataTypeTracking"] is False


def test_data_safety_never_shares_and_no_tracking():
    for app_key in gpm.APP_KEYS:
        doc = json.loads(
            (gpm.APPS_DIR / app_key / "data-safety.json").read_text(encoding="utf-8")
        )
        assert doc["data_collection"]["shares_data"] is False
        for row in doc["collected_data"]:
            assert row["shared"] is False
            assert row["used_for_tracking"] is False


# ── purposes are anchored to the real consent registry ──────────────────────────
def test_every_consent_purpose_is_in_registry():
    consent_purposes = gpm.load_consent_purposes()
    for app_key in gpm.APP_KEYS:
        doc = json.loads(
            (gpm.APPS_DIR / app_key / "data-safety.json").read_text(encoding="utf-8")
        )
        for row in doc["collected_data"]:
            assert row["consent_purpose"] in consent_purposes
