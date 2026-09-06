"""Readiness-honesty contract over the unified catalog (R1 catalog read model).

Every ProviderManifest in `shared.integration_contracts.catalog.ALL_MANIFESTS`
passes `validate_manifest` at import, but this suite pins the honesty
invariants that matter to the customer-facing read model so a regression fails
loudly here rather than surfacing as a dishonest "Ready" badge:

  - no connectable capability may be enabled in an environment it does not
    evidence (level >= 3 rule is the load-bearing gate);
  - nothing in the catalog may claim sandbox/production enablement today
    (the R1 posture is honest-but-dormant: credential_waiting material only);
  - deferred credit bureaus stay scaffolded, tenant-invisible, and enabled in
    NO environment; the tenant-visible catalog therefore excludes them;
  - every readiness state is a canonical CredentialReadiness ladder token
    (never a parallel vocabulary word, never a `production_ready` claim);
  - the endpoint projection keeps entry facts and readiness claims separate.

Namespaced (test_integration_catalog_*). See
docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md § state model for the spec.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.certification.readiness import (  # noqa: E402
    CredentialReadiness,
    readiness_rank,
)
from shared.integration_contracts.catalog import (  # noqa: E402
    AD_MANIFESTS,
    ALL_MANIFESTS,
    CONNECTOR_MANIFESTS,
    DEFERRED_CREDIT_BUREAU_MANIFESTS,
    PAYMENT_RAIL_MANIFESTS,
)
from services.integrations.connectors.catalog_endpoints import (  # noqa: E402
    _manifest_entry,
    _visible_catalog_entries,
)

_LADDER_STATES = {member.value for member in CredentialReadiness}


def _env_enabled(m) -> bool:
    return m.availability.environments.any_enabled()


def test_no_manifest_claims_a_ladder_state_outside_the_vocabulary():
    for manifest in ALL_MANIFESTS:
        assert manifest.readiness.state.value in _LADDER_STATES, (
            f"{manifest.identity_key} uses non-canonical readiness state "
            f"{manifest.readiness.state.value!r}"
        )


def test_visible_capability_requires_level_at_least_three():
    """Visible-in-environment requires level>=3 (validate_manifest invariant)."""
    for manifest in ALL_MANIFESTS:
        if _env_enabled(manifest):
            assert manifest.readiness.level >= 3, (
                f"{manifest.identity_key} is enabled in an environment at "
                f"level {manifest.readiness.level}"
            )


def test_no_capability_claims_sandbox_or_production_today():
    """Honest-but-dormant: no manifest may be enabled in staging/production."""
    for manifest in ALL_MANIFESTS:
        envs = manifest.availability.environments
        assert not envs.staging and not envs.production, (
            f"{manifest.identity_key} claims staging/production enablement"
        )
        assert manifest.readiness.state not in (
            CredentialReadiness.SANDBOX_VALIDATED,
            CredentialReadiness.PARTNER_LIVE,
        ), f"{manifest.identity_key} claims a validated/live ladder state"


def test_deferred_credit_bureaus_are_scaffolded_and_hidden():
    assert len(DEFERRED_CREDIT_BUREAU_MANIFESTS) == 3
    for manifest in DEFERRED_CREDIT_BUREAU_MANIFESTS:
        assert manifest.product_id == "credit"
        assert manifest.capability_id == "report"
        assert manifest.readiness.state == CredentialReadiness.SCAFFOLDED
        assert manifest.readiness.level == 1
        assert not _env_enabled(manifest)
        assert not manifest.availability.tenant_self_service


def test_visible_catalog_excludes_deferred_bureaus():
    visible = _visible_catalog_entries()
    visible_keys = {entry["key"] for entry in visible}
    deferred_keys = {m.identity_key for m in DEFERRED_CREDIT_BUREAU_MANIFESTS}
    assert not (visible_keys & deferred_keys)
    assert len(visible) == len(ALL_MANIFESTS) - len(deferred_keys) == 33


def test_readiness_level_is_consistent_with_state():
    """Manifest readiness.level must equal the ladder's level for its state."""
    # Conservative 1-5 projection table (mirrors catalog.py _READINESS_LEVEL).
    expected_level = {
        CredentialReadiness.SCAFFOLDED: 1,
        CredentialReadiness.DISABLED: 1,
        CredentialReadiness.DEGRADED: 1,
        CredentialReadiness.CREDENTIAL_WAITING: 3,
        CredentialReadiness.REPLAY_VALIDATED: 3,
        CredentialReadiness.SANDBOX_VALIDATED: 4,
        CredentialReadiness.PARTNER_LIVE: 5,
    }
    for manifest in ALL_MANIFESTS:
        assert manifest.readiness.level == expected_level[manifest.readiness.state], (
            f"{manifest.identity_key} level {manifest.readiness.level} inconsistent "
            f"with state {manifest.readiness.state.value}"
        )


def test_readiness_rank_is_monotonic_with_state():
    ranks = [readiness_rank(m.readiness.state) for m in ALL_MANIFESTS]
    assert all(rank is not None for rank in ranks)
    credential_waiting = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    # Every connectable capability is credential-waiting material or better.
    for manifest in ALL_MANIFESTS:
        if _env_enabled(manifest):
            assert (
                manifest.readiness.state == CredentialReadiness.CREDENTIAL_WAITING
            ), f"unexpected visible state {manifest.identity_key}"


def test_endpoint_entry_readiness_is_the_manifest_ladder():
    """The read-model projection exposes ladder tokens, never derived words."""
    for entry in _visible_catalog_entries():
        readiness = entry["readiness"]
        assert readiness["state"] in _LADDER_STATES
        assert readiness["rank"] == readiness_rank(
            CredentialReadiness(readiness["state"])
        )
        assert readiness["level"] == manifest_level_for_state(readiness["state"])
        assert entry["tenant_self_service"] is True
        assert set(entry["environments"]) <= {"local", "integration"}


def manifest_level_for_state(state_value: str) -> int:
    state = CredentialReadiness(state_value)
    if state == CredentialReadiness.CREDENTIAL_WAITING:
        return 3
    if state in (CredentialReadiness.SANDBOX_VALIDATED, CredentialReadiness.REPLAY_VALIDATED):
        return 3 if state == CredentialReadiness.REPLAY_VALIDATED else 4
    if state == CredentialReadiness.PARTNER_LIVE:
        return 5
    return 1


def test_ad_platform_manifest_shapes_are_consistent():
    """Seven ad platforms as ads.metrics credential-waiting material."""
    assert len(AD_MANIFESTS) == 7
    for manifest in AD_MANIFESTS:
        assert manifest.product_id == "ads"
        assert manifest.capability_id == "metrics"
        assert manifest.category == "ad_platform"
        assert manifest.readiness.state == CredentialReadiness.CREDENTIAL_WAITING
        assert _env_enabled(manifest)


def test_payment_rail_manifests_are_observe_only():
    """Payment rails are one product ('payment_rails') observing funding flows."""
    assert len(PAYMENT_RAIL_MANIFESTS) == 5
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert manifest.product_id == "payment_rails"
        assert manifest.capability_id == "observe"
        assert manifest.category == "payments"
        assert manifest.readiness.state == CredentialReadiness.CREDENTIAL_WAITING


def test_catalog_counts():
    assert len(CONNECTOR_MANIFESTS) == 21
    assert len(ALL_MANIFESTS) == 36
    assert len(manifest_identity_keys()) == 36


def manifest_identity_keys():
    return [m.identity_key for m in ALL_MANIFESTS]
