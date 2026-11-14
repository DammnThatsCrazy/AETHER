"""Program A — reconciled authority map.

Pins the one-owner rule: the control plane owns convergence and activation, it
observes the surrounding authorities, and it has no interface at all to
canonical identity or graph mutation.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from connectors.managed_integrations import authority
from connectors.managed_integrations.authority import (
    CONTROL_PLANE_AUTHORITY_AREAS,
    CONTROL_PLANE_AUTHORITY_ASSIGNMENTS,
    RCP_FORBIDDEN_AUTHORITY_AREAS,
    RCP_NO_INTERFACE_AUTHORITY_AREAS,
    RCP_OBSERVED_AUTHORITY_AREAS,
    RCP_OWNED_AUTHORITY_AREAS,
    assert_authority_map_integrity,
    assignment_for,
    owner_of,
    rcp_role_for,
)


def test_authority_map_is_internally_consistent():
    assert_authority_map_integrity()


def test_every_area_is_assigned_exactly_once():
    areas = [assignment.area for assignment in CONTROL_PLANE_AUTHORITY_ASSIGNMENTS]
    assert len(areas) == len(set(areas))
    assert set(areas) == set(CONTROL_PLANE_AUTHORITY_AREAS)
    assert set(RCP_FORBIDDEN_AUTHORITY_AREAS) <= set(areas)


def test_control_plane_owns_convergence_and_activation_only():
    owned = {
        assignment.area
        for assignment in CONTROL_PLANE_AUTHORITY_ASSIGNMENTS
        if assignment.owner == "reconciled_control_plane"
    }
    assert owned == set(RCP_OWNED_AUTHORITY_AREAS)
    assert owner_of("control_plane_activation") == "reconciled_control_plane"
    assert rcp_role_for("control_plane_activation") == "own"


def test_external_authorities_are_observed_not_owned():
    for area in RCP_OBSERVED_AUTHORITY_AREAS:
        assert rcp_role_for(area) == "observe"
        assert owner_of(area) != "reconciled_control_plane"


def test_identity_and_graph_have_no_interface():
    for area in RCP_NO_INTERFACE_AUTHORITY_AREAS:
        assignment = assignment_for(area)
        assert assignment.rcp_role == "none"
        assert assignment.interface == ()


def test_unknown_area_fails_closed():
    with pytest.raises(KeyError):
        assignment_for("not_a_real_authority")


def test_forbidden_area_cannot_gain_an_interface(monkeypatch):
    original = authority.assignment_for("graph_mutation")
    tampered = replace(original, rcp_role="observe", interface=("read_graph",))
    monkeypatch.setattr(
        authority,
        "CONTROL_PLANE_AUTHORITY_ASSIGNMENTS",
        tuple(
            tampered if item.area == "graph_mutation" else item
            for item in authority.CONTROL_PLANE_AUTHORITY_ASSIGNMENTS
        ),
    )
    with pytest.raises(ValueError, match="must have rcp_role='none'"):
        authority.assert_authority_map_integrity()
