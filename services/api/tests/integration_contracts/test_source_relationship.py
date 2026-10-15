"""SourceRelationship vocabulary and its deny-only consistency guard."""

from __future__ import annotations

import pytest

from shared.integration_contracts.source_relationship import (
    COMPATIBLE_RIGHTS_CLASSES,
    OLYMPUS_SOURCE_TENANT_ID,
    OPERATOR_RELATIONSHIPS,
    RAW_DATA_OWNERS,
    REQUIRED_RAW_DATA_OWNER,
    SOURCE_RELATIONSHIPS,
    TENANT_SELF_SERVICE_RELATIONSHIPS,
    UNCLASSIFIED,
    relationship_consistent,
)


def test_vocabulary_is_the_curated_eight_in_order():
    assert SOURCE_RELATIONSHIPS == (
        "personal_account",
        "organization_system",
        "first_party_application",
        "partner_feed",
        "olympus_source",
        "public_reference",
        "internal_system",
        "unclassified",
    )
    assert UNCLASSIFIED == "unclassified"
    assert OLYMPUS_SOURCE_TENANT_ID == "olympus"


def test_every_classified_relationship_has_an_owner_and_rights_classes():
    classified = set(SOURCE_RELATIONSHIPS) - {UNCLASSIFIED}
    assert set(REQUIRED_RAW_DATA_OWNER) == classified
    assert set(COMPATIBLE_RIGHTS_CLASSES) == classified
    assert set(REQUIRED_RAW_DATA_OWNER.values()) <= set(RAW_DATA_OWNERS)
    assert RAW_DATA_OWNERS == ("subject", "tenant", "partner", "olympus_labs", "public")


def test_self_service_and_operator_relationships_are_disjoint():
    assert TENANT_SELF_SERVICE_RELATIONSHIPS == {"personal_account", "organization_system"}
    assert OPERATOR_RELATIONSHIPS == {
        "partner_feed", "olympus_source", "public_reference", "internal_system",
    }
    assert not TENANT_SELF_SERVICE_RELATIONSHIPS & OPERATOR_RELATIONSHIPS
    assert UNCLASSIFIED not in TENANT_SELF_SERVICE_RELATIONSHIPS | OPERATOR_RELATIONSHIPS


@pytest.mark.parametrize(
    "relationship,connector_class,expected",
    [
        ("organization_system", "tenant_byod_data", True),
        ("personal_account", "tenant_byod_data", True),
        ("organization_system", "tenant_import", True),
        ("olympus_source", "olympus_provider", True),
        ("partner_feed", "partner_feed", True),
        ("internal_system", "olympus_provider", True),
        ("organization_system", "olympus_provider", False),
        ("personal_account", "partner_feed", False),
        ("olympus_source", "tenant_byod_data", False),
        ("partner_feed", "tenant_byod_data", False),
        ("first_party_application", "olympus_provider", False),
        # Legacy rows: only the class they could already admit stays consistent.
        ("unclassified", "tenant_byod_data", True),
        (None, "tenant_byod_data", True),
        ("unclassified", "olympus_provider", False),
        ("unclassified", "partner_feed", False),
        ("made_up", "tenant_byod_data", False),
    ],
)
def test_relationship_consistency_matrix(relationship, connector_class, expected):
    assert relationship_consistent(relationship, connector_class) is expected


@pytest.mark.parametrize("connector_class", ["", None, "unknown"])
def test_unknown_rights_class_is_never_consistent(connector_class):
    for relationship in SOURCE_RELATIONSHIPS:
        assert relationship_consistent(relationship, connector_class) is False
