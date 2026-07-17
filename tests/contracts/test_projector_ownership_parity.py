"""Registry <-> generated-artifact <-> dispatcher parity for projector ownership.

`Backend Architecture/aether-backend/services/silver/generated_ownership.py`
is the generated twin of
`packages/shared/contracts/projector-ownership-registry.json` (via
scripts/generate_platform_contracts.py); scripts/validate_projector_ownership.py
enforces the registry against the LIVE dispatcher. This test fails on drift
in any leg of that triangle.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

REGISTRY_PATH = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "projector-ownership-registry.json"
)

from services.silver import generated_ownership as gen  # noqa: E402


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_generated_order_matches_registry():
    registry = _registry()
    assert list(gen.PROJECTOR_ORDER) == [e["name"] for e in registry["projectors"]]
    assert gen.PROJECTOR_OWNERSHIP_CONTRACT_VERSION == registry["contractVersion"]


def test_generated_tables_and_roles_match_registry():
    registry = _registry()
    for entry in registry["projectors"]:
        assert gen.PROJECTOR_TABLES[entry["name"]] == entry["table"]
        assert gen.PROJECTOR_ACTIVITY_ROLES[entry["name"]] == entry["activityRole"]
        assert list(gen.PROJECTOR_EVENT_TYPES[entry["name"]]) == entry["eventTypes"]
        assert list(gen.PROJECTOR_EVENT_FAMILIES[entry["name"]]) == entry["eventFamilies"]


def test_exactly_one_activity_owner_per_event_type():
    registry = _registry()
    seen: dict[str, str] = {}
    for entry in registry["projectors"]:
        for event_type in entry["ownedActivityEventTypes"]:
            assert event_type not in seen, (
                f"{event_type!r} claimed by {seen[event_type]!r} and {entry['name']!r}"
            )
            seen[event_type] = entry["name"]
    assert dict(gen.ACTIVITY_OWNER_BY_EVENT_TYPE) == seen


def test_no_projection_families_are_generated():
    registry = _registry()
    assert dict(gen.NO_PROJECTION_FAMILIES) == {
        e["family"]: e["status"] for e in registry["noProjection"]
    }
    # Be honest: the interaction family has NO projector until the PR 2
    # interaction plane lands.
    assert gen.NO_PROJECTION_FAMILIES["interaction"] == "pending_pr2"


def test_out_of_band_declares_silver_graph_projector():
    assert "SilverGraphProjector" in gen.OUT_OF_BAND_PROJECTORS


def test_validator_passes_against_live_dispatcher():
    """The registry must match the LIVE dispatcher (order, handles, owners)."""
    proc = subprocess.run(
        [sys.executable, "scripts/validate_projector_ownership.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"validator failed:\n{proc.stdout}\n{proc.stderr}"
