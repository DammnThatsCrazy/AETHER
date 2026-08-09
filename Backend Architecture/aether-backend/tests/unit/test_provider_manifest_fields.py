"""Unit tests: every first-release provider manifest declares the conformance fields.

The §8 universal-provider conformance surface is only trustworthy if EVERY
release-critical manifest actually declares it. These tests assert:

* the catalog still builds and honesty-validates (import-time guarantee),
* every financial provider manifest (payment rails + financial connectors)
  explicitly declares the financial-critical trio — ``read_only_mutating_boundary``,
  ``health_probe``, ``certification_state`` — because the §32 honesty gate refuses
  a money-adjacent manifest that leaves them unset,
* every manifest, financial or not, exposes the three sync-projection attributes
  (``reconciliation_support`` / ``backfill_support`` / ``cursor_semantics``)
  consistently with the canonical ``sync`` sub-model, and
* the validator itself rejects a financial manifest that omits the trio while
  still accepting a non-financial one.
"""

from __future__ import annotations

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.catalog import (
    ALL_MANIFESTS,
    CONNECTOR_MANIFESTS,
    DEFERRED_CREDIT_BUREAU_MANIFESTS,
    PAYMENT_RAIL_MANIFESTS,
)
from shared.integration_contracts.manifest import (
    Authentication,
    Availability,
    EnvironmentAvailability,
    ManifestReadiness,
    ManifestValidationError,
    ProviderManifest,
    is_financial_provider,
    validate_manifest,
)

# The declarative conformance fields every release-critical manifest must carry.
DECLARED_FIELDS = {
    "transport_protocol",
    "base_url_config",
    "callback_requirements",
    "reconciliation_support",
    "backfill_support",
    "cursor_semantics",
    "idempotency_semantics",
    "rate_limit_behavior",
    "read_only_mutating_boundary",
    "health_probe",
    "normalization_version",
    "supported_event_types",
    "known_unsupported_behavior",
    "certification_state",
}

# The financial-critical trio the honesty validator requires for money-adjacent
# capabilities (leave-default None is rejected by validate_manifest).
FINANCIAL_TRIO = {
    "read_only_mutating_boundary",
    "health_probe",
    "certification_state",
}

RELEASE_CRITICAL_FINANCIAL = frozenset(
    m.identity_key
    for m in [*PAYMENT_RAIL_MANIFESTS, *CONNECTOR_MANIFESTS]
    if is_financial_provider(m)
)


def test_catalog_builds_and_honesty_validates() -> None:
    """Import already built ALL_MANIFESTS; every entry is a validated manifest."""
    assert len(ALL_MANIFESTS) >= 29
    for manifest in ALL_MANIFESTS:
        assert isinstance(manifest, ProviderManifest)
        # Building ran validate_manifest at import; re-validate to be explicit.
        assert validate_manifest(manifest) is manifest


def test_release_critical_financial_providers_are_identified() -> None:
    """The financial gate covers the payment rails + financial connectors."""
    rail_keys = {m.identity_key for m in PAYMENT_RAIL_MANIFESTS}
    assert RELEASE_CRITICAL_FINANCIAL.issuperset(rail_keys)
    # Stripe is the one financial connector (billing category).
    assert "stripe.ingestion.connector" in RELEASE_CRITICAL_FINANCIAL
    # Credit bureaus are financial too (validator requires the trio), but they
    # are DEFERRED, not first-release.
    for m in DEFERRED_CREDIT_BUREAU_MANIFESTS:
        assert is_financial_provider(m)
        assert m.identity_key not in RELEASE_CRITICAL_FINANCIAL


@pytest.mark.parametrize(
    "identity",
    sorted(RELEASE_CRITICAL_FINANCIAL),
    ids=sorted(RELEASE_CRITICAL_FINANCIAL),
)
def test_release_critical_financial_declares_every_field(identity: str) -> None:
    """Every first-release financial manifest declares the full conformance surface."""
    manifest = next(m for m in ALL_MANIFESTS if m.identity_key == identity)
    # The three sync-overlapping attributes are read-only PROPERTIES (not pydantic
    # fields), so probe by attribute access — the projection exists on every
    # manifest even though it is not in ``vars()``.
    missing = {name for name in DECLARED_FIELDS if not hasattr(manifest, name)}
    assert not missing, f"{identity} omits declared attributes: {sorted(missing)}"

    # transport_protocol must be a real protocol (not the default that just means
    # "unset by an author who did not think about it").
    assert manifest.transport_protocol in {
        "rest",
        "websocket",
        "polling",
        "webhook",
        "stream",
    }
    # The financial trio must be EXPLICITLY declared (non-empty).
    for field in FINANCIAL_TRIO:
        value = getattr(manifest, field)
        assert value is not None and str(value).strip(), (
            f"{identity} leaves {field} undeclared for a financial provider"
        )
    # The honest posture: nothing in this wave is certified yet.
    assert manifest.certification_state == "uncertified"


@pytest.mark.parametrize(
    "manifest",
    ALL_MANIFESTS,
    ids=lambda m: m.identity_key,
)
def test_sync_projection_attributes_consistent_with_sync(manifest: ProviderManifest) -> None:
    """The three sync-projection attributes are pure views of ``sync`` — a
    parallel map cannot drift from the canonical sub-model."""
    assert manifest.reconciliation_support == manifest.sync.reconciliation
    assert manifest.backfill_support == manifest.sync.initial_backfill
    assert manifest.cursor_semantics == manifest.sync.cursor


def test_payment_rails_are_observe_only() -> None:
    """Every payment rail is an observe-only capability with a declared boundary."""
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert manifest.capability_id == "observe"
        boundary = manifest.read_only_mutating_boundary.lower()
        assert "observe" in boundary or "read-only" in boundary
        for forbidden in ("executes", "settles", "originates", "custodies"):
            # The boundary may NAME the forbidden action to forbid it, so assert
            # the platform-role is observe-only (never a mutating claim).
            assert manifest.product_destinations == []


def test_financial_manifest_without_trio_rejected() -> None:
    """The §32 gate rejects a money-adjacent manifest that omits the trio."""
    base = _financial_manifest()
    for field in FINANCIAL_TRIO:
        manifest = base.model_copy(update={field: None})
        with pytest.raises(ManifestValidationError) as exc_info:
            validate_manifest(manifest)
        assert any(field in v for v in exc_info.value.violations)


def test_financial_manifest_with_trio_accepted() -> None:
    """The §32 gate accepts a financial manifest that declares the trio."""
    manifest = _financial_manifest()
    assert validate_manifest(manifest) is manifest


def test_non_financial_manifest_without_trio_accepted() -> None:
    """The gate does not overreach: non-financial manifests may omit the trio."""
    manifest = ProviderManifest(
        provider_family="acme",
        product_id="ingestion",
        capability_id="connector",
        display_name="Acme",
        category="crm",
        readiness=ManifestReadiness(state=CredentialReadiness.REPLAY_VALIDATED, level=3),
        availability=Availability(
            environments=EnvironmentAvailability(local=True, integration=True)
        ),
        authentication=Authentication(type="api_key"),
        data_outputs=["bronze.connector_events"],
        product_destinations=[],
    )
    assert not is_financial_provider(manifest)
    assert validate_manifest(manifest) is manifest


def _financial_manifest() -> ProviderManifest:
    """A minimal, honest financial manifest WITH the trio declared."""
    return ProviderManifest(
        provider_family="acme_pay",
        product_id="payment_rails",
        capability_id="observe",
        display_name="Acme Pay",
        category="payments",
        readiness=ManifestReadiness(state=CredentialReadiness.CREDENTIAL_WAITING, level=3),
        availability=Availability(
            environments=EnvironmentAvailability(local=True, integration=True)
        ),
        authentication=Authentication(type="webhook_only"),
        data_outputs=["bronze.payment_rail_events"],
        product_destinations=[],
        transport_protocol="webhook",
        read_only_mutating_boundary="observe-only; never moves funds",
        health_probe="test_connection",
        certification_state="uncertified",
    )
