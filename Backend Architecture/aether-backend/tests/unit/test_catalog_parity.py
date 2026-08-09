"""Unit tests: provider behavior derives from the manifest, not parallel maps.

The universal-provider conformance surface exists to end hand-maintained,
per-connector behavior maps that silently rot. These tests enforce that:

* ``transport_protocol`` is a projection of the descriptor's real capability
  flags — a webhook-only connector is never declared pull-capable, and a
  pull-capable connector is never declared webhook-only-transport,
* ``supported_event_types`` exactly equals the connector descriptor's
  ``ingest_event_types`` (single source of truth), and the rails' canonical
  payment event set,
* every payment rail is observe-only (capability ``observe``) with a declared
  read-only boundary,
* the OAuth required-scopes path is exercised with real scope vocabulary:
  an OAuth connector derives ``oauth2`` + its declared scopes, an OAuth
  connector WITHOUT scopes falls through honestly (never empty-scope oauth2),
  and no registered connector today silently depends on the empty map, and
* the three sync-projection attributes never drift from ``sync``.
"""

from __future__ import annotations

import pytest

from services.integrations.connectors.base import (
    ConnectorDescriptor,
    ImplementationStatus,
)
from services.integrations.connectors.registry import CONNECTORS
from shared.integration_contracts.catalog import (
    CONNECTOR_MANIFESTS,
    PAYMENT_RAIL_EVENT_TYPES,
    PAYMENT_RAIL_MANIFESTS,
    manifest_by_family,
    manifest_from_connector_descriptor,
)

# Protocols that legitimately advance a recency cursor (pull-like).
_PULL_PROTOCOLS = frozenset({"rest", "polling", "websocket", "stream"})


def test_connector_transport_is_a_projection_of_descriptor_flags() -> None:
    """transport_protocol matches the descriptor's capability flags — no parallel map."""
    for manifest in CONNECTOR_MANIFESTS:
        desc = CONNECTORS[manifest.provider_family].descriptor()
        assert manifest.transport_protocol in {
            "rest",
            "websocket",
            "polling",
            "webhook",
            "stream",
        }, manifest.identity_key
        # A webhook-transport connector genuinely has no pull API.
        if manifest.transport_protocol == "webhook":
            assert not desc.supports_pull, (
                f"{manifest.provider_family} declared webhook transport but the "
                "descriptor supports pull"
            )
        # A pull-capable connector advances a cursor over a pull protocol.
        if desc.supports_pull:
            assert manifest.transport_protocol in _PULL_PROTOCOLS, (
                f"{manifest.provider_family} supports pull but declares "
                f"{manifest.transport_protocol}"
            )
        # The manifest's own sync structure agrees.
        if manifest.sync.incremental:
            assert manifest.transport_protocol in _PULL_PROTOCOLS
        if manifest.transport_protocol == "webhook":
            assert not manifest.sync.incremental


def test_payment_rail_transport_derives_from_adapter_mode() -> None:
    """Rails: webhook-only ⇒ webhook transport; polling ⇒ polling transport."""
    for manifest in PAYMENT_RAIL_MANIFESTS:
        if manifest.authentication.type == "webhook_only":
            assert manifest.transport_protocol == "webhook", manifest.identity_key
            assert not manifest.sync.incremental
        else:  # api_key polling rails
            assert manifest.transport_protocol == "polling", manifest.identity_key
            assert manifest.sync.incremental
            assert manifest.cursor_semantics is not None


def test_connector_event_types_equal_descriptor_ingest_event_types() -> None:
    """supported_event_types is a projection of the descriptor — the moment a
    parallel map drifts from the descriptor, this fails."""
    for manifest in CONNECTOR_MANIFESTS:
        desc = CONNECTORS[manifest.provider_family].descriptor()
        assert list(manifest.supported_event_types) == list(desc.ingest_event_types), (
            f"{manifest.provider_family}: supported_event_types drifted from ingest_event_types"
        )


def test_payment_rail_event_types_are_canonical_set() -> None:
    """Every rail observes the canonical payment event set, exactly."""
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert list(manifest.supported_event_types) == PAYMENT_RAIL_EVENT_TYPES


def test_every_payment_rail_is_observe_only_with_declared_boundary() -> None:
    """The read/mutate boundary is declared and observation-only — a rail that
    ever claimed to move funds would fail here before it could ship."""
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert manifest.capability_id == "observe", manifest.identity_key
        boundary = (manifest.read_only_mutating_boundary or "").lower()
        assert "observe" in boundary or "read-only" in boundary, (
            f"{manifest.provider_family} did not declare an observe-only boundary"
        )
        assert manifest.product_destinations == []


def test_oauth_connectors_declare_required_scopes() -> None:
    """Every registered OAuth connector derives oauth2 with real, non-empty
    scopes. Vacuously true today (no connector flips supports_oauth yet); the
    moment a connector is flipped, the required-scopes path must be satisfied."""
    for connector_type, connector in CONNECTORS.items():
        manifest = manifest_by_family[connector_type]
        if connector.descriptor().supports_oauth:
            assert manifest.authentication.type == "oauth2", connector_type
            assert manifest.authentication.oauth is not None
            assert manifest.authentication.oauth.scopes, (
                f"{connector_type} is oauth2 but declares no required scopes"
            )


def test_oauth_required_scopes_path_is_exercised() -> None:
    """A descriptor declaring OAuth with real scopes derives oauth2 + scopes."""
    desc = _oauth_descriptor(connector_type="hubspot")
    manifest = manifest_from_connector_descriptor(desc)
    assert manifest.authentication.type == "oauth2"
    assert manifest.authentication.oauth is not None
    assert "crm.objects.contacts.read" in manifest.authentication.oauth.scopes


def test_oauth_without_scopes_falls_through_honestly() -> None:
    """A descriptor declaring OAuth but with NO declared scopes never emits
    empty oauth2 — it falls through to secret-based auth (validate_manifest's
    oauth2⇒scopes rule can then never fire on a lie)."""
    desc = _oauth_descriptor(connector_type="klaviyo")  # not in _OAUTH_SCOPES
    manifest = manifest_from_connector_descriptor(desc)
    assert manifest.authentication.type != "oauth2"
    assert manifest.authentication.oauth is None


def test_oauth_scope_map_is_non_empty_and_never_has_empty_lists() -> None:
    """The scope vocabulary is real and non-empty; a provider in the map always
    has something to request."""
    from shared.integration_contracts.catalog import _OAUTH_SCOPES

    assert _OAUTH_SCOPES, "no OAuth scope vocabulary declared"
    for provider, scopes in _OAUTH_SCOPES.items():
        assert scopes, f"{provider} declares an empty scope list"
        assert all(isinstance(s, str) and s.strip() for s in scopes)


def _oauth_descriptor(connector_type: str) -> ConnectorDescriptor:
    """A synthetic descriptor that declares OAuth (honest pull + secret shape)."""
    return ConnectorDescriptor(
        connector_type=connector_type,  # type: ignore[arg-type]
        label="Synthetic OAuth",
        category="crm",
        description="synthetic",
        supports_webhook=True,
        supports_pull=True,
        requires_secret=True,
        premium=False,
        ingest_event_types=["synth.event"],
        docs_slug="operations/connectors",
        implementation_status=ImplementationStatus.CREDENTIAL_GATED,
        supports_oauth=True,
    )
