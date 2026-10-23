"""The SDK parity conformance check must record known gaps, not only claims."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

from sdk_conformance import build_matrix  # noqa: E402


def test_committed_matrix_has_no_conformance_failures():
    _, failures = build_matrix(ROOT)
    assert failures == []


def test_react_native_manifest_signature_verification_is_recorded_as_unsupported():
    parity = json.loads((ROOT / "packages/shared/sdk-parity.json").read_text())
    cap = next(c for c in parity["capabilities"] if c["id"] == "manifest_signature_verify")
    cell = cap["matrix"]["react-native"]
    assert cell["status"] == "unsupported"
    assert "unsupported" in parity["statusLegend"]
    # The bridge must not advertise a capability the matrix says is absent.
    bridge = (ROOT / "packages/sdk/react-native/src/bridge.ts").read_text()
    assert "manifestSignatureVerification: false" in bridge
