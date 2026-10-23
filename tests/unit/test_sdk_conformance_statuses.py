"""The SDK parity conformance check must record known gaps, not only claims."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import sdk_conformance  # noqa: E402
from sdk_conformance import build_matrix  # noqa: E402


def _with_cell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cell: dict) -> list[str]:
    """Run the real conformance check against a copy of the matrix with one cell replaced."""
    parity = json.loads((ROOT / "packages/shared/sdk-parity.json").read_text())
    cap = next(c for c in parity["capabilities"] if c["id"] == "manifest_signature_verify")
    cap["matrix"]["react-native"] = cell
    patched = tmp_path / "sdk-parity.json"
    patched.write_text(json.dumps(parity))
    monkeypatch.setattr(sdk_conformance, "PARITY_FILE", str(patched))  # absolute path wins over root
    _, failures = build_matrix(ROOT)
    return failures


def test_committed_matrix_has_no_conformance_failures():
    _, failures = build_matrix(ROOT)
    assert failures == []


def test_unsupported_records_a_gap_without_needing_evidence(tmp_path, monkeypatch):
    assert _with_cell(tmp_path, monkeypatch, {"status": "unsupported", "note": "known gap"}) == []


def test_a_claimed_status_still_needs_verifiable_evidence(tmp_path, monkeypatch):
    failures = _with_cell(tmp_path, monkeypatch, {"status": "delegated_native"})
    assert any("react-native" in f and "no evidence" in f for f in failures)
    failures = _with_cell(
        tmp_path, monkeypatch,
        {"status": "supported", "evidence": "packages/sdk/react-native/src/bridge.ts#doesNotExist"},
    )
    assert any("react-native" in f for f in failures)


def test_unknown_statuses_are_rejected(tmp_path, monkeypatch):
    failures = _with_cell(tmp_path, monkeypatch, {"status": "mostly"})
    assert any("unknown status" in f for f in failures)


def test_legend_documents_unsupported():
    parity = json.loads((ROOT / "packages/shared/sdk-parity.json").read_text())
    assert "unsupported" in parity["statusLegend"]


def test_manifest_verification_is_claimed_on_every_manifest_consuming_sdk():
    parity = json.loads((ROOT / "packages/shared/sdk-parity.json").read_text())
    cap = next(c for c in parity["capabilities"] if c["id"] == "manifest_signature_verify")
    for sdk in ("web", "ios", "android"):
        assert cap["matrix"][sdk]["status"] == "supported", sdk
    assert cap["matrix"]["react-native"]["status"] == "delegated_native"
    # The bridge advertises exactly what the matrix claims.
    bridge = (ROOT / "packages/sdk/react-native/src/bridge.ts").read_text()
    assert "manifestSignatureVerification: true" in bridge
