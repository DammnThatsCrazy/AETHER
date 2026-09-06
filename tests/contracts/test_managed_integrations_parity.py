"""TS <-> Python parity for the Reconciled Control Plane contract.

``packages/shared/managed-integrations.ts`` and
``services/managed_integrations/contracts.py`` are hand-authored twins; this
test fails if their canonical vocabularies drift (kinds, source origins/owners,
release channels, CP-12 availability values, reconcile results, observed
provenance, the Phase-0 emitted drift-type subset), and if the TS module is not
exported from the shared barrel.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.managed_integrations.contracts import (  # noqa: E402
    INTEGRATION_AVAILABILITY_VALUES,
    INTEGRATION_SOURCE_ORIGINS,
    INTEGRATION_SOURCE_OWNERS,
    MANAGED_DRIFT_TYPES,
    MANAGED_INTEGRATION_KINDS,
    MANAGED_RELEASE_CHANNELS,
    OBSERVED_PROVENANCE_VALUES,
    RECONCILE_RESULT_VALUES,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "managed-integrations.ts"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export const {name}\b[^=]*=\s*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in managed-integrations.ts"
    return re.findall(r"'([a-z0-9_]+)'", m.group(1))


def test_kinds_parity():
    ts = _const_array("managedIntegrationKinds")
    assert ts == list(MANAGED_INTEGRATION_KINDS), (
        f"managed-integration-kind drift: TS={ts} PY={list(MANAGED_INTEGRATION_KINDS)}"
    )


def test_source_origins_parity():
    ts = _const_array("integrationSourceOrigins")
    assert ts == list(INTEGRATION_SOURCE_ORIGINS), (
        f"source-origin drift: TS={ts} PY={list(INTEGRATION_SOURCE_ORIGINS)}"
    )


def test_source_owners_parity():
    ts = _const_array("integrationSourceOwners")
    assert ts == list(INTEGRATION_SOURCE_OWNERS), (
        f"source-owner drift: TS={ts} PY={list(INTEGRATION_SOURCE_OWNERS)}"
    )


def test_release_channels_parity():
    ts = _const_array("managedReleaseChannels")
    assert ts == list(MANAGED_RELEASE_CHANNELS), (
        f"release-channel drift: TS={ts} PY={list(MANAGED_RELEASE_CHANNELS)}"
    )


def test_availability_parity():
    ts = _const_array("integrationAvailabilityValues")
    assert ts == list(INTEGRATION_AVAILABILITY_VALUES), (
        f"CP-12 availability drift: TS={ts} PY={list(INTEGRATION_AVAILABILITY_VALUES)}"
    )


def test_reconcile_results_parity():
    ts = _const_array("reconcileResultValues")
    assert ts == list(RECONCILE_RESULT_VALUES), (
        f"reconcile-result drift: TS={ts} PY={list(RECONCILE_RESULT_VALUES)}"
    )


def test_drift_types_parity():
    ts = _const_array("managedDriftTypes")
    assert ts == list(MANAGED_DRIFT_TYPES), (
        f"drift-type drift: TS={ts} PY={list(MANAGED_DRIFT_TYPES)}"
    )


def test_observed_provenance_parity():
    ts = _const_array("observedProvenanceValues")
    assert ts == list(OBSERVED_PROVENANCE_VALUES), (
        f"observed-provenance drift: TS={ts} PY={list(OBSERVED_PROVENANCE_VALUES)}"
    )


def test_drift_types_are_not_an_invented_vocabulary():
    # Six Phase-0 *emitted* dimensions; reserved-but-canonical §33 types are
    # intentionally not enumerated yet (contract/... drift arrive with later
    # phases). Guard against accidental narrowing below six.
    assert len(MANAGED_DRIFT_TYPES) >= 6


def test_availability_preserves_cp12_distinctness():
    # CP-12: missing/empty/zero/degraded/not_applicable remain distinct.
    # `missing` must never be represented as `empty` or vice-versa.
    assert set(INTEGRATION_AVAILABILITY_VALUES) == {
        "available", "empty", "missing", "degraded", "not_applicable", "unknown",
    }
    for value in ("missing", "empty", "degraded", "not_applicable", "unknown"):
        assert INTEGRATION_AVAILABILITY_VALUES.count(value) == 1


def test_barrel_exports_managed_integrations_contract():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './managed-integrations';" in index
