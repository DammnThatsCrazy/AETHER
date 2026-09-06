"""TS <-> Python parity for the Reconciled Control Plane contract.

``packages/shared/managed-integrations.ts`` and
``services/managed_integrations/contracts.py`` are hand-authored twins; this
test fails if their canonical vocabularies drift (kinds, source origins/owners,
release channels, CP-12 availability values, reconcile results, observed
provenance, the Phase-0 emitted drift-type subset, and the Phase-1 canonical
§33 taxonomy / §34 ChangeSet statuses / §39 risk classes / §36 action kinds),
and if the TS module is not exported from the shared barrel.
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
    CHANGE_ACTION_KINDS,
    CHANGE_RISK_CLASSES,
    CHANGESET_STATUSES,
    DRIFT_TAXONOMY_TYPES,
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
    # Values are snake_case or risk-class tokens (R0…R5), so keep [A-Z].
    return re.findall(r"'([A-Za-z0-9_]+)'", m.group(1))


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


def test_drift_taxonomy_parity():
    ts = _const_array("driftTaxonomyTypes")
    assert ts == list(DRIFT_TAXONOMY_TYPES), (
        f"drift-taxonomy drift: TS={ts} PY={list(DRIFT_TAXONOMY_TYPES)}"
    )


def test_change_set_statuses_parity():
    ts = _const_array("changeSetStatuses")
    assert ts == list(CHANGESET_STATUSES), (
        f"ChangeSet-status drift: TS={ts} PY={list(CHANGESET_STATUSES)}"
    )


def test_change_risk_classes_parity():
    ts = _const_array("changeRiskClasses")
    assert ts == list(CHANGE_RISK_CLASSES), (
        f"risk-class drift: TS={ts} PY={list(CHANGE_RISK_CLASSES)}"
    )


def test_change_action_kinds_parity():
    ts = _const_array("changeActionKinds")
    assert ts == list(CHANGE_ACTION_KINDS), (
        f"change-action drift: TS={ts} PY={list(CHANGE_ACTION_KINDS)}"
    )


def test_drift_taxonomy_is_exactly_the_22_canonical_types():
    # §33 canonical taxonomy — not every drift requires mutation, and later
    # phases must be able to plan any of these. Guard against accidental
    # narrowing below the full 22-type set.
    assert set(DRIFT_TAXONOMY_TYPES) == {
        "version_drift",
        "capability_drift",
        "contract_drift",
        "schema_drift",
        "mapping_drift",
        "config_drift",
        "policy_drift",
        "authority_drift",
        "consent_drift",
        "platform_permission_drift",
        "provider_scope_drift",
        "provider_terms_drift",
        "endpoint_drift",
        "health_drift",
        "data_quality_drift",
        "release_support_drift",
        "fleet_identity_drift",
        "region_drift",
        "credential_drift",
        "source_authority_drift",
        "volume_drift",
        "cost_drift",
    }
    assert len(DRIFT_TAXONOMY_TYPES) == 22


def test_emitted_drift_types_are_members_of_the_canonical_taxonomy():
    # The Phase-0/1 reconciler *emits* six dimensions; every one must be a real
    # member of the canonical §33 taxonomy. The two must never drift apart.
    canonical = set(DRIFT_TAXONOMY_TYPES)
    for value in MANAGED_DRIFT_TYPES:
        assert value in canonical, f"{value!r} emitted but absent from §33"
    assert len(MANAGED_DRIFT_TYPES) == 6


def test_change_set_statuses_cover_the_spec_state_machine():
    # §34 vocabulary: DRAFT → PLANNED → … → COMMITTED / ROLLED_BACK plus the
    # other terminal states. The Phase-1 planner only ever reaches `planned` or
    # `superseded`, but the full vocabulary must be present so the executor can
    # enforce legality without re-negotiating names later.
    assert set(CHANGESET_STATUSES) == {
        "draft",
        "planned",
        "preparing",
        "validating",
        "simulating",
        "waiting_approval",
        "ready",
        "canary",
        "rolling_out",
        "verifying",
        "committed",
        "rolling_back",
        "rolled_back",
        "cancelled",
        "blocked",
        "failed",
        "superseded",
    }


def test_risk_classes_cover_r0_through_r5_and_security_emergency():
    assert set(CHANGE_RISK_CLASSES) == {
        "R0", "R1", "R2", "R3", "R4", "R5", "security_emergency",
    }


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
