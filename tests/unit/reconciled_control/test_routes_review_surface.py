"""Phase-3 operator review surface — approvals + action-required routes.

The two review endpoints (``GET /approvals``, ``GET /action-required``) sit on
the read-only operator router. These tests drive the handlers directly against
the module-local in-memory stores (the repo singleton seam), pinning the
operator gate, the filters and the fail-closed validation.
"""

from __future__ import annotations

from shared.common.common import BadRequestError

from services.managed_integrations.execution_records_repository import (
    ActionRequiredView,
    ChangeSetApprovalView,
    get_action_required_repository,
    get_change_set_approval_repository,
)
from services.managed_integrations.routes import (
    list_action_required,
    list_change_set_approvals,
)


async def _seed_approvals() -> None:
    repo = get_change_set_approval_repository()
    for idx, (changeset, decision) in enumerate(
        (("cs-1", "approved"), ("cs-1", "denied"), ("cs-2", "approved"))
    ):
        await repo.create(
            ChangeSetApprovalView(
                approval_id=f"appr-{idx}",
                changeset_ref=changeset,
                tenant_id="tenant-a",
                environment_id="prod",
                required_approval_ref="gate:simulation",
                granted_role="olympus_operator",
                granted_by_actor="operator-1",
                decision=decision,
                note=None,
                decided_at=f"2026-09-06T10:00:{idx:02d}Z",
            )
        )


async def _seed_action_required() -> None:
    repo = get_action_required_repository()
    for idx, status in enumerate(("open", "resolved", "open")):
        await repo.create(
            ActionRequiredView(
                action_id=f"ar-{idx}",
                tenant_ref="tenant-a",
                managed_integration_ref="mi-1",
                environment_id="prod",
                action_type="rollout_engine_required",
                reason="R2 automation gate",
                impact="blocked",
                deadline=None,
                required_actor="olympus_operator",
                required_action="review",
                continuity_state="no_data_loss",
                data_loss_expected=False,
                resolution_ref=None,
                status=status,
                created_at=f"2026-09-06T10:00:{idx:02d}Z",
            )
        )


def _operator_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.managed_integrations.routes._require_operator",
        lambda request: None,
    )


async def test_approvals_list_aggregate(monkeypatch) -> None:
    _operator_gate(monkeypatch)
    await _seed_approvals()
    body = await list_change_set_approvals(
        request=None, tenant_id=None, environment_id=None, changeset_ref=None,
        decision=None, limit=50, offset=0,  # type: ignore[arg-type]
    )
    data = body["data"]
    assert data["count"] == 3
    assert [a["approval_id"] for a in data["approvals"]] == [
        "appr-2",
        "appr-1",
        "appr-0",
    ]


async def test_approvals_list_filters_are_anded(monkeypatch) -> None:
    _operator_gate(monkeypatch)
    await _seed_approvals()
    body = await list_change_set_approvals(
        request=None,  # type: ignore[arg-type]
        tenant_id="tenant-a",
        environment_id="prod",
        changeset_ref="cs-1",
        decision="approved",
        limit=50,
        offset=0,
    )
    data = body["data"]
    assert data["count"] == 1
    assert data["approvals"][0]["approval_id"] == "appr-0"


async def test_approvals_bad_decision_rejected(monkeypatch) -> None:
    _operator_gate(monkeypatch)
    try:
        await list_change_set_approvals(
            request=None, decision="maybe", limit=50, offset=0  # type: ignore[arg-type]
        )
    except BadRequestError:
        pass
    else:
        raise AssertionError("invalid decision must raise BadRequestError")


async def test_action_required_list_aggregate(monkeypatch) -> None:
    _operator_gate(monkeypatch)
    await _seed_action_required()
    body = await list_action_required(
        request=None, tenant_id=None, status=None, limit=50, offset=0,  # type: ignore[arg-type]
    )
    data = body["data"]
    assert data["count"] == 3
    assert [a["action_id"] for a in data["action_required"]] == [
        "ar-2",
        "ar-1",
        "ar-0",
    ]


async def test_action_required_status_filter(monkeypatch) -> None:
    _operator_gate(monkeypatch)
    await _seed_action_required()
    body = await list_action_required(
        request=None, tenant_id=None, status="open", limit=50, offset=0,  # type: ignore[arg-type]
    )
    data = body["data"]
    assert data["count"] == 2
    assert all(a["status"] == "open" for a in data["action_required"])


async def test_action_required_bad_status_rejected(monkeypatch) -> None:
    _operator_gate(monkeypatch)
    try:
        await list_action_required(
            request=None, status="in_review", limit=50, offset=0  # type: ignore[arg-type]
        )
    except BadRequestError:
        pass
    else:
        raise AssertionError("invalid status must raise BadRequestError")


async def test_tenant_filter_narrows_action_required(monkeypatch) -> None:
    _operator_gate(monkeypatch)
    await _seed_action_required()
    body = await list_action_required(
        request=None, tenant_id="other-tenant", status=None, limit=50, offset=0  # type: ignore[arg-type]
    )
    assert body["data"]["count"] == 0
