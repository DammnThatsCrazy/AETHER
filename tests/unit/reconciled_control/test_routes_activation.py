"""Read-only activation surface on the Kyber operator router.

``GET /activation`` exposes durable activation states plus derived effective
states; ``GET /activation/transitions`` exposes evidence for exactly one scope.
These tests drive the handlers directly against the in-memory seam and pin
fail-closed scope validation. There is deliberately no write/transition route in
this slice.
"""

from __future__ import annotations

import pytest

from shared.common.common import BadRequestError

from connectors.managed_integrations.activation import (
    ActivationScope,
    ControlPlaneActivationService,
    readiness_from_controls,
)
from connectors.managed_integrations.activation_repository import (
    get_activation_repository,
)
from connectors.managed_integrations.routes import (
    get_authority_map,
    list_activation_states,
    list_activation_transitions,
)

READY = readiness_from_controls({"control_plane_api": True}, evidence_ref="ev-1")


def _operator_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        "connectors.managed_integrations.routes._require_operator",
        lambda request: None,
    )


async def test_activation_list_empty_is_not_live(monkeypatch, rcp_flags):
    _operator_gate(monkeypatch)
    rcp_flags(enabled=True, reconciler_enabled=True, scheduler_enabled=True)
    body = await list_activation_states(
        request=None,
        scope_kind=None,
        tenant_id=None,
        environment_id=None,
        region=None,
        limit=50,
        offset=0,
    )  # type: ignore[arg-type]
    data = body["data"]
    assert data["count"] == 0
    assert "emergency_frozen" in data["activation_states_vocabulary"]
    assert "disabled" in data["effective_states_vocabulary"]


async def test_activation_scope_filter_returns_effective_state(monkeypatch, rcp_flags):
    _operator_gate(monkeypatch)
    rcp_flags(enabled=True, reconciler_enabled=True, scheduler_enabled=True)
    scope = ActivationScope(
        scope_kind="tenant_environment", tenant_id="tenant-a", environment_id="prod"
    )
    await ControlPlaneActivationService(
        repository=get_activation_repository()
    ).transition(scope, "advance", readiness=READY)

    body = await list_activation_states(
        request=None,
        scope_kind="tenant_environment",
        tenant_id="tenant-a",
        environment_id="prod",
        region=None,
        limit=50,
        offset=0,
    )  # type: ignore[arg-type]
    data = body["data"]
    assert data["count"] == 1
    assert data["activation_states"][0]["state"] == "detect"
    assert data["activation_states"][0]["effective_state"] == "detect"


async def test_activation_list_derives_tenant_scope_from_filters(monkeypatch, rcp_flags):
    _operator_gate(monkeypatch)
    rcp_flags(enabled=True, reconciler_enabled=True, scheduler_enabled=True)
    body = await list_activation_states(
        request=None,
        scope_kind=None,
        tenant_id="tenant-a",
        environment_id="prod",
        region=None,
        limit=50,
        offset=0,
    )  # type: ignore[arg-type]
    assert body["data"]["count"] == 1
    row = body["data"]["activation_states"][0]
    assert row["scope_kind"] == "tenant_environment"
    assert row["state"] == "shadow"


async def test_activation_partial_tenant_scope_rejected(monkeypatch):
    _operator_gate(monkeypatch)
    with pytest.raises(BadRequestError):
        await list_activation_states(
            request=None,
            scope_kind=None,
            tenant_id="tenant-a",
            environment_id=None,
            region=None,
            limit=50,
            offset=0,
        )  # type: ignore[arg-type]


async def test_activation_global_scope_rejects_tenant(monkeypatch):
    _operator_gate(monkeypatch)
    with pytest.raises(BadRequestError):
        await list_activation_states(
            request=None,
            scope_kind="global",
            tenant_id="tenant-a",
            environment_id="prod",
            region=None,
            limit=50,
            offset=0,
        )  # type: ignore[arg-type]


async def test_activation_scope_rejects_ambiguous_activation_id(monkeypatch):
    _operator_gate(monkeypatch)
    with pytest.raises(BadRequestError):
        await list_activation_states(
            request=None,
            scope_kind="tenant_environment",
            tenant_id="tenant:a",
            environment_id="prod",
            region=None,
            limit=50,
            offset=0,
        )  # type: ignore[arg-type]


async def test_activation_transitions_require_scope(monkeypatch):
    _operator_gate(monkeypatch)
    with pytest.raises(BadRequestError):
        await list_activation_transitions(
            request=None,
            scope_kind=None,
            tenant_id=None,
            environment_id=None,
            region=None,
            limit=50,
            offset=0,
        )  # type: ignore[arg-type]


async def test_activation_transitions_are_scoped(monkeypatch, rcp_flags):
    _operator_gate(monkeypatch)
    rcp_flags(enabled=True, reconciler_enabled=True, scheduler_enabled=True)
    scope = ActivationScope()
    await ControlPlaneActivationService(
        repository=get_activation_repository()
    ).transition(scope, "freeze", reason="incident", actor="oncall")

    body = await list_activation_transitions(
        request=None,
        scope_kind="global",
        tenant_id=None,
        environment_id=None,
        region=None,
        limit=50,
        offset=0,
    )  # type: ignore[arg-type]
    data = body["data"]
    assert data["count"] == 1
    assert data["activation_id"] == "rcpa:global:global:-:-"
    assert data["transitions"][0]["to_state"] == "emergency_frozen"
    assert data["transitions"][0]["actor"] == "oncall"


async def test_authority_map_is_readable_and_forbidden_areas_are_explicit(monkeypatch):
    _operator_gate(monkeypatch)
    body = await get_authority_map(request=None)  # type: ignore[arg-type]
    data = body["data"]
    assert data["forbidden_areas"] == ["graph_mutation"]
    by_area = {row["area"]: row for row in data["assignments"]}
    assert by_area["control_plane_activation"]["owner"] == "reconciled_control_plane"
    assert by_area["control_plane_activation"]["rcp_role"] == "own"
    assert by_area["graph_mutation"]["rcp_role"] == "none"
    assert by_area["graph_mutation"]["interface"] == []
    assert "readiness" in data["owners_vocabulary"]
    assert set(data["roles_vocabulary"]) == {"own", "observe", "none"}
