"""WS-E 6 — SDK version-compatibility tiers (Invariant #18), flag-gated.

Unit tests for :mod:`services.ingestion.sdk_version_tiers`:

* band classification boundaries (8.x supported / 7.x deprecated / 6.x
  read-compatible / 5.x blocked-after-date / <5.0 unsupported / unparseable →
  unclassified), inclusive/exclusive bound semantics, recognized SDK names.
* ``tiers_payload()`` — the capability manifest served at
  ``GET /v1/config/sdk/versions`` (always served; ``enabled``/``mode`` reflect
  the ingress consultation seam).
* ``sdk_version_advisory()`` — None while the flag is OFF (all clients treated
  identically); additive tier metadata when ON.
* ``sdk_version_ingress_blocked()`` — True ONLY when flag ON + mode ==
  "enforce" + band is blocked-after-date/unsupported AND that date has arrived.
  Fail-closed by date, never by band alone; unclassified never blocks.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.ingestion import sdk_version_tiers as st


def _settings(enabled: bool, mode: str = "off") -> SimpleNamespace:
    return SimpleNamespace(
        sdk_version_compat=SimpleNamespace(enabled=enabled, mode=mode),
    )


# ── Band classification ──────────────────────────────────────────────────────

def test_classify_version_band_boundaries():
    cases = {
        "8.0.0": "supported",
        "8.12.0": "supported",
        "99.0.0": "supported",   # no upper bound on the supported band
        "7.0.0": "deprecated",
        "7.99.9": "deprecated",
        "6.0.0": "read_compatible",
        "6.9.9": "read_compatible",
        "5.9.9": "blocked",
        "5.0.0": "blocked",      # min_version is inclusive
        "4.9.9": "unsupported",
        "0.1.0": "unsupported",
    }
    for version, expected in cases.items():
        band = st.classify_sdk_version(version)
        assert band.id == expected, f"{version} → {band.id}, expected {expected}"


def test_classify_version_parsing_variants():
    # v-prefix, pre-release, build metadata, and 2-part semver all classify.
    assert st.classify_sdk_version("v8.2.1").id == "supported"
    assert st.classify_sdk_version("8.2.1-rc.1").id == "supported"
    assert st.classify_sdk_version("8.2.1+build.7").id == "supported"
    assert st.classify_sdk_version("8.12").id == "supported"  # patch defaults to 0
    # Unparseable → unclassified (never blocked).
    assert st.classify_sdk_version(None).id == "unclassified"
    assert st.classify_sdk_version("").id == "unclassified"
    assert st.classify_sdk_version("latest").id == "unclassified"
    assert st.classify_sdk_version("8").id == "unclassified"
    assert st.classify_sdk_version("8.x").id == "unclassified"


def test_classify_version_name_recognition_is_advisory():
    # A parseable version from an unknown library still classifies by version.
    assert st.classify_sdk_version("8.1.0", "analytics.js").id == "supported"
    # Unknown name with an unparseable version stays unclassified.
    assert st.classify_sdk_version("nope", "analytics.js").id == "unclassified"
    # Known SDK names are recognized (substring, case-insensitive).
    for name in ("@aether/web", "aether-react-native", "react-native", "ios"):
        assert st.sdk_name_known(name) is True
    assert st.sdk_name_known("analytics.js") is False
    assert st.sdk_name_known(None) is False


def test_supported_band_carries_full_capabilities_and_read_compatible_flat():
    sup = st.classify_sdk_version("8.12.0")
    assert st.CAP_ENVELOPE_B in sup.capabilities
    assert st.CAP_NORMALIZATION_SPINE in sup.capabilities

    rc = st.classify_sdk_version("6.4.0")
    assert st.CAP_BATCH_INGESTION in rc.capabilities
    assert st.CAP_SERVER_SIDE in rc.capabilities
    assert st.CAP_REPLAY in rc.capabilities
    assert st.CAP_ENVELOPE_B not in rc.capabilities

    blocked = st.classify_sdk_version("5.2.0")
    assert blocked.blocked_after == st.BLOCKED_AFTER_DATE


# ── tiers_payload (capability manifest) ─────────────────────────────────────

def test_tiers_payload_always_served_and_reflects_flag(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=False))
    payload = st.tiers_payload()
    assert payload["enabled"] is False
    assert payload["mode"] == "off"
    assert payload["schema_version"] == "1.0.0"
    assert payload["blocked_after_date"] == st.BLOCKED_AFTER_DATE
    assert len(payload["tiers"]) == 5
    ids = [t["id"] for t in payload["tiers"]]
    assert ids == ["supported", "deprecated", "read_compatible", "blocked", "unsupported"]
    assert payload["unclassified"]["id"] == "unclassified"
    by_id = {t["id"]: t for t in payload["tiers"]}
    assert "canonical_observation_envelope" in by_id["supported"]["capabilities"]
    assert "canonical_observation_envelope" not in by_id["read_compatible"]["capabilities"]

    monkeypatch.setattr(st, "settings", _settings(enabled=True, mode="enforce"))
    enabled_payload = st.tiers_payload()
    assert enabled_payload["enabled"] is True
    assert enabled_payload["mode"] == "enforce"


# ── sdk_version_advisory (ingress consultation, flag-gated) ─────────────────

def test_advisory_is_none_when_flag_off(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=False))
    assert st.sdk_version_advisory({"name": "@aether/web", "version": "8.12.0"}) is None


def test_advisory_is_none_without_library(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=True, mode="shadow"))
    assert st.sdk_version_advisory(None) is None
    assert st.sdk_version_advisory({}) is None


def test_advisory_labels_tier_and_capabilities(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=True, mode="shadow"))
    adv = st.sdk_version_advisory({"name": "@aether/web", "version": "8.12.0"})
    assert adv is not None
    assert adv["consulted"] is True
    assert adv["mode"] == "shadow"
    assert adv["tier"] == "supported"
    assert adv["source"] == {"name": "@aether/web", "version": "8.12.0"}
    assert "batch_ingestion" in adv["capabilities"]

    rc = st.sdk_version_advisory({"name": "@aether/web", "version": "6.2.0"})
    assert rc["tier"] == "read_compatible"
    assert rc["blocked_after"] is None

    blk = st.sdk_version_advisory({"name": "@aether/web", "version": "5.2.0"})
    assert blk["tier"] == "blocked"
    assert blk["blocked_after"] == st.BLOCKED_AFTER_DATE


# ── sdk_version_ingress_blocked (enforce-mode, date-gated) ──────────────────

def test_blocked_is_inert_when_flag_off(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=False, mode="enforce"))
    assert st.sdk_version_ingress_blocked(
        {"name": "@aether/web", "version": "5.2.0"}
    ) is False


def test_blocked_requires_enforce_mode(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=True, mode="shadow"))
    assert st.sdk_version_ingress_blocked(
        {"name": "@aether/web", "version": "5.2.0"}
    ) is False


def test_blocked_is_date_gated(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=True, mode="enforce"))
    monkeypatch.setattr(st, "_utc_today_iso", lambda: "2026-09-05")  # before 2027-01-31
    assert st.sdk_version_ingress_blocked(
        {"name": "@aether/web", "version": "5.2.0"}
    ) is False

    monkeypatch.setattr(st, "_utc_today_iso", lambda: "2027-02-01")  # after block date
    assert st.sdk_version_ingress_blocked(
        {"name": "@aether/web", "version": "5.2.0"}
    ) is True
    # Unsupported (<5.0) also blocks once the date arrives.
    assert st.sdk_version_ingress_blocked(
        {"name": "@aether/web", "version": "4.1.0"}
    ) is True


def test_blocked_never_blocks_supported_or_unclassified(monkeypatch):
    monkeypatch.setattr(st, "settings", _settings(enabled=True, mode="enforce"))
    monkeypatch.setattr(st, "_utc_today_iso", lambda: "2027-02-01")
    assert st.sdk_version_ingress_blocked(
        {"name": "@aether/web", "version": "8.12.0"}
    ) is False
    assert st.sdk_version_ingress_blocked(
        {"name": "@aether/web", "version": "7.1.0"}
    ) is False
    assert st.sdk_version_ingress_blocked({"name": "@aether/web", "version": "latest"}) is False
    assert st.sdk_version_ingress_blocked(None) is False
    assert st.sdk_version_ingress_blocked({}) is False
