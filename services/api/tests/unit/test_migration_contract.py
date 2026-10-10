"""Unit tests for the migration-projection contract models.

``MigrationProjection`` and ``ProjectionCandidate`` are the typed seams the UPR
follow-on uses to project a legacy connector onto a native provider identity
before any migration runs. Both are strict (``extra="forbid"``) so a
misspelled or unplanned field fails fast.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from shared.integration_contracts.migration import (
    MigrationProjection,
    ProjectionCandidate,
)


def _make_projection(**overrides: Any) -> MigrationProjection:
    fields: dict[str, Any] = {
        "connector_type": "shopify",
        "native_identity": "shopify.admin.orders_read",
        "config_field_map": {"shop_domain": "admin_base_url"},
        "secret_field_map": {"password": "access_token"},
        "credential_ref_target": "provider:acme:shopify.admin.orders_read",
        "confidence": "high",
    }
    fields.update(overrides)
    return MigrationProjection(**fields)


# --- MigrationProjection ------------------------------------------------------


def test_migration_projection_constructs_with_defaults() -> None:
    projection = _make_projection()
    assert projection.connector_type == "shopify"
    assert projection.native_identity == "shopify.admin.orders_read"
    assert projection.config_field_map == {"shop_domain": "admin_base_url"}
    assert projection.secret_field_map == {"password": "access_token"}
    assert projection.credential_ref_target == "provider:acme:shopify.admin.orders_read"
    assert projection.confidence == "high"
    assert projection.notes == ""


def test_migration_projection_accepts_notes() -> None:
    projection = _make_projection(notes="manual secret review required")
    assert projection.notes == "manual secret review required"


@pytest.mark.parametrize("bad", ["HIGH", "High", "critical", "", "unknown"])
def test_migration_projection_rejects_non_literal_confidence(bad: str) -> None:
    with pytest.raises(ValidationError):
        _make_projection(confidence=bad)


def test_migration_projection_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _make_projection(unexpected="nope")


def test_migration_projection_round_trip() -> None:
    projection = _make_projection(notes="round trip")
    restored = MigrationProjection.model_validate(projection.model_dump())
    assert restored == projection
    assert restored.model_dump() == projection.model_dump()


def test_migration_projection_requires_required_fields() -> None:
    with pytest.raises(ValidationError):
        MigrationProjection(  # type: ignore[call-arg]
            connector_type="shopify",
            native_identity="shopify.admin.orders_read",
            config_field_map={},
            secret_field_map={},
            credential_ref_target="provider:acme:shopify.admin.orders_read",
        )  # missing confidence


# --- ProjectionCandidate ------------------------------------------------------


def test_projection_candidate_defaults() -> None:
    candidate = ProjectionCandidate(connector_type="woocommerce")
    assert candidate.connector_type == "woocommerce"
    assert candidate.native_identity is None
    assert candidate.confidence == ""
    assert candidate.requires_manual_mapping is False


def test_projection_candidate_with_native_identity() -> None:
    candidate = ProjectionCandidate(
        connector_type="shopify",
        native_identity="shopify.admin.orders_read",
        confidence="medium",
        requires_manual_mapping=True,
    )
    assert candidate.native_identity == "shopify.admin.orders_read"
    assert candidate.confidence == "medium"
    assert candidate.requires_manual_mapping is True


def test_projection_candidate_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionCandidate(connector_type="shopify", bogus=True)  # type: ignore[call-arg]


def test_projection_candidate_round_trip() -> None:
    candidate = ProjectionCandidate(
        connector_type="shopify",
        native_identity="shopify.admin.orders_read",
        confidence="low",
        requires_manual_mapping=True,
    )
    restored = ProjectionCandidate.model_validate(candidate.model_dump())
    assert restored == candidate
    assert restored.model_dump() == candidate.model_dump()


def test_projection_candidate_requires_strict_bool() -> None:
    # requires_manual_mapping is StrictBool — integer truthy values must be
    # rejected rather than silently coerced to True.
    with pytest.raises(ValidationError):
        ProjectionCandidate(connector_type="x", requires_manual_mapping=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ProjectionCandidate(connector_type="x", requires_manual_mapping=0)  # type: ignore[call-arg]
    assert (
        ProjectionCandidate(
            connector_type="x", requires_manual_mapping=True
        ).requires_manual_mapping
        is True
    )
    assert (
        ProjectionCandidate(
            connector_type="x", requires_manual_mapping=False
        ).requires_manual_mapping
        is False
    )
