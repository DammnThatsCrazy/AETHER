from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.derivatives.product import (  # noqa: E402
    DERIVATIVES_ALERT_RULES,
    DERIVATIVES_REALTIME_TOPICS,
    DerivativesAccountView,
    DerivativesProductService,
    DerivativesProductSnapshot,
)
from services.derivatives.models import PositionEpochState, PositionSide, PositionStatus  # noqa: E402
from services.derivatives.routes import (  # noqa: E402
    OperatorActionRequest,
    derivatives_overview,
    derivatives_position_detail,
    kyber_derivatives_operator_action,
    product_service,
)
from shared.common.common import ForbiddenError, NotFoundError  # noqa: E402


class FakeTenant:
    def __init__(self, tenant_id="tenant-a", permissions=None, is_platform_admin=False):
        self.tenant_id = tenant_id
        self.permissions = set({"derivatives:read", "derivatives:export"} if permissions is None else permissions)
        self.is_platform_admin = is_platform_admin

    def require_permission(self, permission):
        if permission not in self.permissions:
            raise PermissionError(permission)


def request(tenant):
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


def position(tenant_id="tenant-a"):
    return PositionEpochState(
        tenant_id=tenant_id,
        trading_account_id="acct-1",
        canonical_market_id="mkt-btc-usd-perp",
        epoch_id="epoch-1",
        side=PositionSide.LONG,
        status=PositionStatus.CLOSED,
        size=Decimal("0"),
        realized_pnl=Decimal("15.00"),
        fees=Decimal("2.50"),
        opened_at="2026-07-01T00:00:00Z",
        closed_at="2026-07-02T00:00:00Z",
        source_fill_ids=["fill-open", "fill-close"],
    )


def seeded_service():
    service = DerivativesProductService()
    service.seed_snapshot(DerivativesProductSnapshot(
        tenant_id="tenant-a",
        accounts=(DerivativesAccountView("tenant-a", "acct-1", "hyperliquid", "active", last_sync_at="2026-07-04T00:00:00Z", historical_coverage_days=30),),
        positions=(position("tenant-a"), position("tenant-b")),
        reconciliation_variances=({"variance_type": "pnl", "severity": "medium"},),
    ))
    return service


def test_overview_accounts_positions_and_position_detail_are_tenant_scoped():
    service = seeded_service()
    overview = service.overview("tenant-a")
    assert overview["connected_accounts"] == 1
    assert overview["net_pnl"] == "12.50"
    assert overview["execution_by_aether"] is False
    assert len(service.accounts("tenant-a")) == 1
    assert [p["tenant_id"] for p in service.positions("tenant-a")] == ["tenant-a"]
    detail = service.position_detail("tenant-a", "epoch-1")
    assert detail["evidence"]["source_fill_ids"] == ["fill-open", "fill-close"]
    assert service.position_detail("tenant-b", "epoch-1") is None


def test_profile_realtime_alerts_and_usage_metering_are_product_ready():
    service = seeded_service()
    profile = service.behavior("tenant-a")
    assert profile["dimension"] == "derivatives"
    assert profile["state"] == "complete"
    assert service.realtime_catalog("tenant-a")["topics"] == list(DERIVATIVES_REALTIME_TOPICS)
    rules = service.alert_catalog("tenant-a")["rules"]
    assert {r["rule_key"] for r in rules} == set(DERIVATIVES_ALERT_RULES)
    usage = service.meter_usage("tenant-a", "active_positions", Decimal("1"))
    assert usage["quantity"] == "1"
    with pytest.raises(ValueError):
        service.meter_usage("tenant-a", "unknown", Decimal("1"))


def test_kyber_operations_and_operator_actions_are_bounded_and_audited():
    service = seeded_service()
    assert service.kyber_fleet("operator")["account_count"] == 1
    assert service.kyber_data_quality("operator")["snapshot_delta_mismatches"] == 1
    assert service.kyber_reconciliation("operator", tenant_id="tenant-a")["variance_count"] == 1
    action = service.record_operator_action("operator", "tenant-a", "reconcile_position", {"position_epoch_id": "epoch-1"})
    assert action["audited"] is True
    assert action["execution_by_aether"] is False
    assert action["action_id"] == service.record_operator_action("operator", "tenant-a", "reconcile_position", {"position_epoch_id": "epoch-1"})["action_id"]
    with pytest.raises(ValueError):
        service.record_operator_action("operator", "tenant-a", "submit_trade", {})


@pytest.mark.anyio
async def test_tenant_routes_enforce_permissions_and_not_found(monkeypatch):
    product_service.seed_snapshot(DerivativesProductSnapshot(
        tenant_id="tenant-a",
        accounts=(DerivativesAccountView("tenant-a", "acct-1", "hyperliquid", "active"),),
        positions=(position("tenant-a"),),
    ))
    response = await derivatives_overview(request(FakeTenant()))
    assert response["data"]["connected_accounts"] == 1
    with pytest.raises(PermissionError):
        await derivatives_overview(request(FakeTenant(permissions=set())))
    with pytest.raises(NotFoundError):
        await derivatives_position_detail("missing", request(FakeTenant()))


@pytest.mark.anyio
async def test_kyber_routes_require_platform_admin_and_record_operator_action():
    body = OperatorActionRequest(tenant_id="tenant-a", action="reconcile_position", scope={"position_epoch_id": "epoch-1"})
    # Operator identity is now the canonical kyber:operator grant (the never-set
    # is_platform_admin flag was removed); the domain admin permission is the
    # secondary requirement.
    operator = FakeTenant("operator", permissions={"kyber:operator", "derivatives:connector:admin"})
    response = await kyber_derivatives_operator_action(body, request(operator))
    assert response["data"]["audited"] is True
    non_operator = FakeTenant("operator", permissions={"derivatives:connector:admin"})
    with pytest.raises(ForbiddenError):
        await kyber_derivatives_operator_action(body, request(non_operator))
