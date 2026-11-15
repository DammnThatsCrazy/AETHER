"""Source roles: per-stream role tags, role/pack rules, and evidence ceilings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.agent_lineage.vocabulary import PRINCIPAL_EVIDENCE_CLASSES
from shared.integration_contracts.source_roles import (
    DOMAIN_PACKS,
    SOURCE_ROLES,
    allowed_domain_packs,
    cap_evidence,
    evidence_ceiling,
    provider_source_roles,
    role_domain_pack_violation,
)
from shared.integration_contracts.streams import StreamDescriptor
from shared.privacy.classification import DataClassification


def _stream(stream_id: str, domain_pack: str, role: str | None) -> StreamDescriptor:
    return StreamDescriptor(
        stream_id=stream_id,
        object_kind="record",
        domain_pack=domain_pack,
        acquisition_modes=("webhook",),
        output_contract="bronze.provider_events",
        source_authority_class=f"{domain_pack}.test",
        data_classification=DataClassification.INTERNAL,
        source_role=role,
    )


def test_every_role_has_a_ceiling_and_packs() -> None:
    for role in SOURCE_ROLES:
        assert evidence_ceiling(role) in PRINCIPAL_EVIDENCE_CLASSES
        assert allowed_domain_packs(role) <= set(DOMAIN_PACKS)
        assert allowed_domain_packs(role)


def test_untagged_streams_keep_validating() -> None:
    assert _stream("orders", "commerce", None).source_role is None


@pytest.mark.parametrize(
    ("role", "pack"),
    [
        ("system_of_record", "commerce"),
        ("system_of_record", "payments"),
        ("agent_runtime", "agent_activity"),
        ("tool_bridge", "agent_activity"),
        ("network_observer", "agent_activity"),
        ("authority_issuer", "authority"),
    ],
)
def test_allowed_role_pack_pairs(role: str, pack: str) -> None:
    assert _stream("s", pack, role).source_role == role


@pytest.mark.parametrize(
    ("role", "pack"),
    [
        # A runtime's own records are claims; they never establish commerce truth.
        ("agent_runtime", "commerce"),
        ("tool_bridge", "payments"),
        # Authority is declared on its own stream so its trust is explicit.
        ("system_of_record", "authority"),
        ("system_of_record", "agent_activity"),
        ("authority_issuer", "commerce"),
    ],
)
def test_rejected_role_pack_pairs(role: str, pack: str) -> None:
    assert role_domain_pack_violation(role, pack) is not None
    with pytest.raises(ValidationError, match="cannot declare domain_pack"):
        _stream("s", pack, role)


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _stream("s", "commerce", "vendor_magic")
    with pytest.raises(ValueError):
        evidence_ceiling("vendor_magic")


def test_cap_never_strengthens_and_clamps_overclaims() -> None:
    # A runtime cannot self-assert a deterministic binding on its own.
    assert cap_evidence("agent_runtime", "DETERMINISTIC_BINDING") == "PROVIDER_ASSERTED"
    assert cap_evidence("agent_runtime", "TEMPORALLY_CORRELATED") == "TEMPORALLY_CORRELATED"
    assert cap_evidence("authority_issuer", "VERIFIED_AUTHORITY") == "VERIFIED_AUTHORITY"
    assert cap_evidence("tool_bridge", "not-a-class") == "UNKNOWN"


def test_provider_roles_come_from_streams_not_vendor_labels() -> None:
    # One vendor, several roles: a spend platform is a system of record for
    # transactions and an authority issuer for card limits.
    streams = [
        _stream("transactions", "payments", "system_of_record"),
        _stream("card_limits", "authority", "authority_issuer"),
        _stream("legacy", "payments", None),
    ]
    assert provider_source_roles(streams) == {"system_of_record", "authority_issuer"}
    assert provider_source_roles([]) == frozenset()


def test_shopify_streams_declare_system_of_record() -> None:
    from connectors.providers.shopify.plugin import ShopifyOrdersPlugin

    manifest = ShopifyOrdersPlugin().manifest()
    assert manifest.streams
    assert {s.source_role for s in manifest.streams} == {"system_of_record"}
